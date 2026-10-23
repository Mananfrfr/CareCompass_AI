from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.database.session import make_session_factory  # noqa: E402
from app.research.hospital_sources import FixtureHospitalSource  # noqa: E402
from app.research.insurer_sources import FixtureInsurerSource  # noqa: E402
from app.research.service import InProcessResearchClient  # noqa: E402
from app.workflow.orchestrator import CareCompassWorkflow  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), data_mode="fixture", database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                   asi1_api_key="", action_max_attempts=3)


@pytest.fixture
def repo(settings) -> Repository:
    return Repository(make_session_factory(settings.database_url))


@pytest.fixture
def research() -> InProcessResearchClient:
    return InProcessResearchClient(FixtureHospitalSource(), FixtureInsurerSource())


@pytest.fixture
def workflow(repo, settings) -> CareCompassWorkflow:
    wf = CareCompassWorkflow(repo, settings, asi1=None)
    wf.executor.backoff_s = 0.0
    return wf
