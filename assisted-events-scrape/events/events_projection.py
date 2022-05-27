from utils import get_event_id
from clients import create_es_client_from_env
from kafka import KafkaConsumer
import json

def project():
    es_client = create_es_client_from_env()
    consumer = KafkaConsumer('my-topic',
                             bootstrap_servers=['event-store-kafka:9092'],
                             group_id="my-group-id",
                             value_deserializer=deseralizer,
                             consumer_timeout_ms=10000,
                             auto_offset_reset='earliest',
                             enable_auto_commit=True
    )
    current_cluster = {}
    current_version = None
    for message in consumer:
        value = message.value
        if value["event"] == ".component_versions":
            current_version = value["payload"]
        if value["event"] == ".clusters":
            payload = value["payload"]
            current_cluster[payload["id"]] = payload
        if value["event"] == ".events":
            event = value["payload"]
            event["cluster"] = current_cluster.get(event["cluster_id"], {})
            event["component_versions"] = current_version
            resp = es_client.index(index="test-events", id=get_event_id(event), body=event)

def deseralizer(m):
    try:
        return json.loads(m.decode("utf-8"))
    except:
        log.warning(f"error deserializing message: {m}")
        return {}
