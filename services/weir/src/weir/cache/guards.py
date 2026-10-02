"""Which questions may use the cache (main spec §6.1) and which answers may be stored (§6.3)."""
import re

from ..config import BypassConfig, WeirConfig
from ..rag.adapter import GenerateResult
from ..text import normalize

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\d[ -]?){7,}(?!\d)")
LONG_ID = re.compile(r"(?<![\d,])\d{6,}(?![\d,])")
MY_RECORD = re.compile(
    r"\bmy (?:appointment|bill|report|result|record|prescription|admission|account|booking|payment|claim)s?\b")


def _phrases(terms: list[str]) -> re.Pattern | None:
    parts = []
    for term in terms:
        t = normalize(term)
        parts.append(re.escape(t[:-1]) + r"\w*" if t.endswith("*") else re.escape(t))
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)") if parts else None


class BypassRules:
    def __init__(self, cfg: BypassConfig):
        self._time = _phrases(cfg.time_sensitive)
        self._clinical = _phrases(cfg.clinical)
        prefixes = [re.escape(normalize(p)) for p in cfg.followup_prefixes]
        self._prefix = re.compile(r"^(?:" + "|".join(prefixes) + r")(?!\w)") if prefixes else None
        self._pronouns = frozenset(normalize(p) for p in cfg.followup_pronouns)
        self._max_words = cfg.followup_max_words

    def time_sensitive(self, text: str) -> bool:
        return bool(self._time and self._time.search(normalize(text)))

    def clinical(self, text: str) -> bool:
        return bool(self._clinical and self._clinical.search(normalize(text)))

    def followup(self, text: str, session_id: str | None) -> bool:
        if not session_id:
            return False
        t = normalize(text)
        if self._prefix and self._prefix.search(t):
            return True
        words = re.findall(r"[a-z']+", t)
        return len(words) <= self._max_words and any(w in self._pronouns for w in words)


def bypass_reason(*, query: str, namespace: str, session_id: str | None, personalized: bool,
                  bypass_cache: bool, cfg: WeirConfig, rules: BypassRules) -> str | None:
    if personalized:
        return "personalized"
    if bypass_cache:
        return "request_option"
    if cfg.kill_switch.disable_cache:
        return "kill_switch"
    if not cfg.cache.enabled:
        return "cache_disabled"
    if not cfg.cache_enabled_for(namespace):
        return "namespace_disabled"
    if rules.clinical(query):
        return "clinical"
    if rules.time_sensitive(query):
        return "time_sensitive"
    if rules.followup(query, session_id):
        return "followup"
    return None


def contains_personal_data(text: str) -> bool:
    t = normalize(text)
    return bool(EMAIL.search(t) or PHONE.search(t) or LONG_ID.search(t) or MY_RECORD.search(t))


def store_block_reason(*, generated: GenerateResult, top_score: float, query: str,
                       min_retrieval_score: float) -> str | None:
    if generated.not_found:
        return "not_found"
    if generated.finish_reason != "stop":
        return f"finish_reason:{generated.finish_reason}"
    if not generated.cited_chunk_ids:
        return "no_citations"
    if generated.invalid_citations:
        return "invalid_citations"
    if "not_found" in generated.answer.lower():  # model answered part, then gave up on the rest
        return "partial_answer"
    if top_score < min_retrieval_score:
        return "low_retrieval"
    if contains_personal_data(query) or contains_personal_data(generated.answer):
        return "personal_data"
    return None
