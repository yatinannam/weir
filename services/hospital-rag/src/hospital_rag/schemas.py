from pydantic import BaseModel, Field, field_validator


class RetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    k: int | None = Field(default=None, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query is blank")
        return v.strip()


class ChunkOut(BaseModel):
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


class RetrieveOut(BaseModel):
    chunks: list[ChunkOut]
    top_score: float
    score_gap: float
    context_tokens: int
    kb_version: str | None
    latency_ms: int


class ChunkIn(BaseModel):
    id: str
    text: str


class GenerateIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    chunks: list[ChunkIn] = Field(max_length=10)
    model: str


class GenerateOut(BaseModel):
    answer: str
    cited_chunk_ids: list[str]
    invalid_citations: int
    not_found: bool
    finish_reason: str
    tokens_in: int
    tokens_out: int
    model: str
    prompt_version: str
    latency_ms: int
