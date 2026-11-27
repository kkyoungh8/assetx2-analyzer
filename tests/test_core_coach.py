"""P0·P1 테스트: DB 마이그레이션, 코칭 저장소, 프롬프트 원문 보존"""

import re
from datetime import date

import pytest

from coach import repo
from coach.prompts import STEPS, build_prompt, fields_for, original_text
from core import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "t.db")


def test_migration_idempotent(tmp_path):
    p = tmp_path / "m.db"
    db.connect(p).close()
    c = db.connect(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_original_prompts_restore_brackets():
    for s in STEPS:
        t = original_text(s)
        assert "{" not in t, s.key
        assert t.count("[직접 적기]") == len(s.ctx_labels)
        assert t.startswith("# 역할:") and "# 출력 형식:" in t
        if s.needs_prev:
            assert "[이전 결과 붙여 넣기]" in t


def test_build_prompt_fills_all_slots():
    for s in STEPS:
        p = build_prompt(s, ["값"] * len(s.ctx_labels), "이전", use_boost=True, extra_context="추가")
        assert "[직접 적기]" not in p and "[이전 결과 붙여 넣기]" not in p
        assert not re.search(r"\{(PREV|PREV_REF|C\d)\}", p)
        assert "# 추가 맥락:\n추가" in p
        assert ("# 보강" in p) == bool(s.boost)
        nb = build_prompt(s, [""] * len(s.ctx_labels), "", use_boost=False)
        assert "# 보강" not in nb and "(아직 적지 않음)" in nb


def test_boost_fields_only_when_on():
    plan = STEPS[2]
    assert "투자 자산의 몫" in fields_for(plan, True)
    assert "투자 자산의 몫" not in fields_for(plan, False)


def test_step_roundtrip_and_archive(conn):
    d = repo.get_step(conn, "diag")
    d.update(ctx=["a", "b", "c"], messages=[{"role": "user", "content": "x"}], result="결과", fields={"진짜 문제": "y"}, confirmed_at="t")
    repo.save_step(conn, d)
    got = repo.get_step(conn, "diag")
    assert got["ctx"] == ["a", "b", "c"] and got["fields"]["진짜 문제"] == "y"
    repo.archive_step(conn, got)
    assert conn.execute("SELECT COUNT(*) FROM coach_history").fetchone()[0] == 1
    assert repo.done_count(conn) == 1


def test_goal_defaults_and_save(conn):
    g = repo.get_goal(conn)
    assert g["target_amount_krw"] == 0
    g["statement"] = "문장"
    repo.save_goal(conn, g)
    assert repo.get_goal(conn)["statement"] == "문장"


def test_streak(conn):
    for d in ("2026-11-25", "2026-11-26", "2026-11-27"):
        repo.set_check(conn, d, "habit", True)
    assert repo.streak(conn, "habit", today=date(2026, 11, 27)) == 3
    assert repo.streak(conn, "habit", today=date(2026, 11, 28)) == 3   # 오늘 미완료 → 어제부터
    repo.set_check(conn, "2026-11-26", "habit", False)
    assert repo.streak(conn, "habit", today=date(2026, 11, 27)) == 1


def test_week_and_backup(conn, tmp_path):
    w = repo.get_week(conn, "2026-W48")
    w.update(done="d")
    repo.save_week(conn, w)
    repo.save_goal(conn, {**repo.get_goal(conn), "habit": "h"})
    dump = repo.export_all(conn)
    other = db.connect(tmp_path / "o.db")
    repo.import_all(other, dump)
    assert repo.get_week(other, "2026-W48")["done"] == "d"
    assert repo.get_goal(other)["habit"] == "h"
    assert repo.week_key(date(2026, 11, 27)) == "2026-W48"
