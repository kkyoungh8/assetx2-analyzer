"""
부자코치 — 나폴레온 힐 『생각하라 그리고 부자가 되어라』 기반 개인 앱 (맥북 로컬 실행)
설계: docs/ARCHITECTURE.md · 실행: README.md
"""

import streamlit as st

from core import ui

st.set_page_config(page_title="부자코치", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")

with st.sidebar:
    st.markdown("### 🧭 부자코치")
    ui.sidebar_api_key()
    st.divider()

pages = st.navigation({
    "부자코치": [
        st.Page("views/home.py", title="오늘", icon="🏠", default=True),
        st.Page("views/coach.py", title="4단계 코칭", icon="🧭"),
        st.Page("views/weekly.py", title="주간 점검", icon="🗓️"),
    ],
    "투자 (부자코치 산하)": [
        # P2 에서 invest/ 모듈로 재설계한 화면으로 교체 예정
        st.Page("views/legacy_invest.py", title="자산제곱 (기존)", icon="📈"),
    ],
    "설정": [
        st.Page("views/data.py", title="데이터", icon="💾"),
    ],
})
pages.run()
