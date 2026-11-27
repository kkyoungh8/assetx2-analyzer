"""코칭 데이터 접근 (SQLite)"""

import json
from datetime import date, timedelta

from core import db

STEP_KEYS = ("diag", "offer", "plan", "persist")

DEFAULT_GOAL = {
    "statement": "",            # 아침저녁으로 읽을 문장
    "purpose": "",              # 확고한 목적 (금액·날짜·대가)
    "target_amount_krw": 0,
    "target_date": "",
    "first_action": "",
    "habit": "",
    "progress_mode": "manual",  # manual | networth (P5 순자산 연결 후)
    "manual_progress_krw": 0,
}
DEFAULT_SETTINGS = {"use_boost": True}


# ── 4단계 ────────────────────────────────────────────────────
def get_step(conn, key: str) -> dict:
    row = conn.execute("SELECT * FROM coach_steps WHERE step=?", (key,)).fetchone()
    if not row:
        return {"step": key, "ctx": [], "prev_override": "", "extra_context": "", "messages": [],
                "result": "", "fields": {}, "confirmed_at": ""}
    d = dict(row)
    for k in ("ctx", "messages", "fields"):
        d[k] = json.loads(d[k])
    return d


def save_step(conn, d: dict) -> None:
    with conn:
        conn.execute(
            """INSERT INTO coach_steps(step, ctx, prev_override, extra_context, messages, result, fields, confirmed_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(step) DO UPDATE SET ctx=excluded.ctx, prev_override=excluded.prev_override,
                 extra_context=excluded.extra_context, messages=excluded.messages, result=excluded.result,
                 fields=excluded.fields, confirmed_at=excluded.confirmed_at""",
            (d["step"], json.dumps(d["ctx"], ensure_ascii=False), d.get("prev_override", ""),
             d.get("extra_context", ""), json.dumps(d["messages"], ensure_ascii=False), d["result"],
             json.dumps(d["fields"], ensure_ascii=False), d["confirmed_at"]),
        )


def archive_step(conn, d: dict) -> None:
    """확정된 결과를 지우거나 바꾸기 전에 이력으로 남김"""
    if d.get("result"):
        with conn:
            conn.execute(
                "INSERT INTO coach_history(step, result, fields, confirmed_at) VALUES(?,?,?,?)",
                (d["step"], d["result"], json.dumps(d["fields"], ensure_ascii=False), d["confirmed_at"]),
            )


def done_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM coach_steps WHERE result != ''").fetchone()[0]


# ── 목적·설정 ────────────────────────────────────────────────
def get_goal(conn) -> dict:
    return {**DEFAULT_GOAL, **db.kv_get(conn, "goal", {})}


def save_goal(conn, goal: dict) -> None:
    db.kv_set(conn, "goal", goal)


def get_settings(conn) -> dict:
    return {**DEFAULT_SETTINGS, **db.kv_get(conn, "settings", {})}


def save_settings(conn, s: dict) -> None:
    db.kv_set(conn, "settings", s)


# ── 매일 체크 ────────────────────────────────────────────────
def get_day(conn, day: str) -> dict:
    return {r["item"]: bool(r["done"]) for r in conn.execute("SELECT item, done FROM habit_log WHERE day=?", (day,))}


def set_check(conn, day: str, item: str, done: bool) -> None:
    with conn:
        conn.execute(
            "INSERT INTO habit_log(day, item, done) VALUES(?,?,?) "
            "ON CONFLICT(day, item) DO UPDATE SET done=excluded.done",
            (day, item, int(done)),
        )


def streak(conn, item: str, today: date | None = None) -> int:
    """오늘(오늘 미완료면 어제)부터 거꾸로 연속 완료 일수"""
    done_days = {r["day"] for r in conn.execute("SELECT day FROM habit_log WHERE item=? AND done=1", (item,))}
    d = today or date.today()
    if d.isoformat() not in done_days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in done_days:
        n += 1
        d -= timedelta(days=1)
    return n


def count_in_range(conn, item: str, start: date, end: date) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM habit_log WHERE item=? AND done=1 AND day BETWEEN ? AND ?",
        (item, start.isoformat(), end.isoformat()),
    ).fetchone()[0]


# ── 주간 점검 ────────────────────────────────────────────────
def week_key(d: date | None = None) -> str:
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def week_range(d: date | None = None) -> tuple[date, date]:
    d = d or date.today()
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def get_week(conn, week: str) -> dict:
    row = conn.execute("SELECT * FROM weekly_reviews WHERE week=?", (week,)).fetchone()
    return dict(row) if row else {"week": week, "done": "", "blocked": "", "next": "", "coach": ""}


def save_week(conn, w: dict) -> None:
    with conn:
        conn.execute(
            """INSERT INTO weekly_reviews(week, done, blocked, next, coach, updated_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(week) DO UPDATE SET done=excluded.done, blocked=excluded.blocked,
                 next=excluded.next, coach=excluded.coach, updated_at=excluded.updated_at""",
            (w["week"], w["done"], w["blocked"], w["next"], w["coach"], db.now()),
        )


def past_weeks(conn, exclude: str, limit: int = 12) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM weekly_reviews WHERE week != ? ORDER BY week DESC LIMIT ?", (exclude, limit))]


# ── 백업·복원 ────────────────────────────────────────────────
BACKUP_TABLES = ("kv", "coach_steps", "coach_history", "habit_log", "weekly_reviews")


def export_all(conn) -> dict:
    return {"version": 1, "tables": {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in BACKUP_TABLES}}


def import_all(conn, data: dict) -> None:
    tables = data["tables"]
    with conn:
        for t in BACKUP_TABLES:
            conn.execute(f"DELETE FROM {t}")
            for row in tables.get(t, []):
                cols = list(row.keys())
                conn.execute(
                    f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [row[c] for c in cols],
                )
