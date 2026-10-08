# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""One-command Weir demo (Phase 6A addendum §4). Standard library only; never prints a key.

    uv run demo.py               start (the stub model if GROQ_API_KEY is blank) and open the demo page
    uv run demo.py --stub        the stub model even when a Groq key is set (no quota used)
    uv run demo.py --keep-cache  don't empty the demo cache first
    uv run demo.py --dashboard   also start Prometheus and Grafana
    uv run demo.py --check       run the five guided steps and check each path (no browser)
    uv run demo.py --no-browser  start everything but don't open a browser
    uv run demo.py --stop        stop everything
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEIR = "http://127.0.0.1:8000"
RAG = "http://127.0.0.1:8001"
GRAFANA = "http://127.0.0.1:3000"
NAMESPACE = "weir-general/en/public"
QUESTIONS = ROOT / "services" / "weir" / "src" / "weir" / "demo" / "questions.json"
FILL = ("WEIR_KEY_PUBLIC", "WEIR_KEY_STAFF", "WEIR_KEY_ADMIN", "GRAFANA_ADMIN_PASSWORD")
SERVICES = ["postgres", "migrate", "hospital-rag", "weir"]
HEALTH_TIMEOUT_S = 600
KB_VERSION_WAIT_S = 35      # Weir re-reads KB versions every 30 s (configs/weir.yaml: rag.info_refresh_seconds)
CACHE_WRITE_WAIT_S = 2      # cache writes are asynchronous: let step 1's answer land before step 2
DOCKER_INFO_TIMEOUT_S = 30  # a wedged Docker Desktop must not hang the launcher
DOCKER_RECHECK_S = 30       # while Weir isn't answering, check Docker itself this often
# Child output is UTF-8 (Docker build logs, tqdm bars); Windows would otherwise decode it as cp1252 and crash.
RUN_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def prepare_env(env_path: Path, example_path: Path,
                token: Callable[[], str] = lambda: secrets.token_urlsafe(24)) -> list[str]:
    """Create .env from the example if missing and fill blank or missing keys. Returns the names filled."""
    if not env_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    filled, seen, lines = [], set(), []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and not line.lstrip().startswith("#"):
            seen.add(name)
            if name in FILL and not value.strip():
                line = f"{name}={token()}"
                filled.append(name)
        lines.append(line)
    for name in FILL:
        if name not in seen:
            lines.append(f"{name}={token()}")
            filled.append(name)
    if filled:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return filled


def choose_mode(env: dict[str, str], force_stub: bool) -> str:
    return "stub" if force_stub or not env.get("GROQ_API_KEY", "").strip() else "groq"


def compose_command(*args: str, monitoring: bool = False) -> list[str]:
    return ["docker", "compose", *(["--profile", "monitoring"] if monitoring else []), *args]


def compose_env(base: dict[str, str], mode: str) -> dict[str, str]:
    return {**base, "LLM_MODE": mode}    # D55: pinned on every compose call, so .env's LLM_MODE can't override it


def demo_url(key: str, mode: str) -> str:
    return f"{WEIR}/demo#" + urllib.parse.urlencode({"key": key, "mode": mode})   # a fragment never reaches a server


def observed_path(meta: dict) -> str:
    if meta.get("cache_status") == "hit":
        return "hit"
    if meta.get("guard_refused"):
        return "guard_refused"
    if meta.get("cache_status") == "bypass":
        return "bypass"
    if meta.get("fallback"):                 # route is the router's decision; the other tier answered
        return "fallback"
    if meta.get("escalated"):
        return "escalated"
    return str(meta.get("route"))


def step_passed(expect: str, meta: dict) -> bool:
    if expect == "miss":
        return meta.get("cache_status") == "miss" and not meta.get("guard_refused")
    return observed_path(meta) == expect


def http_json(method: str, url: str, headers: dict | None = None, body: dict | None = None,
              timeout: float = 10) -> tuple[int, object]:
    """(status, parsed JSON); status 0 when the server can't be reached."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def tail(text: str, lines: int = 15) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def docker_state(run) -> str:
    """'ok', 'down', 'missing' or 'hung' for the Docker engine."""
    try:
        return "ok" if run(["docker", "info"], timeout=DOCKER_INFO_TIMEOUT_S, **RUN_TEXT).returncode == 0 else "down"
    except FileNotFoundError:
        return "missing"
    except subprocess.TimeoutExpired:
        return "hung"


def wait_healthy(http, sleep, out, docker_ok: Callable[[], bool], clock: Callable[[], float],
                 timeout_s: int = HEALTH_TIMEOUT_S, every_s: int = 3) -> str:
    """'ok' once Weir is healthy, 'docker' if Docker stopped meanwhile, 'timeout' after timeout_s."""
    start = clock()
    unreachable_since = None
    next_note = start + 30
    while clock() - start < timeout_s:
        status, body = http("GET", f"{WEIR}/healthz")
        if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
            return "ok"
        if status == 0:                      # nothing answering: is Docker itself still up?
            unreachable_since = unreachable_since if unreachable_since is not None else clock()
            if clock() - unreachable_since >= DOCKER_RECHECK_S:
                if not docker_ok():
                    return "docker"
                unreachable_since = clock()
        else:
            unreachable_since = None
        sleep(every_s)
        if clock() >= next_note:
            out(f"  still starting... ({int(clock() - start)} s)")
            next_note += 30
    return "timeout"


def run_check(http, sleep, public_key: str, out) -> int:
    steps = json.loads(QUESTIONS.read_text(encoding="utf-8"))["steps"]
    failures = 0
    for step in steps:
        status, body = http("POST", f"{WEIR}/v1/query", headers={"X-API-Key": public_key},
                            body={"query": step["question"], "namespace": NAMESPACE}, timeout=60)
        if status != 200 or not isinstance(body, dict):
            out(f"step {step['n']}: FAIL  HTTP {status}")
            failures += 1
            continue
        meta = body["meta"]
        ok = step_passed(step["expect"], meta)
        failures += not ok
        similarity = meta.get("similarity")
        out(f"step {step['n']}: {'pass' if ok else 'FAIL'}  expected {step['expect']}, got {observed_path(meta)}"
            + (f" (similarity {similarity:.3f})" if similarity is not None else ""))
        sleep(CACHE_WRITE_WAIT_S)
    return 1 if failures else 0


def parse_args(argv):
    p = argparse.ArgumentParser(prog="demo.py", description="Start Weir and open the demo page.")
    p.add_argument("--stub", action="store_true", help="use the stub model even if GROQ_API_KEY is set")
    p.add_argument("--keep-cache", action="store_true", help="don't empty the demo cache first")
    p.add_argument("--dashboard", action="store_true", help="also start Prometheus and Grafana")
    p.add_argument("--check", action="store_true", help="run the five guided steps and check each path")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser")
    p.add_argument("--stop", action="store_true", help="stop everything")
    return p.parse_args(argv)


DOCKER_PROBLEM = {"missing": "Docker isn't installed. Install Docker Desktop, then run this again.",
                  "down": "Docker isn't running. Start Docker Desktop, then run this again.",
                  "hung": "Docker isn't responding. Restart Docker Desktop, then run this again."}


def main(argv=None, *, run=subprocess.run, http=http_json, opener=webbrowser.open, sleep=time.sleep,
         clock: Callable[[], float] = time.monotonic, root: Path = ROOT, out: Callable[[str], None] = print,
         environ: dict | None = None) -> int:
    args = parse_args(argv)
    base = dict(os.environ if environ is None else environ)
    state = docker_state(run)
    if state != "ok":
        out(DOCKER_PROBLEM[state])
        return 1
    if args.stop:
        run(compose_command("stop", monitoring=True), cwd=root, env=compose_env(base, "stub"), **RUN_TEXT)
        out("Stopped. Start again with: uv run demo.py")
        return 0

    filled = prepare_env(root / ".env", root / ".env.example")
    if filled:
        out(f"Created in .env: {', '.join(filled)} (values not shown).")
    env = read_env(root / ".env")
    mode = choose_mode(env, args.stub)
    out("Mode: " + ("the stub model (no Groq key needed)" if mode == "stub" else "real Groq models"))
    compose = {"cwd": root, "env": compose_env(base, mode), **RUN_TEXT}

    services = SERVICES + (["prometheus", "grafana"] if args.dashboard else [])
    out("Starting the stack (the first run builds the images and takes a few minutes)...")
    proc = run(compose_command("up", "-d", "--build", *services, monitoring=args.dashboard), **compose)
    if proc.returncode != 0:
        out("docker compose failed:\n" + tail(proc.stderr))
        return 1
    health = wait_healthy(http, sleep, out, docker_ok=lambda: docker_state(run) == "ok", clock=clock)
    if health == "docker":
        out("Docker stopped while Weir was starting. Start Docker Desktop, then run this again.")
        return 1
    if health != "ok":
        out(f"Weir didn't become healthy within {HEALTH_TIMEOUT_S // 60} minutes. Check: docker compose logs weir")
        return 1

    status, info = http("GET", f"{RAG}/info")
    if status == 200 and isinstance(info, dict) and not info.get("namespaces"):
        out("Loading the knowledge base (first run only)...")
        ingest = run(compose_command("exec", "-T", "hospital-rag", "python", "-m", "hospital_rag.ingest",
                                     "--kb", "/app/kb"), **compose)
        if ingest.returncode != 0:
            out("Loading the knowledge base failed:\n" + tail(ingest.stderr))
            return 1
        out(f"Waiting {KB_VERSION_WAIT_S} s for Weir to pick up the new knowledge base...")
        sleep(KB_VERSION_WAIT_S)

    if not args.keep_cache:
        status, _ = http("DELETE", f"{WEIR}/v1/cache?" + urllib.parse.urlencode({"namespace": NAMESPACE}),
                         headers={"X-API-Key": env["WEIR_KEY_ADMIN"]})
        if status != 200:
            out(f"Couldn't empty the demo cache (HTTP {status}); the guided story may start from a cache hit.")
    if args.check:
        return run_check(http, sleep, env["WEIR_KEY_PUBLIC"], out)
    if args.dashboard:
        out(f"Dashboard: {GRAFANA} (user admin; the password is GRAFANA_ADMIN_PASSWORD in .env)")

    if not args.no_browser and opener(demo_url(env["WEIR_KEY_PUBLIC"], mode)):
        out(f"Opened the demo page: {WEIR}/demo")
    else:
        out(f"Open {WEIR}/demo in a browser and paste WEIR_KEY_PUBLIC from .env when the page asks.")
    out("Stop everything later with: uv run demo.py --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
