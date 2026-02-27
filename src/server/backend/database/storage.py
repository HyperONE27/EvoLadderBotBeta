from supabase import create_client, Client

from server.backend.config import DATABASE


# Connection functions
def create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])


def create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])


class StorageReader:
    def __init__(self) -> None:
        self.client: Client = create_read_client()


class StorageWriter:
    def __init__(self) -> None:
        self.client: Client = create_write_client()
