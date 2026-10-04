"""Router features from the question and the retrieval result (Phase 3 addendum §3.1)."""
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..cache.guards import BypassRules, phrase_pattern
from ..config import Tier
from ..rag.adapter import RetrieveResult
from ..text import normalize

# "... and when ...": a second question joined by "and". Not counted right after "?" / "." / "!",
# where the "?" already counted it.
AND_QUESTION = re.compile(r"(?<![?.!]) and (?:what|when|where|how|which|who|why|is|are|can|does|do)\b")


@dataclass(frozen=True)
class Features:
    tokens: int
    has_reasoning_words: bool
    num_questions: int
    top_score: float
    score_gap: float
    context_tokens: int
    is_clinical: bool
    forced_tier: Tier | None = None


def count_questions(text: str) -> int:
    t = normalize(text)
    return max(1, t.count("?") + len(AND_QUESTION.findall(t)))


class FeatureExtractor:
    def __init__(self, count_tokens: Callable[[str], int], rules: BypassRules, reasoning_words: list[str]):
        self._count_tokens = count_tokens
        self._rules = rules
        self._reasoning = phrase_pattern(reasoning_words)

    def extract(self, query: str, retrieved: RetrieveResult, forced_tier: Tier | None = None) -> Features:
        t = normalize(query)
        return Features(
            tokens=self._count_tokens(t),
            has_reasoning_words=bool(self._reasoning and self._reasoning.search(t)),
            num_questions=count_questions(t),
            top_score=retrieved.top_score,
            score_gap=retrieved.score_gap,
            context_tokens=retrieved.context_tokens,
            is_clinical=self._rules.clinical(query),
            forced_tier=forced_tier,
        )
