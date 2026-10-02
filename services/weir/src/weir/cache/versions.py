from collections.abc import Awaitable, Callable

Versions = dict[str, tuple[str, str]]


class VersionCache:
    """Latest (kb_version, prompt_version) per namespace from hospital-rag /info, held in memory
    so a cache lookup never waits on the network (main spec §5.3)."""

    def __init__(self, fetch: Callable[[], Awaitable[Versions]] | None, initial: Versions | None = None):
        self._fetch = fetch
        self._versions: Versions = dict(initial or {})

    def get(self, namespace: str) -> tuple[str, str] | None:
        return self._versions.get(namespace)

    async def refresh(self) -> None:
        if self._fetch is None:
            return
        self._versions = dict(await self._fetch())  # on failure the exception propagates; old values stay
