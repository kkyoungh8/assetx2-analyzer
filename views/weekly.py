"""🗓️ 주간 점검: 계획이 막혀도 포기 대신 다시 계획하기"""

import streamlit as st

from ai import client as ai
from coach import repo
from coach.prompts import COACH_SYSTEM, weekly_prompt
from core import ui

conn = ui.conn()
g = repo.get_goal(conn)
wk = repo.week_key()
w = repo.get_week(conn, wk)

st.title("🗓️ 주간 점검")
st.caption("힐: 대부분의 사람은 첫 계획이 실패했을 때 새 계획을 세우지 못하고 포기합니다. 막힌 주에는 포기 대신 계획을 고칩니다.")

ritual = repo.get_step(conn, "persist")["fields"].get("주간 점검")
if ritual:
    with st.expander("🧭 4단계에서 정한 주간 점검 의식", expanded=True):
        st.write(ritual)

with st.form("weekly"):
    st.markdown(f"**{wk}** · 이번 주 첫 행동: {g['first_action'] or '-'}")
    done = st.text_area("이번 주에 실제로 한 것", value=w["done"], height=90)
    blocked = st.text_area("막힌 것 / 하지 못한 이유", value=w["blocked"], height=90)
    nxt = st.text_area("다음 주 첫 행동 (비워 두면 코치가 제안)", value=w["next"], height=70)
    c1, c2 = st.columns(2)
    save_only = c1.form_submit_button("저장")
    ask = c2.form_submit_button("🧭 코치에게 점검받기", type="primary")

if save_only or ask:
    w.update(done=done, blocked=blocked, next=nxt)
    repo.save_week(conn, w)

if ask:
    key = ui.require_api_key()
    start, end = repo.week_range()
    prompt = weekly_prompt(
        goal=g,
        plan_result=repo.get_step(conn, "plan")["result"],
        habit_days=repo.count_in_range(conn, "habit", start, end),
        done=done, blocked=blocked, nxt=nxt,
    )
    with st.chat_message("assistant", avatar="🧭"):
        reply = st.write_stream(ai.stream_reply(key, [{"role": "user", "content": prompt}], COACH_SYSTEM, effort="medium"))
    if isinstance(reply, str) and not reply.startswith("❌"):
        w["coach"] = reply
        repo.save_week(conn, w)
elif w["coach"]:
    with st.chat_message("assistant", avatar="🧭"):
        st.markdown(w["coach"])

if w["coach"] and st.button("👟 코치가 제안한 '다음 주 첫 행동'을 오늘 화면에 반영"):
    try:
        got = ai.extract_fields(ui.require_api_key(), w["coach"], ["다음 주 첫 행동"])
    except Exception:
        got = {}
    if got.get("다음 주 첫 행동"):
        g["first_action"] = got["다음 주 첫 행동"]
        repo.save_goal(conn, g)
        st.toast("반영했습니다")
    else:
        st.warning("항목을 찾지 못했습니다. 🏠 오늘 화면에서 직접 고쳐 주세요.")

past = repo.past_weeks(conn, exclude=wk)
if past:
    st.divider()
    st.markdown("#### 지난 점검")
    for p in past:
        with st.expander(p["week"]):
            st.markdown(f"**한 것** {p['done'] or '-'}\n\n**막힌 것** {p['blocked'] or '-'}\n\n**다음 행동** {p['next'] or '-'}")
            if p["coach"]:
                st.markdown("---\n" + p["coach"])
