"""Start all three CareCompass agents (each in its own process) and stream their logs.

    python scripts/run_agents.py --init-env     # create .env with fresh agent seeds (once)
    python scripts/run_agents.py                # start coordinator + hospital + insurer agents
    python scripts/run_agents.py --local        # coordinator without Agentverse mailbox (local tests)
    python scripts/run_agents.py --addresses    # print agent addresses for the README / Agentverse
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AGENTS = [("hospital", "app.agents.hospital_agent"), ("insurer", "app.agents.insurer_agent"),
          ("coordinator", "app.agents.coordinator")]


def init_env() -> None:
    env_path = ROOT / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else (ROOT / ".env.example").read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().endswith("_SEED") and not value.strip():
            line = f"{key.strip()}=carecompass-{key.strip().lower()}-{secrets.token_hex(24)}"
        lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote seeds to {env_path} (keep it private; it is git-ignored).")


def print_addresses() -> None:
    from app.agents.common import address_from_seed
    from app.config import get_settings

    s = get_settings()
    for name, seed in (("Coordinator (CareCompass AI)", s.coordinator_seed), ("Hospital Verification Agent", s.hospital_agent_seed),
                       ("Insurer Research Agent", s.insurer_agent_seed)):
        print(f"{name}: {address_from_seed(seed) if seed else '(seed not set)'}")


def _pump(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(f"[{name}] {line}")


def run(local: bool) -> None:
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    if local:
        env["COORDINATOR_CONNECTIVITY"] = "local"
    procs = []
    for name, module in AGENTS:
        proc = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        procs.append(proc)
        threading.Thread(target=_pump, args=(name, proc), daemon=True).start()
    try:
        for proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-env", action="store_true")
    ap.add_argument("--addresses", action="store_true")
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args()
    if args.init_env:
        init_env()
    elif args.addresses:
        print_addresses()
    else:
        run(args.local)
