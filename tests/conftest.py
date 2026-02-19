"""Shared test fixtures — mock NetLogoLink so tests don't need JVM/NetLogo."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


class MockNetLogoLink:
    """Fake pynetlogo.NetLogoLink for unit testing."""

    def __init__(self):
        self._model_loaded = False
        self._globals = {}

    def load_model(self, path: str):
        self._model_loaded = True

    def command(self, cmd: str):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        if cmd.startswith("set "):
            parts = cmd.split(None, 2)
            if len(parts) == 3:
                self._globals[parts[1]] = parts[2]

    def report(self, reporter: str):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        mapping = {
            "ticks": 0,
            "count turtles": 100,
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

    def repeat_report(self, reporters, ticks, go="go", include_t0=True):
        if not self._model_loaded:
            raise RuntimeError("No model loaded")
        data = {r: list(range(ticks)) for r in reporters}
        return pd.DataFrame(data)

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
    """Return a mock MCP Context with netlogo in lifespan context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"netlogo": mock_nl}
    return ctx
