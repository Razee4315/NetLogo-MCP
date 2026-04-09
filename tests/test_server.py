"""Tests for lazy NetLogo workspace startup and shutdown."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from netlogo_mcp.server import get_or_create_netlogo, lifespan


class FakeNetLogoLink:
    """Small fake used to verify workspace lifecycle behavior."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.kill_calls = 0

    def kill_workspace(self):
        self.kill_calls += 1


@pytest.mark.asyncio
async def test_lifespan_does_not_start_workspace_eagerly(monkeypatch):
    starts = []

    def factory(**kwargs):
        starts.append(kwargs)
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")

    async with lifespan(None) as state:
        assert state == {}
        assert starts == []


def test_get_or_create_netlogo_starts_once_and_reuses_workspace(monkeypatch):
    starts = []

    def factory(**kwargs):
        starts.append(kwargs)
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")

    state = {}
    first = get_or_create_netlogo(state)
    second = get_or_create_netlogo(state)

    assert first is second
    assert state["netlogo"] is first
    assert len(starts) == 1
    assert first.kwargs["gui"] is False


@pytest.mark.asyncio
async def test_lifespan_shuts_down_workspace_if_started(monkeypatch):
    fake_nl = FakeNetLogoLink()

    monkeypatch.setitem(
        sys.modules,
        "pynetlogo",
        SimpleNamespace(NetLogoLink=lambda **kwargs: fake_nl),
    )
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")

    async with lifespan(None) as state:
        assert get_or_create_netlogo(state) is fake_nl

    assert fake_nl.kill_calls == 1
