from kafka import KafkaProducer
from kafka.errors import KafkaError
from opensearchpy import OpenSearch
import json
from utils import log

class EventsProducer:
    def __init__(self, es_client: OpenSearch, kafka_producer: KafkaProducer):
        self._es_client = es_client
        self._kafka_producer = kafka_producer

    def produce(self):
        events = self._get_events()
        for event in events:
            self._kafka_producer.send("my-topic", key=get_key(event), value=event)
        self._kafka_producer.flush()

    def _get_events(self):
        search = []
        search.append({"index": ".clusters"})
        search.append({"query": {"match_all" : {}}, "size": 100, "sort":[{"updated_at":"asc"}]})
        search.append({"index": ".component_versions"})
        search.append({"query": {"match_all" : {}}, "size": 100, "sort":[{"timestamp":"asc"}]})
        search.append({"index": ".events"})
        search.append({"query": {"match_all" : {}}, "size": 100, "sort":[{"event_time":"asc"}]})

        request = ""
        for item in search:
            request = request + json.dumps(item) + "\n"
        resp = self._es_client.msearch(body = request)
        all_events = []
        if "responses" in resp:
            for r in resp["responses"]:
                all_events.extend([{"event": x["_index"], "payload": x["_source"]} for x in r["hits"]["hits"]])
        all_events.sort(key=by_date)
        return all_events

def by_date(item: dict):
    time_fields = ["event_time", "updated_at", "timestamp"]
    for time_field in time_fields:
        if time_field in item:
            return item[time_field]
    log.warning(f"Item {item} does not have time field {time_fields}")
    return 0

def get_key(item: dict):
    id_fields = ["cluster_id", "id"]
    for id_field in id_fields:
        if id_field in item:
            return bytes(item[id_field].encode("utf-8"))
    log.warning(f"Item {item} does not have id field {id_fields}")
    return bytes("0".encode("utf-8"))
