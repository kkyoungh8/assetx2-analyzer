"""🧭 4단계 코칭: 진단 → 제안 → 계획 → 지속"""

import re

import streamlit as st

from ai import client as ai
from coach import repo
from coach.prompts import COACH_SYSTEM, STEPS, STEP_BY_KEY, build_prompt, fields_for, original_text
from core import db, ui

conn = ui.conn()
settings = repo.get_settings(conn)

st.title("🧭 4단계 코칭")
st.caption("나폴레온 힐 『생각하라 그리고 부자가 되어라』 · 앞 단계에서 확정한 결과가 다음 단계의 [이전 결과]로 자동으로 들어갑니다.")

steps = {s.key: repo.get_step(conn, s.key) for s in STEPS}


def icon(key: str) -> str:
    return "✅" if steps[key]["result"] else ("💬" if steps[key]["messages"] else "⬜")


labels = {f"{icon(s.key)} {s.no}. {s.file.split('-')[1].removesuffix('.md')}": s.key for s in STEPS}
if "coach_step" not in st.session_state:
    st.session_state.coach_step = next((s.key for s in STEPS if not steps[s.key]["result"]), "persist")
choice = st.segmented_control(
    "단계", list(labels), label_visibility="collapsed",
    default=next(l for l, k in labels.items() if k == st.session_state.coach_step),
)
if choice:
    st.session_state.coach_step = labels[choice]

step = STEP_BY_KEY[st.session_state.coach_step]
sd = steps[step.key]
idx = [s.key for s in STEPS].index(step.key)
prev_step = STEPS[idx - 1] if step.needs_prev else None

use_boost = st.toggle(
    "원전 보강 지시 사용", value=settings["use_boost"],
    help="원문 프롬프트 끝에 『생각하라 그리고 부자가 되어라』 원전 내용과 투자 연동을 위한 '보강' 지시를 덧붙입니다. 끄면 원문만 보냅니다.",
)
if use_boost != settings["use_boost"]:
    repo.save_settings(conn, {**settings, "use_boost": use_boost})

st.subheader(f"프롬프트 {step.no} / 4 — {step.title}")
with st.expander("📄 원문 프롬프트 보기"):
    st.code(original_text(step), language="markdown", wrap_lines=True)
    if step.boost:
        st.markdown("**보강 지시 (원문에 없음 · 토글로 켜고 끔)**")
        st.code(step.boost, language="markdown", wrap_lines=True)

# ── 1) 맥락 입력 ───────────────────────────────────────────
if prev_step and not steps[prev_step.key]["result"]:
    st.warning(f"{prev_step.no}단계 결과가 아직 확정되지 않았습니다. 먼저 {prev_step.no}단계를 마치거나, 아래 칸에 직접 붙여 넣으세요.")

ctx_vals = list(sd["ctx"]) + [""] * (len(step.ctx_labels) - len(sd["ctx"]))
locked = bool(sd["messages"])
with st.form(f"ctx_{step.key}"):
    st.markdown("**맥락 채우기**" + (" · 코칭이 시작되어 잠겨 있습니다. 바꾸려면 아래 '처음부터 다시'를 누르세요." if locked else ""))
    prev_text = ""
    if prev_step:
        prev_text = st.text_area(
            f"이전 결과 ({prev_step.no}단계에서 자동으로 가져옴)",
            value=sd["prev_override"] or steps[prev_step.key]["result"], height=180, disabled=locked,
        )
    new_vals = [st.text_area(lbl, value=ctx_vals[i], height=90, disabled=locked, key=f"c_{step.key}_{i}")
                for i, lbl in enumerate(step.ctx_labels)]
    extra = st.text_area(
        "추가 맥락 (선택)", value=sd["extra_context"], height=70, disabled=locked,
        help="원문 칸에 없는 정보를 덧붙일 때. 3단계에서는 '자산제곱 투자 현황: …'처럼 적으면 보강 지시가 투자 몫을 따로 계산합니다. "
             "(P2 이후 자동으로 채워집니다)",
    )
    started = st.form_submit_button("▶️ 코칭 시작", type="primary", disabled=locked)

if started:
    ui.require_api_key()
    repo.archive_step(conn, sd)
    base_prev = steps[prev_step.key]["result"] if prev_step else ""
    sd.update({
        "ctx": new_vals, "extra_context": extra,
        "prev_override": prev_text if prev_text != base_prev else "",
        "messages": [{"role": "user", "content": build_prompt(step, new_vals, prev_text, use_boost, extra)}],
        "result": "", "fields": {}, "confirmed_at": "",
    })
    repo.save_step(conn, sd)

# ── 2) 대화 ────────────────────────────────────────────────
msgs = sd["messages"]
if msgs:
    st.divider()
    with st.expander("📤 보낸 프롬프트"):
        st.code(msgs[0]["content"], language="markdown", wrap_lines=True)
    for m in msgs[1:]:
        with st.chat_message(m["role"], avatar="🧭" if m["role"] == "assistant" else None):
            st.markdown(m["content"])

    if msgs[-1]["role"] == "user":
        key = ui.require_api_key()
        with st.chat_message("assistant", avatar="🧭"):
            reply = st.write_stream(ai.stream_reply(key, msgs, COACH_SYSTEM))
        if isinstance(reply, str) and reply and not reply.startswith("❌"):
            msgs.append({"role": "assistant", "content": reply})
        else:
            failed = msgs.pop()   # 실패한 요청이 화면을 다시 그릴 때마다 반복되지 않게
            if msgs:
                st.info("보내려던 답장입니다. 복사해 다시 보내 주세요.")
                st.code(failed["content"], language=None, wrap_lines=True)
            else:
                st.info("맥락 입력은 그대로 남아 있습니다. 문제를 해결한 뒤 '코칭 시작'을 다시 누르세요.")
        repo.save_step(conn, sd)

    c1, c2 = st.columns([3, 1])
    can_confirm = len(msgs) > 1 and msgs[-1]["role"] == "assistant"
    if c1.button("✅ 마지막 답을 이 단계의 결과로 확정", type="primary", disabled=not can_confirm, use_container_width=True):
        key = ui.require_api_key()
        repo.archive_step(conn, sd)
        result = msgs[-1]["content"]
        extra_schema = None
        if step.key == "plan":
            extra_schema = {
                "target_amount_krw": {"type": "integer", "description": "확고한 목적의 목표 금액(원, 정수). 알 수 없으면 0"},
                "target_date": {"type": "string", "description": "확고한 목적의 기한 YYYY-MM-DD. 알 수 없으면 빈 문자열"},
            }
        with st.spinner("결과 항목 정리 중…"):
            try:
                fields = ai.extract_fields(key, result, fields_for(step, use_boost), extra_schema)
            except Exception as e:  # 항목 정리가 실패해도 확정은 유지
                fields = {}
                st.warning(f"항목 자동 정리에 실패했습니다. 아래에서 직접 적어 주세요. ({e})")
        sd.update({"result": result, "fields": fields, "confirmed_at": db.now()})
        repo.save_step(conn, sd)
        goal = repo.get_goal(conn)
        if step.key == "plan":
            goal.update({k: fields[v] for k, v in (("purpose", "확고한 목적"), ("statement", "글로 적은 문장"),
                                                    ("first_action", "이번 주 첫 행동")) if fields.get(v)})
            if fields.get("target_amount_krw"):
                goal["target_amount_krw"] = int(fields["target_amount_krw"])
            if re.match(r"^\d{4}-\d{2}-\d{2}$", fields.get("target_date", "")):
                goal["target_date"] = fields["target_date"]
        if step.key == "persist" and fields.get("매일의 습관"):
            goal["habit"] = fields["매일의 습관"]
        repo.save_goal(conn, goal)
        if idx < 3:
            st.session_state.coach_step = STEPS[idx + 1].key
        st.rerun()
    if c2.button("🔄 처음부터 다시", use_container_width=True):
        repo.archive_step(conn, sd)
        sd.update({"messages": [], "result": "", "fields": {}, "confirmed_at": ""})
        repo.save_step(conn, sd)
        st.rerun()

    if answer := st.chat_input("코치의 질문에 답하거나, 더 묻고 싶은 것을 적으세요"):
        msgs.append({"role": "user", "content": answer})
        repo.save_step(conn, sd)
        st.rerun()

# ── 3) 확정된 결과 ─────────────────────────────────────────
if sd["result"]:
    st.divider()
    st.success(f"✅ {step.no}단계 결과 확정 · {sd['confirmed_at']}")
    with st.expander("확정된 결과 항목 (직접 고칠 수 있음)", expanded=True), st.form(f"fields_{step.key}"):
        edited = {n: st.text_area(n, value=str(sd["fields"].get(n, "")), height=80) for n in fields_for(step, use_boost)}
        if st.form_submit_button("저장"):
            sd["fields"].update(edited)
            repo.save_step(conn, sd)
            goal = repo.get_goal(conn)
            if step.key == "plan":
                goal.update(purpose=edited["확고한 목적"], statement=edited["글로 적은 문장"], first_action=edited["이번 주 첫 행동"])
            if step.key == "persist":
                goal["habit"] = edited["매일의 습관"]
            repo.save_goal(conn, goal)
            st.toast("저장했습니다")
    if idx < 3:
        st.info(f"다음: {STEPS[idx + 1].no}단계 — {STEPS[idx + 1].title}")
    else:
        st.info("4단계를 모두 마쳤습니다. 🏠 오늘 화면에서 매일 확인하고, 🗓️ 주간 점검으로 이어가세요.")
