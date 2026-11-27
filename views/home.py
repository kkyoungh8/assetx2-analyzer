"""🏠 오늘: 확고한 목적, 아침·저녁 읽기, 매일 습관, 목표 진척"""

from datetime import date

import streamlit as st

from richcoach import store

data = st.session_state.data
g = data["goal"]
today = store.today_key()
log = data["habit_log"].setdefault(today, {})

st.title("🏠 오늘")
st.caption(date.today().strftime("%Y년 %m월 %d일") + " · 힐: 확고한 목적을 글로 적고, 아침저녁으로 소리 내어 읽으세요.")

if not g["statement"] and not data["steps"]["plan"]["result"]:
    st.info("아직 확고한 목적이 없습니다. 🧭 4단계 코칭에서 1단계(진단)부터 시작하세요. 3단계를 확정하면 이 화면이 채워집니다.")
    done = [s for s in ("diag", "offer", "plan", "persist") if data["steps"][s]["result"]]
    st.progress(len(done) / 4, text=f"코칭 진행 {len(done)}/4")
    st.page_link("views/coach.py", label="4단계 코칭으로 가기", icon="🧭")
    st.stop()

# ── 확고한 목적 문장 ───────────────────────────────────────
st.markdown("#### 📜 나의 확고한 목적")
st.markdown(
    f"<div style='font-size:1.35rem;line-height:1.7;padding:1.2rem 1.4rem;border-radius:12px;"
    f"border-left:5px solid #e0457b;background:rgba(224,69,123,0.08)'>{g['statement'] or g['purpose'] or '(문장이 비어 있습니다 — 아래에서 적어 주세요)'}</div>",
    unsafe_allow_html=True,
)
c1, c2, c3 = st.columns(3)


def tick(field: str, label: str, col):
    with col:
        v = st.checkbox(label, value=bool(log.get(field)), key=f"tick_{field}")
        if v != bool(log.get(field)):
            log[field] = v
            store.save(data)


tick("read_am", "☀️ 아침에 소리 내어 읽음", c1)
tick("read_pm", "🌙 저녁에 소리 내어 읽음", c2)
with c3:
    st.metric("읽기 연속", f"{min(store.streak(data['habit_log'], 'read_am'), store.streak(data['habit_log'], 'read_pm'))}일")

# ── 매일 습관 & 이번 주 행동 ─────────────────────────────────
st.markdown("---")
l, r = st.columns(2)
with l:
    st.markdown("#### 🔁 매일의 습관")
    st.write(g["habit"] or "4단계(지속)를 확정하면 여기에 표시됩니다.")
    if g["habit"]:
        tick("habit", "오늘 습관 완료", st.container())
        st.caption(f"연속 {store.streak(data['habit_log'], 'habit')}일 · 최악의 날에도 할 수 있을 만큼 작게.")
with r:
    st.markdown("#### 👟 이번 주 첫 행동")
    st.write(g["first_action"] or "-")
    st.page_link("views/weekly.py", label="주간 점검하러 가기", icon="🗓️")

# ── 목표 진척 ─────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 🎯 목표 진척")
target = int(g.get("target_amount_krw") or 0)
mode = g.get("progress_mode", "assets")
if mode == "assets":
    current, basis = store.latest_total_assets_krw(data)
else:
    current, basis = float(g.get("manual_progress_krw") or 0), "직접 입력한 누적 금액"

m1, m2, m3 = st.columns(3)
m1.metric("목표 금액", f"₩{target:,.0f}" if target else "미정")
m2.metric("현재", f"₩{current:,.0f}")
if g.get("target_date"):
    try:
        left = (date.fromisoformat(g["target_date"]) - date.today()).days
        m3.metric("기한까지", f"D-{left}" if left >= 0 else f"{-left}일 지남", help=g["target_date"])
    except ValueError:
        m3.metric("기한", g["target_date"])
else:
    m3.metric("기한", "미정")
if target:
    st.progress(min(current / target, 1.0), text=f"{current / target * 100:.1f}% · 기준: {basis}")
else:
    st.caption(f"기준: {basis}")

with st.expander("목표와 진척 기준 고치기"):
    with st.form("goal_edit"):
        statement = st.text_area("아침저녁으로 읽을 문장", value=g["statement"], height=90)
        purpose = st.text_area("확고한 목적 (금액·날짜·대가)", value=g["purpose"], height=70)
        a, b = st.columns(2)
        amt = a.number_input("목표 금액(원)", min_value=0, value=target, step=1_000_000)
        try:
            d0 = date.fromisoformat(g["target_date"]) if g.get("target_date") else None
        except ValueError:
            d0 = None
        dt = b.date_input("기한", value=d0)
        first_action = st.text_input("이번 주 첫 행동", value=g["first_action"])
        habit = st.text_input("매일의 습관", value=g["habit"])
        pm = st.radio(
            "진척 기준", ["assets", "manual"], index=0 if mode == "assets" else 1, horizontal=True,
            format_func=lambda x: "자산제곱 총자산 (투자 계좌 + 투자 외 자산)" if x == "assets" else "직접 입력 (예: 제안으로 번 누적 금액)",
            help="목표가 '자산 규모'면 총자산, '벌어들일 돈'이면 직접 입력이 맞습니다.",
        )
        manual = st.number_input("직접 입력 누적 금액(원)", min_value=0, value=int(g.get("manual_progress_krw") or 0), step=100_000)
        if st.form_submit_button("저장", type="primary"):
            g.update({
                "statement": statement, "purpose": purpose, "target_amount_krw": int(amt),
                "target_date": dt.isoformat() if dt else "", "first_action": first_action,
                "habit": habit, "progress_mode": pm, "manual_progress_krw": int(manual),
            })
            store.save(data)
            st.rerun()
