"""🏠 오늘: 확고한 목적, 아침·저녁 읽기, 매일 습관, 목표 진척"""

import html
from datetime import date

import streamlit as st

from coach import repo
from core import ui

conn = ui.conn()
g = repo.get_goal(conn)
today = date.today().isoformat()
checks = repo.get_day(conn, today)

st.title("🏠 오늘")
st.caption(date.today().strftime("%Y년 %m월 %d일") + " · 힐: 확고한 목적을 글로 적고, 아침저녁으로 소리 내어 읽으세요.")

if not (g["statement"] or g["purpose"]):
    n = repo.done_count(conn)
    st.info("아직 확고한 목적이 없습니다. 🧭 4단계 코칭에서 1단계(진단)부터 시작하세요. 3단계를 확정하면 이 화면이 채워집니다.")
    st.progress(n / 4, text=f"코칭 진행 {n}/4")
    st.page_link("views/coach.py", label="4단계 코칭으로 가기", icon="🧭")
    st.stop()

st.markdown("#### 📜 나의 확고한 목적")
st.markdown(
    "<div style='font-size:1.35rem;line-height:1.7;padding:1.2rem 1.4rem;border-radius:12px;"
    "border-left:5px solid #e0457b;background:rgba(224,69,123,0.08)'>"
    f"{html.escape(g['statement'] or g['purpose'])}</div>",
    unsafe_allow_html=True,
)


def check(item: str, label: str):
    v = st.checkbox(label, value=checks.get(item, False), key=f"chk_{item}")
    if v != checks.get(item, False):
        repo.set_check(conn, today, item, v)


c1, c2, c3 = st.columns(3)
with c1:
    check("read_am", "☀️ 아침에 소리 내어 읽음")
with c2:
    check("read_pm", "🌙 저녁에 소리 내어 읽음")
c3.metric("아침 읽기 연속", f"{repo.streak(conn, 'read_am')}일")

st.divider()
l, r = st.columns(2)
with l:
    st.markdown("#### 🔁 매일의 습관")
    st.write(g["habit"] or "4단계(지속)를 확정하면 여기에 표시됩니다.")
    if g["habit"]:
        check("habit", "오늘 습관 완료")
        st.caption(f"연속 {repo.streak(conn, 'habit')}일 · 최악의 날에도 할 수 있을 만큼 작게.")
with r:
    st.markdown("#### 👟 이번 주 첫 행동")
    st.write(g["first_action"] or "-")
    st.page_link("views/weekly.py", label="주간 점검하러 가기", icon="🗓️")

st.divider()
st.markdown("#### 🎯 목표 진척")
target = int(g["target_amount_krw"] or 0)
current = float(g["manual_progress_krw"] or 0)
m1, m2, m3 = st.columns(3)
m1.metric("목표 금액", f"₩{target:,.0f}" if target else "미정")
m2.metric("현재 (직접 입력)", f"₩{current:,.0f}")
try:
    left = (date.fromisoformat(g["target_date"]) - date.today()).days
    m3.metric("기한까지", f"D-{left}" if left >= 0 else f"{-left}일 지남", help=g["target_date"])
except ValueError:
    m3.metric("기한", "미정")
if target:
    st.progress(min(current / target, 1.0), text=f"{current / target * 100:.1f}%")
st.caption("순자산(토스증권·미래에셋·현금) 자동 연결은 P5에서 붙습니다. 그 전까지는 아래에서 직접 입력하세요.")

with st.expander("목표 고치기"), st.form("goal_edit"):
    statement = st.text_area("아침저녁으로 읽을 문장", value=g["statement"], height=90)
    purpose = st.text_area("확고한 목적 (금액·날짜·대가)", value=g["purpose"], height=70)
    a, b = st.columns(2)
    amt = a.number_input("목표 금액(원)", min_value=0, value=target, step=1_000_000)
    try:
        d0 = date.fromisoformat(g["target_date"])
    except ValueError:
        d0 = None
    dt = b.date_input("기한", value=d0)
    first_action = st.text_input("이번 주 첫 행동", value=g["first_action"])
    habit = st.text_input("매일의 습관", value=g["habit"])
    manual = st.number_input("현재 달성 금액(원)", min_value=0, value=int(current), step=100_000)
    if st.form_submit_button("저장", type="primary"):
        g.update(statement=statement, purpose=purpose, target_amount_krw=int(amt),
                 target_date=dt.isoformat() if dt else "", first_action=first_action,
                 habit=habit, manual_progress_krw=int(manual))
        repo.save_goal(conn, g)
        st.rerun()
