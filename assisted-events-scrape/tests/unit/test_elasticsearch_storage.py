import pytest
import elasticsearch
from storage import ElasticsearchStorage
from elasticmock import elasticmock

class TestElasticsearchStorage:
    def setup(self):
        self._mock_items = [
            {"foo":"bar"},
            {"bar":"foo"}
        ]

    @elasticmock
    def test_store(self, _iterator_items):
        es_client = elasticsearch.Elasticsearch()
        store = ElasticsearchStorage(es_client, "myindex", self._get_id)
        (items_count, errors) = store.store_events(_iterator_items)
        expected_items_count = 2
        assert [] == errors
        assert expected_items_count == items_count

    @pytest.fixture
    def _iterator_items(self):
        return [
            {"foo":"bar"},
            {"bar":"foo"}
        ]

    def _get_id(self, item: dict) -> str:
        return hash(str(item))
