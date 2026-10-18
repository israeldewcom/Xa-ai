from pydantic import BaseModel


class QuotaStatus(BaseModel):
    chat: int
    chat_tokens: int
    upload_bytes: int
    jobs: int
    agent_runs: int
    voice_seconds: int


class UsageAggregate(BaseModel):
    kind: str
    count: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
