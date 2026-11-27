"""SQLite 저장소 (~/.richcoach/richcoach.db)

테이블은 MIGRATIONS 에 순서대로 쌓는다. 이미 적용된 번호는 PRAGMA user_version 으로 건너뛴다.
나중 단계(P2~)의 테이블은 그 단계에서 MIGRATIONS 끝에 추가한다.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core import config

MIGRATIONS = [
    # 1 — P0 기반 + P1 코칭
    """
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,              -- JSON
        updated_at TEXT NOT NULL
    );
    CREATE TABLE coach_steps (
        step TEXT PRIMARY KEY,            -- diag | offer | plan | persist
        ctx TEXT NOT NULL DEFAULT '[]',   -- JSON list: [직접 적기] 칸 값
        prev_override TEXT NOT NULL DEFAULT '',
        extra_context TEXT NOT NULL DEFAULT '',
        messages TEXT NOT NULL DEFAULT '[]',
        result TEXT NOT NULL DEFAULT '',
        fields TEXT NOT NULL DEFAULT '{}',
        confirmed_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE coach_history (          -- 확정했던 결과를 덮어쓰기 전에 남김
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        step TEXT NOT NULL,
        result TEXT NOT NULL,
        fields TEXT NOT NULL,
        confirmed_at TEXT NOT NULL
    );
    CREATE TABLE habit_log (
        day TEXT NOT NULL,                -- YYYY-MM-DD
        item TEXT NOT NULL,               -- habit | read_am | read_pm
        done INTEGER NOT NULL,
        PRIMARY KEY (day, item)
    );
    CREATE TABLE weekly_reviews (
        week TEXT PRIMARY KEY,            -- 2026-W48
        done TEXT NOT NULL DEFAULT '',
        blocked TEXT NOT NULL DEFAULT '',
        next TEXT NOT NULL DEFAULT '',
        coach TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    -- 모든 수집기(텔레그램·카드 문자·PDF)가 원문을 그대로 넣는 곳 (P3~)
    CREATE TABLE raw_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,             -- telegram:<채널> | card_sms | report_pdf ...
        source_id TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        received_at TEXT NOT NULL,
        payload TEXT NOT NULL,            -- JSON
        processed_at TEXT,
        UNIQUE (source, source_id)
    );
    """,
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[ver:], start=ver + 1):
        with conn:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {i}")


@contextmanager
def tx(conn: sqlite3.Connection):
    with conn:
        yield conn


# ── kv 도우미 ────────────────────────────────────────────────
def kv_get(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(conn, key: str, value) -> None:
    with conn:
        conn.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now()),
        )
