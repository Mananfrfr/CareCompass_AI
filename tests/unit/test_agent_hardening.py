"""Outbound uAgents deliveries must be time-bounded so one stalled POST cannot freeze the agent."""
import pytest

aiohttp = pytest.importorskip("aiohttp")
communication = pytest.importorskip("uagents.communication")


def test_outbound_sessions_get_a_timeout():
    from app.agents.common import harden_outbound_sends
    harden_outbound_sends(7)
    session = communication.aiohttp.ClientSession
    assert communication.aiohttp.ClientConnectorError is aiohttp.ClientConnectorError
    import asyncio

    async def make():
        s = session()
        try:
            return s.timeout.total
        finally:
            await s.close()
    assert asyncio.run(make()) == 7
