import pytest

from weir.cache.versions import VersionCache


def _returns(value):
    async def fetch():
        return value
    return fetch


async def test_refresh_replaces_versions():
    vc = VersionCache(fetch=_returns({"ns": ("v2", "p1")}), initial={"ns": ("v1", "p1")})
    assert vc.get("ns") == ("v1", "p1")
    await vc.refresh()
    assert vc.get("ns") == ("v2", "p1") and vc.get("other") is None


async def test_refresh_failure_keeps_old_versions():
    async def down():
        raise RuntimeError("rag down")

    vc = VersionCache(fetch=down, initial={"ns": ("v1", "p1")})
    with pytest.raises(RuntimeError):
        await vc.refresh()
    assert vc.get("ns") == ("v1", "p1")


def test_observe_updates_one_namespace_immediately():  # final-review finding I3
    vc = VersionCache(fetch=None, initial={"ns": ("v1", "p1"), "other": ("x", "p1")})
    vc.observe("ns", "v2", "p1")
    assert vc.get("ns") == ("v2", "p1") and vc.get("other") == ("x", "p1")
