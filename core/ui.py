"""Streamlit 공용 도우미"""

import streamlit as st

from core import config, db


@st.cache_resource
def conn():
    return db.connect()


def api_key() -> str:
    return st.session_state.get("api_key", "")


def require_api_key() -> str:
    k = api_key()
    if not k:
        st.error("사이드바에 Claude API 키를 넣거나 ~/.richcoach/secrets.toml 에 ANTHROPIC_API_KEY 를 적어 주세요.")
        st.stop()
    return k


def sidebar_api_key() -> None:
    k = config.secret("ANTHROPIC_API_KEY")
    if k:
        st.session_state.api_key = k
        st.caption("🔑 API 키: secrets 에서 불러옴")
    else:
        st.session_state.api_key = st.text_input(
            "Claude API 키", type="password", placeholder="sk-ant-...",
            value=st.session_state.get("api_key", ""),
            help="~/.richcoach/secrets.toml 에 ANTHROPIC_API_KEY = \"...\" 로 적어 두면 매번 넣지 않아도 됩니다.",
        )
