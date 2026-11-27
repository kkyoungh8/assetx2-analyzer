"""📈 자산제곱 — 부자코치 산하 투자 모듈 (기존 자산제곱 AI 분석기)"""

import copy

import streamlit as st

from assetx2 import analyzer
from richcoach import store

data = st.session_state.data
g = data["goal"]
inv = data["invest"]

# ── 부자코치 → 자산제곱: 목적과 보유 종목을 넘겨줌 ────────────
if g["purpose"] or g["target_amount_krw"]:
    st.session_state["coach_goal_context"] = (
        f"- 확고한 목적: {g['purpose'] or '-'}\n"
        f"- 목표 금액: ₩{int(g['target_amount_krw'] or 0):,} / 기한: {g['target_date'] or '미정'}\n"
        f"- 4단계 계획에서 투자 자산이 맡는 몫: {(data['steps']['plan'].get('fields') or {}).get('투자 자산의 몫', '-')}"
    )
else:
    st.session_state.pop("coach_goal_context", None)

if "portfolio" not in st.session_state and inv.get("portfolio"):
    st.session_state.portfolio = copy.deepcopy(inv["portfolio"])

with st.container(border=True):
    a, b = st.columns([3, 2])
    with a:
        st.markdown("**🧭 부자코치 연동**")
        if st.session_state.get("coach_goal_context"):
            st.caption("AI 종합 분석에 나의 확고한 목적이 함께 들어갑니다. 분석할 때마다 자산 스냅샷이 🏠 오늘의 목표 진척에 반영됩니다.")
        else:
            st.caption("4단계 코칭 3단계(계획)를 확정하면, 목표 금액·기한이 AI 분석에 함께 반영됩니다.")
    with b:
        other = st.number_input(
            "투자 외 자산(예금·현금 등, 원)", min_value=0, step=1_000_000,
            value=int(inv.get("other_assets_krw") or 0),
            help="목표 진척(총자산)에 더해집니다.",
        )
        if other != inv.get("other_assets_krw"):
            inv["other_assets_krw"] = int(other)
            store.save(data)

# ── 기존 자산제곱 분석기 ─────────────────────────────────────
analyzer.render()

# ── 자산제곱 → 부자코치: 보유 종목과 스냅샷 저장 ─────────────
changed = False
pf = st.session_state.get("portfolio")
if pf is not None and pf != inv.get("portfolio"):
    inv["portfolio"] = copy.deepcopy(pf)
    changed = True
snap = st.session_state.get("last_portfolio_snapshot")
if snap and (not inv["snapshots"] or inv["snapshots"][-1]["at"] != snap["at"]):
    inv["snapshots"].append(snap)
    inv["snapshots"] = inv["snapshots"][-200:]
    changed = True
if changed:
    store.save(data)
