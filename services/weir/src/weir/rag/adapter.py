"""HTTP client for hospital-rag's /retrieve and /generate (the two-step split Weir needs)."""
import httpx
from pydantic import BaseModel, ValidationError


class RagError(Exception):
    """kind: rate_limited | timeout | unavailable | bad_response"""

    def __init__(self, kind: str, detail: str = "", retry_after: float | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after


class RetrievedChunk(BaseModel):
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


class RetrieveResult(BaseModel):
    chunks: list[RetrievedChunk]
    top_score: float
    score_gap: float
    context_tokens: int
    kb_version: str | None
    latency_ms: int


class GenerateResult(BaseModel):
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


class RagClient:
    def __init__(self, base_url: str, timeout_s: float, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def retrieve(self, query: str, namespace: str, k: int) -> RetrieveResult:
        data = await self._post("/retrieve", {"query": query, "namespace": namespace, "k": k})
        return _parse(RetrieveResult, data)

    async def generate(self, query: str, namespace: str, chunks: list[RetrievedChunk], model: str) -> GenerateResult:
        payload = {"query": query, "namespace": namespace, "model": model,
                   "chunks": [c.model_dump() for c in chunks]}
        return _parse(GenerateResult, await self._post("/generate", payload))

    async def health(self) -> bool:
        try:
            return (await self._client.get("/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as e:
            raise RagError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise RagError("unavailable", str(e)) from e
        if response.status_code == 200:
            body = _json_or_none(response)
            if body is None:
                raise RagError("bad_response", f"200 with non-JSON body: {response.text[:100]}")
            return body
        body = _json_or_none(response)
        if response.status_code == 503 and body and body.get("error") == "rate_limited":
            raise RagError("rate_limited", "provider rate limit", body.get("retry_after"))
        if response.status_code == 504:
            raise RagError("timeout", response.text[:300])
        raise RagError("bad_response", f"{response.status_code}: {response.text[:300]}")


def _parse[M: BaseModel](model: type[M], data: dict) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise RagError("bad_response", f"unexpected {model.__name__} shape: {e.error_count()} error(s)") from e


def _json_or_none(response: httpx.Response) -> dict | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
