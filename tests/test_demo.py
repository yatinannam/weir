"""The one-command demo launcher (Phase 6A addendum §4). No Docker, no network: every side effect is faked."""
from types import SimpleNamespace

import pytest

import demo

EXAMPLE = (demo.ROOT / ".env.example").read_text(encoding="utf-8")
GOOD = [{"cache_status": "miss", "route": "large"},
        {"cache_status": "hit", "route": "none", "similarity": 0.984},
        {"cache_status": "miss", "guard_refused": True, "route": "large", "similarity": 0.964},
        {"cache_status": "miss", "route": "small"},
        {"cache_status": "miss", "route": "large"}]


class FakeRun:
    def __init__(self, fail=None):                     # fail: {word in the command: (returncode, stderr)}
        self.calls, self.fail = [], fail or {}

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        for word, (code, err) in self.fail.items():
            if word in cmd:
                return SimpleNamespace(returncode=code, stdout="", stderr=err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeHttp:
    def __init__(self, namespaces=("weir-general/en/public",), metas=None):
        self.calls, self.namespaces, self.metas = [], namespaces, list(metas or [])

    def __call__(self, method, url, headers=None, body=None, timeout=10):
        self.calls.append((method, url, headers or {}, body))
        if url.endswith("/healthz"):
            return 200, {"status": "ok"}
        if url.endswith("/info"):
            return 200, {"namespaces": {n: {} for n in self.namespaces}}
        if method == "DELETE":
            return 200, {"deleted": 3}
        if url.endswith("/v1/query"):
            return 200, {"answer": "x", "sources": [], "meta": self.metas.pop(0)}
        raise AssertionError(url)


def project(tmp_path, env_text=None):
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    return tmp_path


def run_main(root, argv, run=None, http=None, opener_result=True):
    lines, opened = [], []
    code = demo.main(argv, run=run or FakeRun(), http=http or FakeHttp(),
                     opener=lambda url: opened.append(url) or opener_result, sleep=lambda s: None,
                     root=root, out=lines.append, environ={"PATH": "x"})
    return code, lines, opened


def test_prepare_env_creates_from_the_example_and_fills_blank_keys(tmp_path):
    root = project(tmp_path)
    filled = demo.prepare_env(root / ".env", root / ".env.example", token=iter(["t1", "t2", "t3", "t4"]).__next__)
    env = demo.read_env(root / ".env")
    assert filled == list(demo.FILL)
    assert [env[k] for k in demo.FILL] == ["t1", "t2", "t3", "t4"] and env["GROQ_API_KEY"] == ""
    assert (root / ".env").read_text(encoding="utf-8").count("#") == EXAMPLE.count("#")   # comments kept


def test_prepare_env_never_overwrites_and_adds_missing_names(tmp_path):  # Review Focus 2
    root = project(tmp_path, "GROQ_API_KEY=gsk_real\nWEIR_KEY_PUBLIC=mine\nWEIR_KEY_STAFF=\n")
    filled = demo.prepare_env(root / ".env", root / ".env.example", token=iter(["a", "b", "c"]).__next__)
    env = demo.read_env(root / ".env")
    assert filled == ["WEIR_KEY_STAFF", "WEIR_KEY_ADMIN", "GRAFANA_ADMIN_PASSWORD"]
    assert (env["GROQ_API_KEY"], env["WEIR_KEY_PUBLIC"], env["WEIR_KEY_STAFF"]) == ("gsk_real", "mine", "a")
    assert demo.prepare_env(root / ".env", root / ".env.example") == []          # a second run changes nothing


def test_demo_url_carries_the_key_only_in_the_fragment():
    base, fragment = demo.demo_url("k-123", "stub").split("#")
    assert base == "http://127.0.0.1:8000/demo" and fragment == "key=k-123&mode=stub"


@pytest.mark.parametrize("meta, path", [
    ({"cache_status": "hit", "route": "none"}, "hit"),
    ({"cache_status": "miss", "guard_refused": True, "route": "large"}, "guard_refused"),
    ({"cache_status": "bypass", "route": "large"}, "bypass"),
    ({"cache_status": "miss", "escalated": True, "route": "large"}, "escalated"),
    ({"cache_status": "miss", "route": "small"}, "small"),
])
def test_observed_path(meta, path):
    assert demo.observed_path(meta) == path


def test_a_cached_question_never_passes_as_a_miss():  # Review Focus 5
    assert not demo.step_passed("miss", {"cache_status": "hit", "route": "none"})
    assert not demo.step_passed("miss", {"cache_status": "miss", "guard_refused": True, "route": "large"})
    assert demo.step_passed("miss", {"cache_status": "miss", "route": "small"})


def test_main_starts_pins_the_mode_purges_and_opens_without_printing_keys(tmp_path):  # Review Focus 2
    root = project(tmp_path)
    run, http = FakeRun(), FakeHttp()
    code, lines, opened = run_main(root, [], run=run, http=http)
    env = demo.read_env(root / ".env")
    compose = [(cmd, kw) for cmd, kw in run.calls if cmd[:2] == ["docker", "compose"]]
    assert code == 0 and compose and all(kw["env"]["LLM_MODE"] == "stub" for _, kw in compose)
    [delete] = [c for c in http.calls if c[0] == "DELETE"]
    assert delete[2]["X-API-Key"] == env["WEIR_KEY_ADMIN"] and "namespace=weir-general%2Fen%2Fpublic" in delete[1]
    [url] = opened
    assert url.split("#")[0] == "http://127.0.0.1:8000/demo" and env["WEIR_KEY_PUBLIC"] in url.split("#")[1]
    printed = "\n".join(lines)
    assert not any(env[k] in printed for k in demo.FILL)
    assert not any("hospital_rag.ingest" in cmd for cmd, _ in run.calls)     # the KB is already loaded


def test_first_run_loads_the_kb_then_waits_for_weir_to_see_it(tmp_path):
    run, slept = FakeRun(), []
    code = demo.main([], run=run, http=FakeHttp(namespaces=()), opener=lambda url: True, sleep=slept.append,
                     root=project(tmp_path), out=lambda line: None, environ={})
    [ingest] = [kw for cmd, kw in run.calls if "hospital_rag.ingest" in cmd]
    assert code == 0 and ingest["env"]["LLM_MODE"] == "stub" and demo.KB_VERSION_WAIT_S in slept


def test_a_groq_key_selects_real_models_unless_stub_is_forced(tmp_path):
    root = project(tmp_path, EXAMPLE.replace("GROQ_API_KEY=", "GROQ_API_KEY=gsk_test"))
    for argv, mode in (([], "groq"), (["--stub"], "stub")):
        run = FakeRun()
        run_main(root, argv, run=run)
        assert all(kw["env"]["LLM_MODE"] == mode for cmd, kw in run.calls if cmd[:2] == ["docker", "compose"])


def test_docker_not_running_says_so_and_stops(tmp_path):  # Review Focus 1
    run = FakeRun(fail={"info": (1, "error during connect")})
    code, lines, opened = run_main(project(tmp_path), [], run=run)
    assert code == 1 and "Start Docker Desktop" in lines[0] and len(run.calls) == 1 and not opened


def test_compose_failure_shows_its_error_and_stops(tmp_path):  # Review Focus 1
    run = FakeRun(fail={"up": (1, "Error: port 8000 is already allocated")})
    code, lines, opened = run_main(project(tmp_path), [], run=run)
    assert code == 1 and "port 8000 is already allocated" in "\n".join(lines) and not opened


def test_no_browser_prints_the_address_without_the_key(tmp_path):
    root = project(tmp_path)
    code, lines, opened = run_main(root, [], opener_result=False)
    key = demo.read_env(root / ".env")["WEIR_KEY_PUBLIC"]
    assert code == 0 and any("http://127.0.0.1:8000/demo" in line and "paste" in line for line in lines)
    assert not any(key in line for line in lines)
    code, lines, opened = run_main(root, ["--no-browser"])
    assert code == 0 and not opened


def test_check_runs_the_five_steps_and_fails_on_a_wrong_path(tmp_path):
    root = project(tmp_path)
    code, lines, opened = run_main(root, ["--check"], http=FakeHttp(metas=GOOD))
    assert code == 0 and sum(line.startswith("step") and ": pass" in line for line in lines) == 5 and not opened
    bad = GOOD[:3] + [{"cache_status": "miss", "route": "large"}] + GOOD[4:]
    code, lines, _ = run_main(root, ["--check"], http=FakeHttp(metas=bad))
    assert code == 1 and any(line.startswith("step 4: FAIL") for line in lines)


def test_dashboard_starts_monitoring_and_points_to_grafana(tmp_path):
    run = FakeRun()
    code, lines, _ = run_main(project(tmp_path), ["--dashboard"], run=run)
    [up] = [cmd for cmd, _ in run.calls if "up" in cmd]
    assert code == 0 and up[2:4] == ["--profile", "monitoring"] and "grafana" in up
    assert any("http://127.0.0.1:3000" in line for line in lines)


def test_stop_stops_every_service(tmp_path):
    run = FakeRun()
    code, _, _ = run_main(project(tmp_path), ["--stop"], run=run)
    assert code == 0 and run.calls[-1][0] == ["docker", "compose", "--profile", "monitoring", "stop"]


# --- Phase 6A final review fixes ----------------------------------------------------------------------

def test_a_fallback_answer_never_passes_as_the_routed_tier():  # I2: the Groq limit must not earn a tick
    meta = {"cache_status": "miss", "route": "large", "fallback": True}
    assert demo.observed_path(meta) == "fallback" and not demo.step_passed("large", meta)


def test_every_command_decodes_its_output_as_utf8(tmp_path):  # I1
    run = FakeRun()
    demo.main([], run=run, http=FakeHttp(namespaces=()), opener=lambda url: True, sleep=lambda s: None,
              root=project(tmp_path), out=lambda line: None, environ={})
    assert run.calls and all(kw.get("encoding") == "utf-8" and kw.get("errors") == "replace" for _, kw in run.calls)


def test_utf8_progress_bars_do_not_break_output_capture():  # I1: tqdm's partial blocks crashed cp1252 decoding
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-c", "import sys; sys.stderr.buffer.write(bytes([0xe2, 0x96, 0x8f]))"],
                          **demo.RUN_TEXT)
    assert proc.stderr == "▏"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_docker_stopping_mid_start_is_reported_quickly(tmp_path):  # I3, Review Focus 1
    class DownHttp(FakeHttp):
        def __call__(self, method, url, headers=None, body=None, timeout=10):
            return (0, None) if url.endswith("/healthz") else super().__call__(method, url, headers, body, timeout)

    infos = iter([0, 1])                                       # docker info: up at the start, then gone

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=next(infos) if cmd == ["docker", "info"] else 0, stdout="", stderr="")

    clock, lines = FakeClock(), []
    code = demo.main([], run=run, http=DownHttp(), opener=lambda url: True, sleep=clock.sleep, clock=clock,
                     root=project(tmp_path), out=lines.append, environ={})
    assert code == 1 and any("Docker stopped" in line for line in lines) and clock.now <= 60


def test_docker_not_responding_says_so(tmp_path):  # I3
    import subprocess

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    code, lines, opened = run_main(project(tmp_path), [], run=run)
    assert code == 1 and "isn't responding" in lines[0] and not opened
