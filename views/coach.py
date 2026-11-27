"""🧭 4단계 코칭: 진단 → 제안 → 계획 → 지속"""

import re

import streamlit as st

from richcoach import llm, store
from richcoach.prompts import STEPS, STEP_BY_KEY, build_prompt, fields_for, original_text

data = st.session_state.data
api_key = st.session_state.get("api_key", "")

st.title("🧭 4단계 코칭")
st.caption("나폴레온 힐 『생각하라 그리고 부자가 되어라』 · 앞 단계에서 확정한 결과가 다음 단계의 [이전 결과]로 자동으로 들어갑니다.")


def status_icon(key: str) -> str:
    s = data["steps"][key]
    if s["result"]:
        return "✅"
    if s["messages"]:
        return "💬"
    return "⬜"


labels = {f"{status_icon(s.key)} {s.no}. {s.file.split('-')[1].replace('.md', '')}": s.key for s in STEPS}
default_key = next((s.key for s in STEPS if not data["steps"][s.key]["result"]), "persist")
if "coach_step" not in st.session_state:
    st.session_state.coach_step = default_key
choice = st.segmented_control(
    "단계", list(labels.keys()),
    default=next(l for l, k in labels.items() if k == st.session_state.coach_step),
    label_visibility="collapsed",
)
if choice:
    st.session_state.coach_step = labels[choice]
step = STEP_BY_KEY[st.session_state.coach_step]
sd = data["steps"][step.key]

use_boost = st.toggle(
    "원전 보강 지시 사용", value=data.get("use_boost", True),
    help="원문 프롬프트 끝에 『생각하라 그리고 부자가 되어라』 원전 내용과 자산제곱 연동을 위한 '보강' 지시를 덧붙입니다. 끄면 원문만 보냅니다.",
)
if use_boost != data.get("use_boost"):
    data["use_boost"] = use_boost
    store.save(data)

st.subheader(f"프롬프트 {step.no} / 4 — {step.title}")

with st.expander("📄 원문 프롬프트 보기"):
    st.code(original_text(step), language="markdown", wrap_lines=True)
    if step.boost:
        st.markdown("**보강 지시 (원문에 없음 · 토글로 켜고 끔)**")
        st.code(step.boost, language="markdown", wrap_lines=True)

# ── 1) 입력: 이전 결과 + [직접 적기] 칸 ─────────────────────
prev_text = ""
idx = [s.key for s in STEPS].index(step.key)
if step.needs_prev:
    prev_step = STEPS[idx - 1]
    prev_saved = data["steps"][prev_step.key]["result"]
    if not prev_saved:
        st.warning(f"{prev_step.no}단계 결과가 아직 확정되지 않았습니다. 먼저 {prev_step.no}단계를 마치거나, 아래 칸에 직접 붙여 넣으세요.")

ctx_vals = list(sd.get("ctx") or [])
ctx_vals += [""] * (len(step.ctx_labels) - len(ctx_vals))

locked = bool(sd["messages"])
with st.form(f"ctx_{step.key}", border=True):
    st.markdown("**맥락 채우기**" + (" · 코칭이 시작되어 잠겨 있습니다. 바꾸려면 아래 '처음부터 다시'를 누르세요." if locked else ""))
    if step.needs_prev:
        prev_text = st.text_area(
            f"이전 결과 ({STEPS[idx - 1].no}단계에서 자동으로 가져옴)",
            value=sd.get("prev_override") or data["steps"][STEPS[idx - 1].key]["result"],
            height=180, disabled=locked,
        )
    new_vals = [
        st.text_area(lbl, value=ctx_vals[i], height=90, disabled=locked, key=f"c_{step.key}_{i}")
        for i, lbl in enumerate(step.ctx_labels)
    ]
    extra = ""
    include_invest = False
    if step.key == "plan":
        total, desc = store.latest_total_assets_krw(data)
        snaps = data["invest"]["snapshots"]
        include_invest = st.checkbox(
            "📈 자산제곱 투자 현황을 함께 넣기", value=bool(snaps), disabled=locked or not snaps,
            help="자산제곱 페이지에서 마지막으로 분석한 결과를 맥락에 덧붙입니다." if snaps else "자산제곱 페이지에서 '지금 분석해줘!'를 한 번 실행하면 켤 수 있습니다.",
        )
        if snaps:
            s = snaps[-1]
            extra = (
                f"• 자산제곱 투자 현황: 주식 평가금 ${s['stock_value_usd']:,.0f} (USD/KRW {s['usd_krw']:,.0f}), "
                f"현금 비중 {s['cash_pct']}%, 포트폴리오 존 {s['zone']}, 총자산 추정 ₩{total:,.0f} ({desc})"
            )
    started = st.form_submit_button("▶️ 코칭 시작", type="primary", disabled=locked)

if started:
    if not api_key:
        st.error("사이드바에 Claude API 키를 넣어 주세요.")
        st.stop()
    sd["ctx"] = new_vals
    if step.needs_prev:
        sd["prev_override"] = prev_text if prev_text != data["steps"][STEPS[idx - 1].key]["result"] else ""
    prompt = build_prompt(step, new_vals, prev_text, use_boost, extra if include_invest else "")
    sd["messages"] = [{"role": "user", "content": prompt}]
    sd["result"], sd["fields"], sd["confirmed_at"] = "", {}, ""
    store.save(data)

# ── 2) 대화 ────────────────────────────────────────────────
msgs = sd["messages"]
if msgs:
    st.markdown("---")
    with st.expander("📤 보낸 프롬프트"):
        st.code(msgs[0]["content"], language="markdown", wrap_lines=True)
    for m in msgs[1:]:
        with st.chat_message(m["role"], avatar="🧭" if m["role"] == "assistant" else None):
            st.markdown(m["content"])

    # 마지막 메시지가 user 이면 코치 답을 받음
    if msgs[-1]["role"] == "user":
        if not api_key:
            st.error("사이드바에 Claude API 키를 넣어 주세요.")
            st.stop()
        with st.chat_message("assistant", avatar="🧭"):
            reply = st.write_stream(llm.stream_reply(api_key, msgs))
        if isinstance(reply, str) and reply and not reply.startswith("❌"):
            msgs.append({"role": "assistant", "content": reply})
        else:
            # 실패: 보낸 메시지를 되돌려 같은 요청이 화면을 다시 그릴 때마다 반복되지 않게 함
            failed = msgs.pop()
            if not msgs:
                st.info("맥락 입력은 그대로 남아 있습니다. 문제를 해결한 뒤 '코칭 시작'을 다시 누르세요.")
            else:
                st.info("보내려던 답장(아래)을 복사해 다시 보내 주세요.")
                st.code(failed["content"], language=None, wrap_lines=True)
        store.save(data)

    c1, c2 = st.columns([3, 1])
    with c1:
        can_confirm = len(msgs) > 1 and msgs[-1]["role"] == "assistant"
        if st.button("✅ 마지막 답을 이 단계의 결과로 확정", type="primary", disabled=not can_confirm, use_container_width=True):
            result = msgs[-1]["content"]
            sd["result"], sd["confirmed_at"] = result, store.now_str()
            extra_schema = None
            if step.key == "plan":
                extra_schema = {
                    "target_amount_krw": {"type": "integer", "description": "확고한 목적의 목표 금액을 원 단위 정수로. 알 수 없으면 0"},
                    "target_date": {"type": "string", "description": "확고한 목적의 기한을 YYYY-MM-DD 로. 알 수 없으면 빈 문자열"},
                }
            with st.spinner("결과 항목 정리 중…"):
                try:
                    sd["fields"] = llm.extract_fields(api_key, result, fields_for(step, use_boost), extra_schema)
                except Exception as e:  # 항목 추출이 실패해도 결과 확정은 유지
                    sd["fields"] = {}
                    st.warning(f"항목 자동 정리에 실패했습니다. 아래에서 직접 적어 주세요. ({e})")
            f = sd["fields"]
            g = data["goal"]
            if step.key == "plan":
                g["purpose"] = f.get("확고한 목적", g["purpose"])
                g["statement"] = f.get("글로 적은 문장", g["statement"])
                g["first_action"] = f.get("이번 주 첫 행동", g["first_action"])
                if f.get("target_amount_krw"):
                    g["target_amount_krw"] = int(f["target_amount_krw"])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", f.get("target_date", "")):
                    g["target_date"] = f["target_date"]
            if step.key == "persist":
                g["habit"] = f.get("매일의 습관", g["habit"])
            store.save(data)
            if idx < 3:
                st.session_state.coach_step = STEPS[idx + 1].key
            st.rerun()
    with c2:
        if st.button("🔄 처음부터 다시", use_container_width=True):
            sd["messages"], sd["result"], sd["fields"], sd["confirmed_at"] = [], "", {}, ""
            store.save(data)
            st.rerun()

    if answer := st.chat_input("코치의 질문에 답하거나, 더 묻고 싶은 것을 적으세요"):
        msgs.append({"role": "user", "content": answer})
        store.save(data)
        st.rerun()

# ── 3) 확정된 결과 ─────────────────────────────────────────
if sd["result"]:
    st.markdown("---")
    st.success(f"✅ {step.no}단계 결과 확정 · {sd['confirmed_at']}")
    with st.expander("확정된 결과 항목 (직접 고칠 수 있음)", expanded=True):
        with st.form(f"fields_{step.key}"):
            edited = {
                name: st.text_area(name, value=str(sd["fields"].get(name, "")), height=80)
                for name in fields_for(step, use_boost)
            }
            if st.form_submit_button("저장"):
                sd["fields"].update(edited)
                g = data["goal"]
                if step.key == "plan":
                    g["purpose"], g["statement"], g["first_action"] = edited["확고한 목적"], edited["글로 적은 문장"], edited["이번 주 첫 행동"]
                if step.key == "persist":
                    g["habit"] = edited["매일의 습관"]
                store.save(data)
                st.toast("저장했습니다")
    if idx < 3:
        st.info(f"다음: {STEPS[idx + 1].no}단계 — {STEPS[idx + 1].title}")
    else:
        st.info("4단계를 모두 마쳤습니다. 🏠 오늘 화면에서 매일 확인하고, 🗓️ 주간 점검으로 이어가세요.")
