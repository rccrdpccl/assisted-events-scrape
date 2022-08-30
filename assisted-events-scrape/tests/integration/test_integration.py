from config import ElasticsearchConfig
import opensearchpy
import waiting
import boto3
import os
import re
import json
import random
from typing import List
from config import EventStoreConfig
from waiting import TimeoutExpired
from utils import log
import pytest

ALL_EVENTS_NUMBER = 101
ALL_CLUSTERS_NUMBER = 2
ALL_VERSIONS_NUMBER = 1
ASSERTION_TIMEOUT_SECONDS = 2
ASSERTION_WAIT_SECONDS = 1


class TestIntegration:

    @classmethod
    def setup_class(cls):
        """Setup s3 client as it is used by multiple test cases"""
        cls._s3_bucket_name = "mybucket"
        cls._s3_client = cls._get_s3_client()

    @classmethod
    def teardown_class(cls):
        """Cleanup objects generated by export job. They will be regenerated when the tests
        are run by `make integration-test`"""
        objects = cls._s3_client.list_objects(Bucket=cls._s3_bucket_name)
        for obj in objects['Contents']:
            cls._s3_client.delete_object(Bucket=cls._s3_bucket_name, Key=obj["Key"])

    def test_event_scrape(self, _wait_for_elastic):
        aggregated_events_index = self._config.index_prefix + "*"
        expected_count_idx = {
            aggregated_events_index: ALL_EVENTS_NUMBER,
            EventStoreConfig.EVENTS_INDEX: ALL_EVENTS_NUMBER,
            EventStoreConfig.CLUSTER_EVENTS_INDEX: ALL_CLUSTERS_NUMBER,
            EventStoreConfig.COMPONENT_VERSIONS_EVENTS_INDEX: ALL_VERSIONS_NUMBER,
        }

        index_pattern = f"{self._config.index_prefix}*"
        # As elasticsearch is eventually consistent, make sure data is synced
        self._es_client.indices.refresh(index=index_pattern)

        def check_document_count(index, expected_count):
            documents_count = self._es_client.count(index=index)['count']
            if documents_count != expected_count:
                log.warning(f"Index {index}: found {documents_count} documents, expected {expected_count}")
                return False
            return True

        for index, expected_count in expected_count_idx.items():
            try:
                waiting.wait(
                    lambda: check_document_count(index, expected_count),
                    timeout_seconds=ASSERTION_TIMEOUT_SECONDS,
                    sleep_seconds=ASSERTION_WAIT_SECONDS,
                    waiting_for=f"{index} document count to be {expected_count}"
                )
                # Wait function succeeded, it means doc count was checked within
                assert True
            except TimeoutExpired:
                # Wait function expired, it means doc count could not match in the given time
                assert False
        query = {
            "size": 1,
            "query": {
                "term": {
                    "cluster.id": {
                        "value": "d386f7df-03ba-46bf-a49b-f6b65a0fb90d"
                    }
                }
            }
        }
        index = f"{self._config.index_prefix}*"
        response = self._es_client.search(index=index, body=query)
        assert len(response["hits"]["hits"]) > 0

        doc = response["hits"]["hits"][0]
        source = doc["_source"]
        assert "infra_env" in source["cluster"]
        assert source["cluster"]["infra_env"]["org_id"] == "xxxxxxxx"
        assert source["cluster"]["infra_env"]["type"] == "full-iso"

        assert "user_name" not in source["cluster"]
        assert "user_id" in source["cluster"]
        assert "cluster_state_id" in source["cluster"]

        query = {
            "size": 1,
            "query": {
                "match_all": {}
            }
        }
        response = self._es_client.search(index=".clusters", body=query)
        doc = response["hits"]["hits"][0]
        source = doc["_source"]
        assert "infra_env" not in source
        assert "user_name" not in source
        assert "user_id" in source
        assert "cluster_state_id" in source
        assert source["cluster_state_id"] == doc["_id"]

    def test_s3_uploaded_files(self):
        objects = self._s3_client.list_objects(Bucket=self._s3_bucket_name)
        # it should have one upload each event type
        assert len(objects['Contents']) == 5
        assert at_least_one_matches_key(objects['Contents'], "Key", ".events/2022-03-08/.*")
        assert at_least_one_matches_key(objects['Contents'], "Key", ".events/2022-03-09/.*")
        assert at_least_one_matches_key(objects['Contents'], "Key", ".clusters/[0-9]{4}-[0-9]{2}-[0-9]{2}/.*")
        assert at_least_one_matches_key(objects['Contents'], "Key", ".component_versions/[0-9]{4}-[0-9]{2}-[0-9]{2}/.*")
        assert at_least_one_matches_key(objects['Contents'], "Key", ".infra_envs/[0-9]{4}-[0-9]{2}-[0-9]{2}/.*")

    def test_s3_exported_cluster_object(self):
        cluster_export = get_first_object_matching_key(
            client=self._s3_client,
            bucket=self._s3_bucket_name,
            match=".*clusters.*")
        clusters = [json.loads(line) for line in cluster_export["Body"].readlines()]

        random_cluster = random.choice(clusters)
        assert "user_name" not in random_cluster
        assert "user_id" in random_cluster
        assert "cluster_state_id" in random_cluster

    def test_s3_exported_events_object(self):
        events_export = get_first_object_matching_key(
            client=self._s3_client,
            bucket=self._s3_bucket_name,
            match=".*events.*")
        events = [json.loads(line) for line in events_export["Body"].readlines()]

        random_event = random.choice(events)
        assert "event_time" in random_event
        assert "cluster_id" in random_event
        assert "event_id" in random_event

    @classmethod
    def _get_s3_client(cls):
        endpoint_url = os.getenv("AWS_S3_ENDPOINT")
        session = boto3.Session(
            aws_access_key_id="myaccesskey",
            aws_secret_access_key="mysecretkey"
        )
        return session.client('s3', endpoint_url=f"{endpoint_url}")

    @pytest.fixture
    def s3_uploaded_filenames(self):
        objects = self._s3_client.list_objects(Bucket=self._s3_bucket_name)
        yield [obj["Key"] for obj in objects["Contents"]]

    @pytest.fixture
    def _wait_for_elastic(self):
        self._config = ElasticsearchConfig.create_from_env()
        self._es_client = opensearchpy.OpenSearch(self._config.host)
        waiting.wait(
            self._is_elastic_ready,
            timeout_seconds=300,
            sleep_seconds=5,
            waiting_for="elasticsearch to become ready",
            expected_exceptions=Exception,
        )

    def _is_elastic_ready(self) -> bool:
        index = self._config.index_prefix + "*"
        is_elastic_ready = self._es_client.indices.exists(index=index)
        if is_elastic_ready:
            return True
        return False


def get_first_object_matching_key(client, bucket: str, match: str) -> bool:
    objects = client.list_objects(Bucket=bucket)
    for obj in objects["Contents"]:
        if "Key" not in obj:
            continue
        if re.search(match, obj["Key"]):
            return client.get_object(Bucket=bucket, Key=obj["Key"])
    return None


def at_least_one_matches_key(objects: List[dict], key: str, match: str) -> bool:
    for obj in objects:
        if key not in obj:
            continue
        if re.search(match, obj[key]):
            return True
    return False
