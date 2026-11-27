"""💾 데이터: 백업·복원"""

import json

import streamlit as st

from richcoach import store

data = st.session_state.data

st.title("💾 데이터")
st.markdown(
    f"모든 기록은 이 컴퓨터의 `{store.DATA_PATH}` 파일 하나에 저장되고, git 에는 올라가지 않습니다.\n\n"
    "⚠️ Streamlit Community Cloud 같은 곳에 올려 쓰면, 앱이 다시 시작될 때 이 파일이 사라질 수 있습니다. "
    "그 경우 아래 백업 파일을 주기적으로 내려받아 두세요."
)

st.download_button(
    "⬇️ 백업 내려받기 (JSON)",
    data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
    file_name=f"richcoach-backup-{store.today_key()}.json",
    mime="application/json",
    type="primary",
)

st.markdown("---")
up = st.file_uploader("백업 파일로 복원", type=["json"])
if up is not None and st.button("이 파일로 덮어쓰기"):
    try:
        st.session_state.data = store.import_json(up.getvalue())
        store.save(st.session_state.data)
        st.success("복원했습니다.")
        st.rerun()
    except (ValueError, json.JSONDecodeError) as e:
        st.error(f"읽을 수 없는 파일입니다: {e}")

st.markdown("---")
with st.expander("🗑️ 전체 초기화"):
    st.warning("코칭 결과, 습관 기록, 주간 점검, 저장된 보유 종목이 모두 지워집니다. 먼저 백업하세요.")
    if st.checkbox("이해했습니다") and st.button("초기화", type="primary"):
        st.session_state.data = store.load.__globals__["copy"].deepcopy(store.DEFAULT)
        store.save(st.session_state.data)
        for k in ("portfolio", "coach_step", "last_portfolio_snapshot"):
            st.session_state.pop(k, None)
        st.rerun()
