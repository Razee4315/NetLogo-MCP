"""Tests for NetLogo workspace lazy startup, eager opt-in, and shutdown."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from netlogo_mcp.server import lifespan, start_netlogo


class FakeNetLogoLink:
    """Small fake used to verify workspace lifecycle behavior."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.kill_calls = 0

    def report(self, reporter):
        return "NetLogo 7.0.3"

    def kill_workspace(self):
        self.kill_calls += 1


def _swap_std(monkeypatch):
    """Replace sys.stdout/stderr with StringIOs.

    Must be called from INSIDE the test body — pytest's capture plugin
    re-binds the sys streams between fixture setup and the call phase,
    so a fixture-level swap would be silently clobbered.
    """
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)
    return fake_stdout, fake_stderr


@pytest.mark.asyncio
async def test_lifespan_is_lazy_by_default(monkeypatch):
    """Lifespan must NOT boot the JVM — only expose a factory for tools."""
    _swap_std(monkeypatch)
    starts = []

    def factory(**kwargs):
        starts.append(kwargs)
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_eager_start", lambda: False)

    async with lifespan(None) as state:
        assert state["netlogo"] is None
        assert callable(state["start_netlogo"])
        assert state["netlogo_version"] is None
        assert starts == []


@pytest.mark.asyncio
async def test_lifespan_eager_start_opt_in(monkeypatch):
    """NETLOGO_EAGER_START=true boots the JVM before serving."""
    _swap_std(monkeypatch)
    starts = []

    def factory(**kwargs):
        starts.append(kwargs)
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_eager_start", lambda: True)
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: False)

    async with lifespan(None) as state:
        assert len(starts) == 1
        assert state["netlogo"].kwargs["gui"] is False
        assert state["netlogo"].kwargs["thd"] is False
        assert state["netlogo_version"] == "NetLogo 7.0.3"


def test_start_netlogo_gui_mode(monkeypatch):
    """GUI mode: gui=True, thd=False (JPype handles Swing EDT)."""

    def factory(**kwargs):
        return FakeNetLogoLink(**kwargs)

    monkeypatch.setitem(sys.modules, "pynetlogo", SimpleNamespace(NetLogoLink=factory))
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: True)

    nl, version = start_netlogo()
    assert nl.kwargs["gui"] is True
    assert nl.kwargs["thd"] is False
    assert version == "NetLogo 7.0.3"


@pytest.mark.asyncio
async def test_lifespan_does_not_touch_stdout(monkeypatch):
    """FastMCP 3 binds the stdio transport to sys.stdout AFTER the lifespan
    has been entered — so the lifespan must never reassign sys.stdout."""
    fake_stdout, _ = _swap_std(monkeypatch)
    monkeypatch.setattr("netlogo_mcp.server.get_eager_start", lambda: False)

    async with lifespan(None):
        assert sys.stdout is fake_stdout


def test_hybrid_stdout_separates_protocol_from_prints(monkeypatch):
    """The transport gets .buffer (protocol); text writes go to stderr —
    pynetlogo prints Java stack traces to stdout on NetLogo errors."""
    from netlogo_mcp.server import _HybridStdout

    _, fake_stderr = _swap_std(monkeypatch)
    protocol_buffer = io.BytesIO()
    hybrid = _HybridStdout(protocol_buffer)
    monkeypatch.setattr(sys, "stdout", hybrid)

    print("java stack trace noise")

    assert protocol_buffer.getvalue() == b""  # protocol channel untouched
    assert "java stack trace noise" in fake_stderr.getvalue()
    assert hybrid.buffer is protocol_buffer  # what the transport binds to


@pytest.mark.asyncio
async def test_lifespan_shuts_down_started_workspace(monkeypatch):
    _swap_std(monkeypatch)
    fake_nl = FakeNetLogoLink()

    monkeypatch.setitem(
        sys.modules,
        "pynetlogo",
        SimpleNamespace(NetLogoLink=lambda **kwargs: fake_nl),
    )
    monkeypatch.setattr("netlogo_mcp.server.get_eager_start", lambda: True)
    monkeypatch.setattr("netlogo_mcp.server.get_netlogo_home", lambda: "C:/NetLogo")
    monkeypatch.setattr("netlogo_mcp.server.get_jvm_path", lambda: "C:/Java/jvm.dll")
    monkeypatch.setattr("netlogo_mcp.server.get_gui_mode", lambda: False)

    async with lifespan(None) as state:
        assert state["netlogo"] is fake_nl

    assert fake_nl.kill_calls == 1


@pytest.mark.asyncio
async def test_lifespan_shutdown_tolerates_never_started(monkeypatch):
    """Exiting the lifespan without any tool call must not raise."""
    _swap_std(monkeypatch)
    monkeypatch.setattr("netlogo_mcp.server.get_eager_start", lambda: False)

    async with lifespan(None) as state:
        assert state["netlogo"] is None
    # no exception == pass
