"""Tests for NetLogo workspace eager startup and shutdown."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from netlogo_mcp.server import lifespan


class FakeNetLogoLink:
    """Small fake used to verify workspace lifecycle behavior."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.kill_calls = 0

    def kill_workspace(self):
        self.kill_calls += 1


@pytest.mark.asyncio
async def test_lifespan_starts_netlogo_and_yields_workspace(monkeypatch):
    """Lifespan should start NetLogo eagerly and yield it in state."""
    starts = []

    def factory(**kwargs):
        starts.append(kwargs)
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: False)

    async with lifespan(None) as state:
        assert "netlogo" in state
        assert len(starts) == 1
        assert state["netlogo"].kwargs["gui"] is False
        assert state["netlogo"].kwargs["thd"] is False


@pytest.mark.asyncio
async def test_lifespan_gui_mode(monkeypatch):
    """GUI mode: gui=True, thd=False (JPype handles Swing EDT)."""

    def factory(**kwargs):
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: True)

    async with lifespan(None) as state:
        assert state["netlogo"].kwargs["gui"] is True
        assert state["netlogo"].kwargs["thd"] is False


@pytest.mark.asyncio
async def test_lifespan_redirects_startup_noise_to_stderr(monkeypatch):
    """Startup chatter from JVM init must not leak onto MCP stdout."""

    def factory(**kwargs):
        print("JVM startup noise")
        return FakeNetLogoLink(**kwargs)

    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: False)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    async with lifespan(None):
        pass

    assert fake_stdout.getvalue() == ""
    assert "JVM startup noise" in fake_stderr.getvalue()


@pytest.mark.asyncio
async def test_lifespan_shuts_down_workspace(monkeypatch):
    fake_nl = FakeNetLogoLink()

    monkeypatch.setitem(
        sys.modules,
        "pynetlogo",
        SimpleNamespace(NetLogoLink=lambda **kwargs: fake_nl),
    )
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")

    async with lifespan(None) as state:
        assert state["netlogo"] is fake_nl

    assert fake_nl.kill_calls == 1
