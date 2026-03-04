from supabase import create_client, Client

from server.backend.config import DATABASE, STORAGE


# Connection functions
def create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])


def create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])


class StorageReader:
    def __init__(self) -> None:
        self.bucket: str = STORAGE["bucket_name"]
        self.client: Client = create_read_client()

    def download_file(self) -> None:
        pass

    def download_replay(self) -> None:
        pass


class StorageWriter:
    def __init__(self) -> None:
        self.bucket: str = STORAGE["bucket_name"]
        self.client: Client = create_write_client()

    def upload_file(self) -> None:
        pass

    def upload_replay(self) -> None:
        pass
