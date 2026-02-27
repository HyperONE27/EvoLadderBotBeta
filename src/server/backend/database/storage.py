from supabase import create_client, Client

from server.backend.config import STORAGE

# Connection functions
def create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])

def create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])

class DatabaseStorage:
    def __init__(self) -> None:
        self.client: Client = create_client(STORAGE["url"], STORAGE["service_role_key"])