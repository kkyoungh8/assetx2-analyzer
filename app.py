"""
부자코치 — 나폴레온 힐 『생각하라 그리고 부자가 되어라』 기반 개인 코칭 앱
===========================================================================
구성
  🏠 오늘          확고한 목적 문장, 아침·저녁 읽기, 매일 습관, 목표 진척
  🧭 4단계 코칭    진단 → 제안 → 계획 → 지속 (앞 단계 결과가 다음 단계로 자동 연결)
  🗓️ 주간 점검     계획이 막힌 주에 포기 대신 다시 계획하기
  📈 자산제곱      기존 자산제곱 AI 포트폴리오 분석기 (부자코치 산하 모듈)
  💾 데이터        백업·복원

실행
  pip install -r requirements.txt
  streamlit run app.py
"""

import streamlit as st

from richcoach import store

st.set_page_config(
    page_title="부자코치",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "data" not in st.session_state:
    st.session_state.data = store.load()

# ── 공용 API 키 (모든 페이지가 st.session_state.api_key 를 사용) ──
with st.sidebar:
    st.markdown("### 🧭 부자코치")
    try:
        secret_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        secret_key = ""
    if secret_key:
        st.session_state.api_key = secret_key
        st.caption("🔑 API 키: secrets 에서 불러옴")
    else:
        st.session_state.api_key = st.text_input(
            "Claude API 키", type="password", placeholder="sk-ant-...",
            value=st.session_state.get("api_key", ""),
            help="Anthropic Console 에서 발급받은 키. .streamlit/secrets.toml 에 ANTHROPIC_API_KEY 로 넣어 두면 매번 입력하지 않아도 됩니다.",
        )
    st.divider()

pages = st.navigation({
    "부자코치": [
        st.Page("views/home.py", title="오늘", icon="🏠", default=True),
        st.Page("views/coach.py", title="4단계 코칭", icon="🧭"),
        st.Page("views/weekly.py", title="주간 점검", icon="🗓️"),
    ],
    "투자 (부자코치 산하)": [
        st.Page("views/invest.py", title="자산제곱", icon="📈"),
    ],
    "설정": [
        st.Page("views/data.py", title="데이터", icon="💾"),
    ],
})
pages.run()
