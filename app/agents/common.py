"""Shared agent wiring: identities, local routing and logging."""

from __future__ import annotations

import logging

from uagents.crypto import Identity
from uagents.resolver import GlobalResolver, Resolver, RulesBasedResolver

from app.config import Settings
from app.security.privacy import RedactingFilter


def address_from_seed(seed: str) -> str:
    return Identity.from_seed(seed, 0).address


class CompositeResolver(Resolver):
    """Known CareCompass agents resolve to fixed endpoints; everyone else (e.g. ASI:One users)
    resolves through the global Almanac/name service."""

    def __init__(self, rules: dict[str, str]):
        self._rules = RulesBasedResolver(rules)
        self._known = set(rules)
        self._global = GlobalResolver()

    async def resolve(self, destination: str) -> tuple[str | None, list[str]]:
        if destination in self._known:
            return await self._rules.resolve(destination)
        return await self._global.resolve(destination)


def require_seed(value: str, name: str) -> str:
    if not value or len(value) < 16:
        raise SystemExit(f"{name} is missing or too short. Run `python scripts/run_agents.py --init-env` "
                         "to generate seeds into .env (never commit .env).")
    return value


def local_routes(settings: Settings) -> dict[str, str]:
    """Endpoints of the three CareCompass agents when they run on the same host."""
    host = "http://127.0.0.1"
    routes = {}
    for seed, port in ((settings.coordinator_seed, settings.coordinator_port),
                       (settings.hospital_agent_seed, settings.hospital_agent_port),
                       (settings.insurer_agent_seed, settings.insurer_agent_port)):
        if seed:
            routes[address_from_seed(seed)] = f"{host}:{port}/submit"
    for pair in filter(None, (p.strip() for p in settings.extra_routes.split(","))):
        address, _, url = pair.partition("=")
        if address.startswith("agent1") and url.startswith(("http://127.0.0.1", "http://localhost")):
            routes[address] = url
    return routes


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
