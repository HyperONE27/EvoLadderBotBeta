from datetime import datetime
from typing import Dict, TypedDict, List

class AdminCommandJSONB(TypedDict):
    command: str
    arguments: List[str]
    performed_at: datetime

class PlayerCommandJSONB(TypedDict):
    command: str
    arguments: List[str]
    performed_at: datetime

class PlayerUpdateJSONB(TypedDict):
    setting_name: str
    old_value: str