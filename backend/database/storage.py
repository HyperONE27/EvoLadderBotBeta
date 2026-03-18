import structlog

from supabase import create_client, Client

from backend.core.config import DATABASE, STORAGE

logger = structlog.get_logger(__name__)


# Connection functions
def _create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])


def _create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])


class StorageReader:
    def __init__(self) -> None:
        self.bucket: str = STORAGE["bucket_name"]
        self.client: Client = _create_read_client()

    def get_public_url(self, storage_path: str) -> str:
        """Return the public URL for a file in Supabase Storage."""
        return self.client.storage.from_(self.bucket).get_public_url(storage_path)


class StorageWriter:
    def __init__(self) -> None:
        self.bucket: str = STORAGE["bucket_name"]
        self.client: Client = _create_write_client()

    def upload_replay(self, replay_bytes: bytes, storage_path: str) -> str | None:
        """Upload replay bytes to Supabase Storage and return the public URL.

        Returns None on failure.
        """
        try:
            self.client.storage.from_(self.bucket).upload(
                storage_path,
                replay_bytes,
                {"content-type": "application/octet-stream", "upsert": "true"},
            )
            public_url: str = self.client.storage.from_(self.bucket).get_public_url(
                storage_path
            )
            return public_url
        except Exception as exc:
            logger.error(
                "Supabase Storage upload failed", path=storage_path, error=str(exc)
            )
            return None
