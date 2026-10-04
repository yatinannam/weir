"""Router rules v1 (main spec §7.2, Phase 3 addendum §3.2). Cut-offs live in configs/weir.yaml, tuned offline."""
from ..config import Tier, WeirConfig
from .features import Features

# Reasons where the router itself chose the tier. Only these may fall back or escalate;
# forced and disabled routes keep to one tier and one call (plan: "one behaviour rule").
ROUTER_DECISIONS = frozenset({"clinical", "weak_retrieval", "simple", "default_large"})


def route(f: Features, cfg: WeirConfig) -> tuple[Tier, str]:
    r = cfg.router
    if cfg.kill_switch.force_large:
        return "large", "kill_switch"
    if f.forced_tier:
        return f.forced_tier, "force_model"
    if not r.enabled:
        return r.default_tier, "router_disabled"
    if f.is_clinical:
        return "large", "clinical"
    if f.top_score < r.low_confidence:
        return "large", "weak_retrieval"
    if (f.tokens <= r.short_query_tokens and not f.has_reasoning_words
            and f.num_questions == 1 and f.top_score >= r.high_confidence):
        return "small", "simple"
    return "large", "default_large"
