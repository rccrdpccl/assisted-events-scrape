from clients import create_es_client_from_env
from .events_producer import EventsProducer
from kafka import KafkaProducer
import json


def hydrate():
    kafka_producer = KafkaProducer(
        bootstrap_servers=['event-store-kafka:9092'],
        value_serializer=lambda m: json.dumps(m).encode('utf-8')
    )

    producer = EventsProducer(create_es_client_from_env(), kafka_producer)
    producer.produce()
