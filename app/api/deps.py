from fastapi.requests import HTTPConnection
from temporalio.client import Client


def get_temporal_client(connection: HTTPConnection) -> Client:
    return connection.app.state.temporal_client
