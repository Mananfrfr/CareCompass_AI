"""Runtime configuration loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _sanitize_user_agent(ua: str) -> str:
    cleaned = (ua or "").strip()
    if not cleaned or "you@example.com" in cleaned or "example.com" in cleaned:
        return "CareCompassAI/0.2 (+https://github.com/Mananfrfr/CareCompass_AI)"
    return cleaned


@dataclass(frozen=True)
class RankingWeights:
    """Product weights for suitability ranking. Not clinically validated."""

    specialty: float = 0.35
    capability: float = 0.20
    quality: float = 0.15
    network: float = 0.15
    affordability: float = 0.10
    location: float = 0.05


@dataclass(frozen=True)
class Settings:
    # "live" (default): real public data everywhere - national hospital directory, government catalogs,
    # OpenStreetMap (Overpass) and the IRDAI register. "fixture": synthetic demo data for the demo cities
    # (Jaipur, Delhi, Ajmer) and the real national directory for every other city.
    data_mode: str = field(default_factory=lambda: _env("CARECOMPASS_DATA_MODE", "live").lower())
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'carecompass.db').as_posix()}")
    )

    asi1_api_key: str = field(default_factory=lambda: _env("ASI1_API_KEY"))
    asi1_base_url: str = field(default_factory=lambda: _env("ASI1_BASE_URL", "https://api.asi1.ai/v1"))
    asi1_model: str = field(default_factory=lambda: _env("ASI1_MODEL", "asi1"))
    asi1_timeout_s: float = field(default_factory=lambda: _env_float("ASI1_TIMEOUT_S", 25.0))

    coordinator_seed: str = field(default_factory=lambda: _env("COORDINATOR_SEED"))
    hospital_agent_seed: str = field(default_factory=lambda: _env("HOSPITAL_AGENT_SEED"))
    insurer_agent_seed: str = field(default_factory=lambda: _env("INSURER_AGENT_SEED"))
    coordinator_port: int = field(default_factory=lambda: _env_int("COORDINATOR_PORT", 8000))
    hospital_agent_port: int = field(default_factory=lambda: _env_int("HOSPITAL_AGENT_PORT", 8001))
    insurer_agent_port: int = field(default_factory=lambda: _env_int("INSURER_AGENT_PORT", 8002))
    # "mailbox" connects the coordinator to Agentverse; "local" keeps everything on localhost.
    coordinator_connectivity: str = field(default_factory=lambda: _env("COORDINATOR_CONNECTIVITY", "mailbox"))
    # Extra fixed routes "agent1q...=http://127.0.0.1:8010/submit,..." (e.g. the local ACP test client).
    extra_routes: str = field(default_factory=lambda: _env("CARECOMPASS_EXTRA_ROUTES"))

    research_timeout_s: int = field(default_factory=lambda: _env_int("RESEARCH_TIMEOUT_S", 45))
    research_max_attempts: int = field(default_factory=lambda: _env_int("RESEARCH_MAX_ATTEMPTS", 2))
    action_max_attempts: int = field(default_factory=lambda: _env_int("ACTION_MAX_ATTEMPTS", 3))

    http_user_agent: str = field(
        default_factory=lambda: _sanitize_user_agent(
            _env("HTTP_USER_AGENT", "CareCompassAI/0.2 (+https://github.com/Mananfrfr/CareCompass_AI)")
        )
    )
    live_max_candidates: int = field(default_factory=lambda: _env_int("LIVE_MAX_CANDIDATES", 40))
    weights: RankingWeights = field(default_factory=RankingWeights)

    @property
    def fixture_mode(self) -> bool:
        return self.data_mode != "live"


def get_settings() -> Settings:
    return Settings()
