"""Tests for the CoMSES Net integration — mocked HTTP, no network, no JVM."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from netlogo_mcp import comses

FIXTURES = Path(__file__).parent / "fixtures" / "comses"


# ── Fixture loaders ───────────────────────────────────────────────────────────


def _fx(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_client(handler) -> comses.ComsesClient:
    """Build a ComsesClient whose underlying httpx uses the given handler."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        transport=transport, base_url=comses.BASE_URL, follow_redirects=True
    )
    return comses.ComsesClient(client=http)


# ── API client: search + metadata ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_builds_correct_url_and_returns_json():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/codebases/"
        assert request.url.params.get("format") == "json"
        assert request.url.params.get("query") == "predator-prey"
        assert request.url.params.get("page") == "2"
        return httpx.Response(200, json=_fx("search_result.json"))

    async with _make_client(handler) as client:
        data = await client.search(query="predator-prey", page=2)

    assert data["count"] == 54
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_search_without_query_omits_query_param():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query" not in dict(request.url.params)
        return httpx.Response(200, json=_fx("search_result.json"))

    async with _make_client(handler) as client:
        await client.search()


@pytest.mark.asyncio
async def test_get_codebase_returns_title_and_releases():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/aaaaaaaa-1111-4aaa-8aaa-111111111111/")
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        data = await client.get_codebase("aaaaaaaa-1111-4aaa-8aaa-111111111111")
    assert data["title"] == "Wolf Sheep Predation"
    assert len(data["releases"]) == 2


@pytest.mark.asyncio
async def test_get_release_returns_citation_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "releases/1.2.0" in request.url.path
        return httpx.Response(200, json=_fx("release_detail.json"))

    async with _make_client(handler) as client:
        rel = await client.get_release("aaaaaaaa-1111-4aaa-8aaa-111111111111", "1.2.0")
    assert "Wolf Sheep Predation" in rel["citationText"]


@pytest.mark.asyncio
async def test_resolve_latest_uses_latest_version_number():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        assert await client.resolve_latest("xxx", "latest") == "1.2.0"


@pytest.mark.asyncio
async def test_resolve_latest_passthrough_for_concrete_version():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        assert await client.resolve_latest("xxx", "1.0.0") == "1.0.0"
    assert calls == 0, "Concrete version must not trigger a codebase fetch"


# ── Retry policy ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"count": 0, "results": []})

    async with _make_client(handler) as client:
        await client.search()
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_does_not_retry_on_4xx():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(404)

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()
    assert state["calls"] == 1


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503)

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()
    assert state["calls"] == comses.MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_retries_on_network_error(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"count": 0, "results": []})

    async with _make_client(handler) as client:
        await client.search()
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_non_json_content_type_is_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>interstitial</html>", headers={"Content-Type": "text/html"}
        )

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()


# ── MCP tools: search_comses + get_comses_model ───────────────────────────────


@pytest.mark.asyncio
async def test_search_comses_tool_returns_compact_json(monkeypatch):
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fx("search_result.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.search_comses(ctx, query="predator-prey", page=1)
    data = json.loads(raw)

    assert data["count"] == 54
    assert data["page"] == 1
    assert len(data["results"]) == 2
    first = data["results"][0]
    assert first["identifier"] == "aaaaaaaa-1111-4aaa-8aaa-111111111111"
    assert first["language"] == "NetLogo"
    assert first["isPeerReviewed"] is True
    assert first["downloads"] == 482
    assert "Jane Author" in first["authors"]


@pytest.mark.asyncio
async def test_search_comses_tool_rejects_invalid_page():
    from fastmcp.exceptions import ToolError

    from netlogo_mcp import tools

    ctx = MagicMock()
    with pytest.raises(ToolError):
        await tools.search_comses(ctx, query="x", page=0)


@pytest.mark.asyncio
async def test_get_comses_model_tool_includes_citation(monkeypatch):
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/releases/1.2.0" in path:
            return httpx.Response(200, json=_fx("release_detail.json"))
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.get_comses_model(
        ctx, identifier="aaaaaaaa-1111-4aaa-8aaa-111111111111"
    )
    data = json.loads(raw)

    assert data["title"] == "Wolf Sheep Predation"
    assert data["citation_text"].startswith("Author, J.")
    assert data["peerReviewed"] is True
    # Both releases should come through, with languages and licenses.
    assert len(data["releases"]) == 2
    latest = [r for r in data["releases"] if r["versionNumber"] == "1.2.0"][0]
    assert latest["language"] == "NetLogo"
    assert latest["license"] == "MIT"
    assert latest["downloadable"] is True


@pytest.mark.asyncio
async def test_get_comses_model_tool_survives_release_fetch_failure(monkeypatch):
    """If the /releases/<v>/ call fails, the codebase response still comes back."""
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        if "/releases/" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.get_comses_model(
        ctx, identifier="aaaaaaaa-1111-4aaa-8aaa-111111111111"
    )
    data = json.loads(raw)
    # No citation (it lives on the release), but the codebase detail still surfaces.
    assert data["title"] == "Wolf Sheep Predation"
    assert data["citation_text"] == ""


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fast_sleep(_seconds: float) -> None:
    """Replace asyncio.sleep so retry tests don't actually wait."""
    return None


def _patch_client_factory(monkeypatch, handler) -> None:
    """Patch ComsesClient() in tools.py to use our MockTransport."""
    from netlogo_mcp import tools

    original = comses.ComsesClient

    def factory(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(
            transport=transport,
            base_url=comses.BASE_URL,
            follow_redirects=True,
        )
        return original(client=http)

    monkeypatch.setattr(tools._comses, "ComsesClient", factory)
