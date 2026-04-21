"""Shared test fixtures — mock NetLogoLink so tests don't need JVM/NetLogo."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest


class MockNetLogoLink:
    """Fake pynetlogo.NetLogoLink for unit testing."""

    def __init__(self):
        self._model_loaded = False
        self.model_path: str | None = None
        self._globals = {}
        self.commands: list[str] = []
        self._ticks = 0

    def load_model(self, path: str):
        self._model_loaded = True
        self.model_path = path
        self._ticks = 0

    def command(self, cmd: str):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        self.commands.append(cmd)
        if cmd == "setup":
            self._ticks = 0
        if cmd == "go":
            self._ticks += 1
        if cmd.startswith("set "):
            parts = cmd.split(None, 2)
            if len(parts) == 3:
                self._globals[parts[1]] = parts[2]

    def report(self, reporter: str):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        mapping = {
            "ticks": self._ticks,
            "count turtles": 100,
            "count sheep": 100 + self._ticks,
            "count wolves": 50 + self._ticks,
            "count patches": 1089,
            "count links": 0,
            "min-pxcor": -16,
            "max-pxcor": 16,
            "min-pycor": -16,
            "max-pycor": 16,
        }
        if reporter in mapping:
            return mapping[reporter]
        if reporter in self._globals:
            return self._globals[reporter]
        return 42

    def patch_report(self, attribute: str):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        return pd.DataFrame([[1, 2], [3, 4]])

    def kill_workspace(self):
        pass


@pytest.fixture
def mock_nl():
    """Return a MockNetLogoLink instance."""
    return MockNetLogoLink()


@pytest.fixture
def mock_context(mock_nl):
    """Return a mock MCP Context with netlogo in lifespan context.

    No _ready event needed — wait_for_netlogo returns immediately
    when 'netlogo' key is already present.
    """
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"netlogo": mock_nl}
    ctx.report_progress = AsyncMock()
    return ctx
