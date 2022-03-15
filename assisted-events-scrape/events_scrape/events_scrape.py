#!/usr/bin/env python3

import os
import time
import urllib3
import logging
import elasticsearch
import sentry_sdk

from queue import Queue

from .assisted_service_api import ClientFactory
from utils.logger import log
from repositories.cluster_repository import ClusterRepository
from repositories.event_repository import EventRepository
from storage.cluster_events_storage import ClusterEventsStorage
from workers.cluster_events_worker import ClusterEventsWorker
from utils.counters import ErrorCounter
from utils.counters import Changes

RETRY_INTERVAL = 60 * 5

DEFAULT_ENV_ERRORS_BEFORE_RESTART = "100"
DEFAULT_ENV_MAX_IDLE_MINUTES = "120"
DEFAULT_ENV_N_WORKERS = "5"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

es_logger = logging.getLogger('elasticsearch')
es_logger.setLevel(logging.WARNING)


class ScrapeEvents:
    def __init__(self, config: dict):
        if config["backup_destination"] and not os.path.exists(config["backup_destination"]):
            os.makedirs(config["backup_destination"])

        self.client = ClientFactory.create_client(
            url=config["inventory_url"],
            offline_token=config["offline_token"])

        elastic_config = config["elasticsearch"]
        http_auth = None
        if elastic_config["username"]:
            http_auth = (elastic_config["username"], elastic_config["password"])
        es_client = elasticsearch.Elasticsearch(elastic_config["host"], http_auth=http_auth)
        self.cluster_events_storage = ClusterEventsStorage(
            self.client, es_client,
            config["backup_destination"], config["inventory_url"], elastic_config["index"])

        self.cluster_repo = ClusterRepository(self.client)
        self.event_repo = EventRepository(self.client)

        self.errors_before_restart = config["errors_before_restart"]
        self.max_idle_minutes = config["max_idle_minutes"]

        self.clusters_queue = Queue()
        workers_config = {
            "queue": self.clusters_queue,
            "error_counter": ErrorCounter(),
            "changes": Changes(),
            "sentry": config["sentry"]
        }
        self.start_workers(config["n_workers"], workers_config)

    def start_workers(self, n_workers: int, workers_config: dict) -> None:
        for n in range(n_workers):
            workers_config["name"] = f"Worker-{n}"
            worker = ClusterEventsWorker(workers_config,
                                         cluster_repository=self.cluster_repo,
                                         event_repository=self.event_repo,
                                         cluster_events_storage=self.cluster_events_storage)

            worker.daemon = True
            worker.start()

    def is_idle(self):
        return not self.changes.has_changed_in_last_minutes(self.max_idle_minutes)

    def has_too_many_unexpected_errors(self):
        return self.error_counter.get_errors() > self.errors_before_restart

    def run_service(self):

        clusters = self.cluster_repo.list_clusters()

        if not clusters:
            log.warning(f'No clusters were found, waiting {RETRY_INTERVAL / 60} min')
            time.sleep(RETRY_INTERVAL)
            return None

        cluster_count = len(clusters)
        for cluster in clusters:
            self.clusters_queue.put(cluster)
        log.info(f"Added {cluster_count} cluster IDs to queue, joining queue...")
        self.clusters_queue.join()
        log.info("Finish syncing all clusters - sleeping 30 seconds")
        time.sleep(30)


def get_env(key, mandatory=False, default=None):
    res = os.environ.get(key, default)
    if res == "":
        res = default

    if res is not None:
        res = res.strip()
    elif mandatory:
        raise ValueError(f'Mandatory environment variable is missing: {key}')

    return res


def handle_arguments():
    return {
        "assisted_service_url": get_env("ASSISTED_SERVICE_URL"),
        "offline_token": get_env("OFFLINE_TOKEN", mandatory=True),
        "es_server": get_env("ES_SERVER", mandatory=True),
        "es_user": get_env("ES_USER"),
        "es_pass": get_env("ES_PASS"),
        "index": get_env("ES_INDEX", mandatory=True),
        "backup_destination": get_env("BACKUP_DESTINATION"),
        "sentry_dsn": get_env("SENTRY_DSN", default=""),
        "max_idle_minutes": get_env("MAX_IDLE_MINUTES", default=DEFAULT_ENV_MAX_IDLE_MINUTES),
        "errors_before_restart": get_env("ERRORS_BEFORE_RESTART", default=DEFAULT_ENV_ERRORS_BEFORE_RESTART),
        "n_workers": get_env("N_WORKERS", default=DEFAULT_ENV_N_WORKERS)
    }


def initSentry(sentry_dsn):
    if sentry_dsn != "":
        sentry_sdk.init(
            sentry_dsn
        )
        return True
    return False


def main():
    args = handle_arguments()
    is_sentry_enabled = initSentry(args["sentry_dsn"])

    config = {
        "inventory_url": args["assisted_service_url"],
        "backup_destination": args["backup_destination"],
        "offline_token": args["offline_token"],
        "sentry": {
            "enabled": is_sentry_enabled,
        },
        "elasticsearch": {
            "host": args["es_server"],
            "index": args["index"],
            "username": args["es_user"],
            "password": args["es_pass"],
        },
        "max_idle_minutes": int(args["max_idle_minutes"]),
        "errors_before_restart": int(args["errors_before_restart"]),
        "n_workers": int(args["n_workers"])
    }
    should_run = True
    while should_run:
        scrape_events = ScrapeEvents(config)
        scrape_events.run_service()

        should_run = scrape_events.is_idle() or scrape_events.has_too_many_unexpected_errors()
