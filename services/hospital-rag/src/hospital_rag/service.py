from .llm import LLM
from .prompt import NOT_FOUND_MESSAGE, PROMPT_VERSION, build_messages, parse_answer
from .schemas import GenerateIn, GenerateOut


async def generate(req: GenerateIn, llm: LLM) -> GenerateOut:
    if not req.chunks:
        return GenerateOut(
            answer=NOT_FOUND_MESSAGE, cited_chunk_ids=[], invalid_citations=0, not_found=True,
            finish_reason="skipped", tokens_in=0, tokens_out=0, model=req.model,
            prompt_version=PROMPT_VERSION, latency_ms=0,
        )
    messages, labels = build_messages(req.query, [(c.id, c.text) for c in req.chunks])
    result = await llm.complete(messages, req.model)
    parsed = parse_answer(result.text, labels)
    return GenerateOut(
        answer=parsed.answer, cited_chunk_ids=parsed.cited_chunk_ids,
        invalid_citations=parsed.invalid_citations, not_found=parsed.not_found,
        finish_reason=result.finish_reason, tokens_in=result.tokens_in,
        tokens_out=result.tokens_out, model=result.model,
        prompt_version=PROMPT_VERSION, latency_ms=result.latency_ms,
    )
