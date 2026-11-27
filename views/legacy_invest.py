"""📈 자산제곱 (기존 분석기) — P2 재설계 전까지 비교·참고용으로 그대로 띄움"""

import streamlit as st

from legacy import assetx2_app

st.info(
    "기존 자산제곱 분석기를 그대로 띄운 화면입니다. P2에서 토스증권·미래에셋 계좌별 보유 종목 저장, "
    "리포트 PDF 기반 전략, 부자코치 목표 연동을 넣어 새로 만듭니다. "
    "저장소를 비공개로 바꾸면 이 화면의 '전략 컨텍스트'(GitHub 에서 읽어 옴)는 불러오지 못합니다.",
    icon="🚧",
)
assetx2_app.render()
