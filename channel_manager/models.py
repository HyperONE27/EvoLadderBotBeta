from pydantic import BaseModel


class ChannelCreateRequest(BaseModel):
    match_id: int
    match_mode: str  # "1v1", "2v2", "FFA"
    discord_uids: list[int]


class ChannelCreateResponse(BaseModel):
    channel_id: int
    message_url: str


class ChannelDeleteResponse(BaseModel):
    success: bool


class ChannelMessageRequest(BaseModel):
    discord_uid: int
    content: str
    timestamp: str  # ISO 8601 UTC string


class ChannelMessageResponse(BaseModel):
    success: bool
