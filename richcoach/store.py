"""개인 데이터 저장소 — data/richcoach.json (git 에 올라가지 않음)"""

import copy
import json
import os
from datetime import date, datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DATA_PATH = os.path.join(DATA_DIR, "richcoach.json")

EMPTY_STEP = {"ctx": [], "messages": [], "result": "", "fields": {}, "confirmed_at": ""}

DEFAULT = {
    "version": 1,
    "use_boost": True,
    "steps": {k: copy.deepcopy(EMPTY_STEP) for k in ("diag", "offer", "plan", "persist")},
    "goal": {               # 확고한 목적 (3단계 결과에서 채우고, 직접 고칠 수 있음)
        "statement": "",    # 아침저녁으로 읽을 문장
        "target_amount_krw": 0,
        "target_date": "",
        "purpose": "",
        "first_action": "",
        "habit": "",
        "progress_mode": "assets",      # "assets"(자산제곱 총자산) | "manual"(직접 입력)
        "manual_progress_krw": 0,
    },
    "habit_log": {},        # {"2026-11-27": {"habit": true, "read_am": true, "read_pm": false}}
    "weekly": [],           # [{"week": "2026-W48", "done": "...", "blocked": "...", "next": "...", "coach": "..."}]
    "invest": {
        "portfolio": None,  # 자산제곱 보유 종목 목록
        "snapshots": [],    # 분석 때마다 남는 자산 스냅샷
        "other_assets_krw": 0,  # 투자 외 자산(예금·현금 등) 직접 입력
    },
}


def _merge(base: dict, loaded: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in loaded.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return _merge(DEFAULT, json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT)


def save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)


def import_json(raw: bytes) -> dict:
    return _merge(DEFAULT, json.loads(raw.decode("utf-8")))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_key() -> str:
    return date.today().isoformat()


def week_key(d: date | None = None) -> str:
    d = d or date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def streak(habit_log: dict, field: str = "habit") -> int:
    """오늘(또는 어제)부터 거꾸로 연속 달성 일수"""
    d = date.today()
    if not habit_log.get(d.isoformat(), {}).get(field):
        d -= timedelta(days=1)
    n = 0
    while habit_log.get(d.isoformat(), {}).get(field):
        n += 1
        d -= timedelta(days=1)
    return n


def latest_total_assets_krw(data: dict) -> tuple[float, str]:
    """최근 스냅샷 기준 총자산(원) 추정. (금액, 설명)"""
    snaps = data["invest"].get("snapshots") or []
    other = float(data["invest"].get("other_assets_krw") or 0)
    if not snaps:
        return other, "투자 스냅샷 없음 — 투자 외 자산만 반영"
    s = snaps[-1]
    stock_krw = s["stock_value_usd"] * s["usd_krw"]
    stock_pct = max(1, 100 - s.get("cash_pct", 0))
    portfolio_krw = stock_krw / (stock_pct / 100)   # 현금 비중 슬라이더로 역산한 계좌 총액
    return portfolio_krw + other, f"{s['at']} 분석 기준 · 계좌 추정 ₩{portfolio_krw:,.0f} + 투자 외 ₩{other:,.0f}"
