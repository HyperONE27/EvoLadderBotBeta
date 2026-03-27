"""Pytest conftest — ensure backend.core.config can be imported without
a real .env file by setting required env vars to dummy values before
any backend module is loaded.
"""

import os

# These must be set before backend.core.config is imported (which happens
# at collection time when test files import algorithm modules).
_DUMMY_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "SUPABASE_BUCKET_NAME": "test-bucket",
    "ALLOW_AI_PLAYERS": "false",  # prod behavior: AI players are rejected
    "COERCE_INDETERMINATE_AS_LOSS": "false",  # prod behavior: indeterminate replays fail validation
}

for key, value in _DUMMY_ENV.items():
    os.environ.setdefault(key, value)
