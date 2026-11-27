"""🗓️ 주간 점검: 계획이 막혀도 포기 대신 다시 계획하기"""

import streamlit as st

from richcoach import llm, store

data = st.session_state.data
g = data["goal"]
api_key = st.session_state.get("api_key", "")
wk = store.week_key()

st.title("🗓️ 주간 점검")
st.caption("힐: 대부분의 사람은 첫 계획이 실패했을 때 새 계획을 세우지 못하고 포기합니다. 막힌 주에는 포기 대신 계획을 고칩니다.")

entry = next((w for w in data["weekly"] if w["week"] == wk), None)
if entry is None:
    entry = {"week": wk, "done": "", "blocked": "", "next": "", "coach": ""}

persist_fields = data["steps"]["persist"].get("fields") or {}
if persist_fields.get("주간 점검"):
    with st.expander("🧭 4단계에서 정한 주간 점검 의식", expanded=True):
        st.write(persist_fields["주간 점검"])

with st.form("weekly"):
    st.markdown(f"**{wk}** · 이번 주 첫 행동: {g['first_action'] or '-'}")
    done = st.text_area("이번 주에 실제로 한 것", value=entry["done"], height=90)
    blocked = st.text_area("막힌 것 / 하지 못한 이유", value=entry["blocked"], height=90)
    nxt = st.text_area("다음 주 첫 행동 (비워 두면 코치가 제안)", value=entry["next"], height=70)
    c1, c2 = st.columns(2)
    save_only = c1.form_submit_button("저장")
    ask = c2.form_submit_button("🧭 코치에게 점검받기", type="primary")

if save_only or ask:
    entry.update({"done": done, "blocked": blocked, "next": nxt})
    if entry not in data["weekly"]:
        data["weekly"].append(entry)
    store.save(data)

if ask:
    if not api_key:
        st.error("사이드바에 Claude API 키를 넣어 주세요.")
        st.stop()
    habit_days = sum(1 for k, v in data["habit_log"].items() if store.week_key(__import__("datetime").date.fromisoformat(k)) == wk and v.get("habit"))
    total, basis = store.latest_total_assets_krw(data)
    plan_result = data["steps"]["plan"]["result"] or "(3단계 미확정)"
    prompt = f"""# 역할:
당신은 나폴레온 힐의 관점으로 훈련받은 부의 코치입니다. 힐은 계획이 실패하는 것은 일시적인 패배일 뿐이며, 그때 필요한 것은 포기가 아니라 새 계획이라고 봤습니다.

# 과제:
이번 주 기록을 보고, 계획을 계속 붙들도록 짧게 점검해 주세요.

# 규칙:
• 확고한 목적(금액·기한)은 바꾸지 말고, 막힌 부분은 계획을 고쳐서 대응하세요
• 실제로 한 행동과 결과만 보세요. 의욕이나 다짐은 점수에 넣지 마세요
• 다음 주 첫 행동은 하나만, 구체적으로
• 투자 종목의 매수·매도는 다루지 마세요

# 맥락:
• 확고한 목적: {g['purpose'] or '-'}
• 아침저녁 문장: {g['statement'] or '-'}
• 3단계 계획:
{plan_result}
• 이번 주 첫 행동: {g['first_action'] or '-'}
• 매일의 습관: {g['habit'] or '-'} (이번 주 완료 {habit_days}일)
• 총자산 추정: ₩{total:,.0f} ({basis}) / 목표 ₩{int(g.get('target_amount_krw') or 0):,}
• 이번 주에 한 것: {done or '-'}
• 막힌 것: {blocked or '-'}
• 내가 생각한 다음 주 첫 행동: {nxt or '(비어 있음)'}

# 출력 형식:
• 이번 주 판정: [계획대로 / 일부 진행 / 멈춤 중 하나와 한 줄 이유]
• 막힌 원인: [행동 기준으로 한 줄]
• 고친 계획: [바꾼 부분만]
• 다음 주 첫 행동: [하나, 구체적으로]"""
    with st.chat_message("assistant", avatar="🧭"):
        reply = st.write_stream(llm.stream_reply(api_key, [{"role": "user", "content": prompt}], effort="medium"))
    if isinstance(reply, str) and not reply.startswith("❌"):
        entry["coach"] = reply
        store.save(data)
elif entry.get("coach"):
    with st.chat_message("assistant", avatar="🧭"):
        st.markdown(entry["coach"])

if entry.get("coach"):
    if st.button("👟 코치가 제안한 '다음 주 첫 행동'을 홈 화면에 반영"):
        try:
            got = llm.extract_fields(api_key, entry["coach"], ["다음 주 첫 행동"])
        except Exception:
            got = {}
        if got.get("다음 주 첫 행동"):
            g["first_action"] = got["다음 주 첫 행동"]
            store.save(data)
            st.toast("반영했습니다")
        else:
            st.warning("항목을 찾지 못했습니다. 🏠 오늘 화면에서 직접 고쳐 주세요.")

past = [w for w in reversed(data["weekly"]) if w["week"] != wk]
if past:
    st.markdown("---")
    st.markdown("#### 지난 점검")
    for w in past[:12]:
        with st.expander(w["week"]):
            st.markdown(f"**한 것** {w['done'] or '-'}\n\n**막힌 것** {w['blocked'] or '-'}\n\n**다음 행동** {w['next'] or '-'}")
            if w.get("coach"):
                st.markdown("---\n" + w["coach"])
