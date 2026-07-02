"""Event store — SQLite persistence for campaign runs.

One database per campaign at ``market_data/runs/<campaign>.sqlite``.
Verbatims (LLM free text) live ONLY here — never inside NetLogo.

Tables
------
runs          one row per (stimulus variant x replicate) simulation run
decisions     one row per resolved exposure event
tick_metrics  funnel counts per tick per run
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Any

import pandas as pd

from .config import get_runs_dir

if TYPE_CHECKING:
    from .schemas import Decision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    campaign     TEXT NOT NULL,
    audience     TEXT NOT NULL,
    stimulus_id  TEXT NOT NULL,
    replicate    INTEGER NOT NULL,
    seed         INTEGER NOT NULL,
    engine       TEXT NOT NULL,
    fidelity     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    started      REAL NOT NULL,
    finished     REAL,
    ticks        INTEGER DEFAULT 0,
    llm_calls    INTEGER DEFAULT 0,
    cache_hits   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    tick              INTEGER NOT NULL,
    agent_index       INTEGER NOT NULL,
    persona_id        TEXT NOT NULL,
    stimulus_id       TEXT NOT NULL,
    exposure_type     TEXT NOT NULL,
    stage1_action     TEXT NOT NULL,
    action            TEXT,
    state             TEXT NOT NULL,
    sentiment         REAL NOT NULL,
    trust_delta       REAL DEFAULT 0,
    attention_seconds INTEGER DEFAULT 0,
    will_share        INTEGER NOT NULL DEFAULT 0,
    cached            INTEGER NOT NULL DEFAULT 0,
    reason            TEXT DEFAULT '',
    objections        TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_decisions_run ON decisions(run_id);
CREATE TABLE IF NOT EXISTS tick_metrics (
    run_id    TEXT NOT NULL,
    tick      INTEGER NOT NULL,
    unaware   INTEGER, exposed INTEGER, engaged INTEGER, clicked INTEGER,
    converted INTEGER, ignored INTEGER, annoyed INTEGER,
    wom_exposures INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, tick)
);
"""


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()) or "campaign"


class EventStore:
    """All persistence for one campaign's runs."""

    def __init__(self, campaign: str, path: str | None = None) -> None:
        self.campaign = campaign
        self.path = path or str(get_runs_dir() / f"{_slug(campaign)}.sqlite")
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── runs ─────────────────────────────────────────────────────────────────

    def create_run(
        self,
        audience: str,
        stimulus_id: str,
        replicate: int,
        seed: int,
        engine: str,
        fidelity: str,
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO runs (run_id, campaign, audience, stimulus_id, replicate,"
            " seed, engine, fidelity, started) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                self.campaign,
                audience,
                stimulus_id,
                replicate,
                seed,
                engine,
                fidelity,
                time.time(),
            ),
        )
        self._conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        ticks: int,
        llm_calls: int,
        cache_hits: int,
        status: str = "done",
    ) -> None:
        self._conn.execute(
            "UPDATE runs SET status=?, finished=?, ticks=?, llm_calls=?,"
            " cache_hits=? WHERE run_id=?",
            (status, time.time(), ticks, llm_calls, cache_hits, run_id),
        )
        self._conn.commit()

    # ── decisions & metrics ──────────────────────────────────────────────────

    def add_decisions(self, run_id: str, decisions: list[Decision]) -> None:
        rows = [
            (
                run_id,
                d.tick,
                d.agent_index,
                d.persona_id,
                d.stimulus_id,
                d.exposure_type,
                d.stage1.action,
                d.reaction.action if d.reaction else None,
                d.state,
                d.sentiment,
                d.reaction.trust_delta if d.reaction else 0.0,
                d.reaction.attention_seconds if d.reaction else 0,
                int(d.will_share),
                int(d.cached),
                d.verbatim,
                json.dumps(d.reaction.objections if d.reaction else []),
            )
            for d in decisions
        ]
        self._conn.executemany(
            "INSERT INTO decisions (run_id, tick, agent_index, persona_id,"
            " stimulus_id, exposure_type, stage1_action, action, state,"
            " sentiment, trust_delta, attention_seconds, will_share, cached,"
            " reason, objections) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()

    def add_tick_metrics(
        self, run_id: str, tick: int, counts: dict[str, int], wom_exposures: int = 0
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO tick_metrics (run_id, tick, unaware, exposed,"
            " engaged, clicked, converted, ignored, annoyed, wom_exposures)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                tick,
                counts.get("unaware", 0),
                counts.get("exposed", 0),
                counts.get("engaged", 0),
                counts.get("clicked", 0),
                counts.get("converted", 0),
                counts.get("ignored", 0),
                counts.get("annoyed", 0),
                wom_exposures,
            ),
        )
        self._conn.commit()

    # ── queries ──────────────────────────────────────────────────────────────

    def runs_df(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM runs ORDER BY started", self._conn)

    def decisions_df(self, run_ids: list[str] | None = None) -> pd.DataFrame:
        if run_ids:
            marks = ",".join("?" * len(run_ids))
            return pd.read_sql_query(
                f"SELECT * FROM decisions WHERE run_id IN ({marks})",
                self._conn,
                params=run_ids,
            )
        return pd.read_sql_query("SELECT * FROM decisions", self._conn)

    def tick_metrics_df(self, run_ids: list[str] | None = None) -> pd.DataFrame:
        if run_ids:
            marks = ",".join("?" * len(run_ids))
            return pd.read_sql_query(
                f"SELECT * FROM tick_metrics WHERE run_id IN ({marks})"
                " ORDER BY run_id, tick",
                self._conn,
                params=run_ids,
            )
        return pd.read_sql_query(
            "SELECT * FROM tick_metrics ORDER BY run_id, tick", self._conn
        )

    def completed_run_ids(self) -> dict[str, list[str]]:
        """stimulus_id -> [run_id, ...] for finished runs."""
        df = self.runs_df()
        done = df[df["status"] == "done"]
        out: dict[str, list[str]] = {}
        for _, row in done.iterrows():
            out.setdefault(str(row["stimulus_id"]), []).append(str(row["run_id"]))
        return out

    # ── export ───────────────────────────────────────────────────────────────

    def export(self, directory: str) -> list[str]:
        """Dump all tables to parquet (falls back to CSV without pyarrow)."""
        from pathlib import Path

        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for name, df in (
            ("runs", self.runs_df()),
            ("decisions", self.decisions_df()),
            ("tick_metrics", self.tick_metrics_df()),
        ):
            base = out_dir / f"{_slug(self.campaign)}_{name}"
            try:
                path = f"{base}.parquet"
                df.to_parquet(path)
            except (ImportError, ValueError, OSError):
                path = f"{base}.csv"
                df.to_csv(path, index=False)
            written.append(path)
        return written


def store_summary(store: EventStore) -> dict[str, Any]:
    runs = store.runs_df()
    return {
        "campaign": store.campaign,
        "runs": len(runs),
        "done": int((runs["status"] == "done").sum()) if len(runs) else 0,
        "total_llm_calls": int(runs["llm_calls"].sum()) if len(runs) else 0,
        "db": store.path,
    }
