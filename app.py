"""
자산제곱 AI 포트폴리오 분석기
================================
자산제곱 5존 시스템 기반 포트폴리오 분석 웹앱
yfinance 실시간 주가 + Claude AI 분석

사용법:
  pip install -r requirements.txt
  streamlit run app.py
"""

import streamlit as st
import yfinance as yf
import anthropic
import pandas as pd
from datetime import datetime
import time

# ── 페이지 설정 ──────────────────────────────────────────────
st.set_page_config(
    page_title="자산제곱 AI 분석기",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS 스타일 ───────────────────────────────────────────────
st.markdown("""
<style>
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1rem;
        color: #6c757d;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1.2rem;
        border-left: 4px solid #4361ee;
    }
    .zone-sell  { background-color: #fff0f0; border-left: 4px solid #e74c3c; border-radius: 8px; padding: 0.8rem; margin: 0.3rem 0; }
    .zone-watch { background-color: #fff8e1; border-left: 4px solid #f39c12; border-radius: 8px; padding: 0.8rem; margin: 0.3rem 0; }
    .zone-hold  { background-color: #f0fff4; border-left: 4px solid #27ae60; border-radius: 8px; padding: 0.8rem; margin: 0.3rem 0; }
    .zone-take  { background-color: #e8f4fd; border-left: 4px solid #2980b9; border-radius: 8px; padding: 0.8rem; margin: 0.3rem 0; }
    .report-box {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #e0e0e0;
        margin-top: 1rem;
        white-space: pre-wrap;
        font-family: 'Malgun Gothic', sans-serif;
        line-height: 1.8;
    }
    .stButton > button {
        width: 100%;
        background-color: #4361ee;
        color: white;
        border-radius: 8px;
        height: 3rem;
        font-size: 1.1rem;
        font-weight: 600;
        border: none;
    }
    .stButton > button:hover {
        background-color: #3730a3;
    }
</style>
""", unsafe_allow_html=True)


# ── 자산제곱 5존 시스템 ──────────────────────────────────────
def get_zone(gain_pct: float) -> tuple[str, str, str]:
    """수익률 기반 5존 판단. Returns (emoji_label, css_class, action)"""
    if gain_pct <= -8:
        return "🚨 손절", "zone-sell", "손절선 돌파 — 즉시 전량 매도 권고"
    elif gain_pct <= -5:
        return "⚠️ 경계", "zone-watch", "손절선 근접 — 일일 모니터링 필수, 추가 하락 시 즉시 매도"
    elif gain_pct >= 60:
        return "💰 2차 익절", "zone-take", "2차 익절 구간 — 포지션 25~50% 분할 매도 검토"
    elif gain_pct >= 40:
        return "💰 1차 익절", "zone-take", "1차 익절 구간 — 포지션 20~25% 분할 매도 검토"
    elif gain_pct >= 20:
        return "📈 익절 고려", "zone-take", "수익 구간 — 분할 익절 타이밍 모니터링"
    else:
        return "✅ 홀딩", "zone-hold", "정상 보유 구간 — 유지"


def get_52w_signal(pos_pct: float) -> str:
    if pos_pct >= 90:
        return "🔴 52주 고점권 (과열 주의)"
    elif pos_pct >= 70:
        return "🟡 상단권 (모니터링)"
    elif pos_pct >= 40:
        return "🟢 중간권 (정상)"
    else:
        return "🔵 하단권 (기회 탐색)"


def get_portfolio_zone(stock_pct: float) -> tuple[str, str]:
    if stock_pct >= 75:
        return "Zone 2 — 공격적", "익절 우선. 현금 비중 확대 검토"
    elif stock_pct >= 55:
        return "Zone 3 — 중립 ✅", "목표 구간. 현재 전략 유지"
    elif stock_pct >= 40:
        return "Zone 4 — 방어적", "선택적 매수 가능. 현금 보유 유지"
    else:
        return "Zone 5 — 최대 방어", "현금 보유. 대형 기회 대기"


# ── 실시간 주가 조회 ─────────────────────────────────────────
@st.cache_data(ttl=300)  # 5분 캐시
def fetch_stock_data(ticker: str) -> dict:
    """yfinance로 실시간 주가 + 52주 데이터 조회"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist_1y = stock.history(period="1y")
        hist_1d = stock.history(period="1d")

        if hist_1d.empty:
            return {}

        current = float(hist_1d["Close"].iloc[-1])
        low_52w = float(hist_1y["Low"].min()) if not hist_1y.empty else 0
        high_52w = float(hist_1y["High"].max()) if not hist_1y.empty else 0
        volume = int(hist_1d["Volume"].iloc[-1]) if not hist_1d.empty else 0
        avg_volume = int(info.get("averageVolume", 0))
        name = info.get("shortName", ticker)

        pos_52w = 0
        if high_52w > low_52w:
            pos_52w = round((current - low_52w) / (high_52w - low_52w) * 100, 1)

        vol_ratio = round(volume / avg_volume, 2) if avg_volume > 0 else 1.0

        return {
            "name": name,
            "current": current,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "volume": volume,
            "avg_volume": avg_volume,
            "pos_52w": pos_52w,
            "vol_ratio": vol_ratio,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Claude AI 분석 ───────────────────────────────────────────
def analyze_with_claude(api_key: str, portfolio_summary: str, cash_pct: float, zone_name: str) -> str:
    """Claude API로 포트폴리오 종합 분석"""
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""당신은 자산제곱 프레임워크를 사용하는 전문 포트폴리오 애널리스트입니다.

## 현재 포트폴리오 현황
{portfolio_summary}

## 포트폴리오 존 상태
- 현금 비중: {cash_pct:.1f}%
- 주식 비중: {100 - cash_pct:.1f}%
- 포트폴리오 존: {zone_name}

## 분석 요청
위 포트폴리오를 자산제곱 5존 프레임워크로 분석해주세요.

다음 순서로 작성해주세요:
1. **📊 전체 평가** (2~3문장, 포트폴리오 전반적인 상태)
2. **🚨 즉시 액션 필요** (손절/익절 필요 종목 중심, 없으면 "없음")
3. **💡 핵심 인사이트** (2~3가지, 가장 중요한 것)
4. **📅 이번 주 할 일** (구체적인 액션 3가지 이내)

톤: 친절하지만 솔직하게. 불필요한 칭찬 없이. 한국어로."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except anthropic.AuthenticationError:
        return "❌ API 키가 올바르지 않습니다. 사이드바에서 API 키를 확인해주세요."
    except Exception as e:
        return f"❌ 분석 중 오류 발생: {str(e)}"


# ── 메인 앱 ─────────────────────────────────────────────────
def main():
    # 타이틀
    st.markdown('<p class="main-title">📊 자산제곱 AI 분석기</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">포트폴리오를 입력하고 AI 분석을 받아보세요</p>', unsafe_allow_html=True)

    # ── 사이드바 ──
    with st.sidebar:
        st.header("⚙️ 설정")

        # secrets에 키가 있으면 자동 사용, 없으면 입력칸 표시
        _secret_key = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else ""
        if _secret_key:
            api_key = _secret_key
            st.success("✅ API 키 설정 완료", icon="🔑")
        else:
            api_key = st.text_input(
                "Claude API 키",
                type="password",
                placeholder="sk-ant-...",
                help="Anthropic Console에서 발급받은 API 키를 입력하세요.",
            )

        st.divider()

        cash_pct = st.slider(
            "💰 현금 비중 (%)",
            min_value=0,
            max_value=100,
            value=27,
            step=1,
            help="전체 자산 중 현금이 차지하는 비율"
        )

        stock_pct = 100 - cash_pct
        zone_name, zone_desc = get_portfolio_zone(stock_pct)

        st.markdown(f"""
        **포트폴리오 존:**
        **{zone_name}**
        <small>{zone_desc}</small>
        """, unsafe_allow_html=True)

        st.divider()
        st.markdown("""
        **자산제곱 5존 기준**
        | 수익률 | 상태 |
        |--------|------|
        | ≤ -8% | 🚨 손절 |
        | ≤ -5% | ⚠️ 경계 |
        | +20%~ | 📈 익절고려 |
        | +40%~ | 💰 1차익절 |
        | +60%~ | 💰 2차익절 |
        | 나머지 | ✅ 홀딩 |
        """)

    # ── 포트폴리오 입력 ──
    st.subheader("📋 보유 종목 입력")
    st.caption("티커 심볼은 Yahoo Finance 기준 (예: AVGO, GEV, 005930.KS)")

    # 세션 상태로 종목 관리
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = [
            {"ticker": "AVGO", "shares": 10.0, "avg_price": 333.77},
            {"ticker": "GEV",  "shares": 5.0,  "avg_price": 652.63},
            {"ticker": "VRT",  "shares": 8.0,  "avg_price": 196.52},
        ]

    # 종목 추가/삭제 버튼
    col_add, col_clear, _ = st.columns([1, 1, 4])
    with col_add:
        if st.button("➕ 종목 추가"):
            st.session_state.portfolio.append({"ticker": "", "shares": 1.0, "avg_price": 0.0})
            st.rerun()
    with col_clear:
        if st.button("🗑️ 전체 삭제"):
            st.session_state.portfolio = []
            st.rerun()

    # 종목 입력 테이블
    to_delete = []
    for i, row in enumerate(st.session_state.portfolio):
        cols = st.columns([2, 2, 2, 0.5])
        with cols[0]:
            ticker = st.text_input(
                "티커", value=row["ticker"], key=f"ticker_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                placeholder="AVGO"
            )
            st.session_state.portfolio[i]["ticker"] = ticker.upper().strip()
        with cols[1]:
            shares = st.number_input(
                "보유 수량", value=float(row["shares"]), min_value=0.001,
                key=f"shares_{i}", format="%.4f",
                label_visibility="collapsed" if i > 0 else "visible",
            )
            st.session_state.portfolio[i]["shares"] = shares
        with cols[2]:
            avg_price = st.number_input(
                "평균단가 ($)", value=float(row["avg_price"]), min_value=0.01,
                key=f"avg_{i}", format="%.2f",
                label_visibility="collapsed" if i > 0 else "visible",
            )
            st.session_state.portfolio[i]["avg_price"] = avg_price
        with cols[3]:
            if i == 0:
                st.write("삭제")
            if st.button("✕", key=f"del_{i}"):
                to_delete.append(i)

    for idx in sorted(to_delete, reverse=True):
        st.session_state.portfolio.pop(idx)
    if to_delete:
        st.rerun()

    st.divider()

    # ── 분석 버튼 ──
    if st.button("🔍 지금 분석해줘!", type="primary"):
        valid_rows = [r for r in st.session_state.portfolio
                      if r["ticker"] and r["shares"] > 0 and r["avg_price"] > 0]

        if not valid_rows:
            st.error("분석할 종목을 먼저 입력해주세요.")
            return

        if not api_key:
            st.error("사이드바에서 Claude API 키를 입력해주세요.")
            return

        # 주가 조회
        progress = st.progress(0, text="실시간 주가 조회 중...")
        results = []
        alerts = []
        holds = []
        total_value = 0
        total_cost = 0

        for i, row in enumerate(valid_rows):
            ticker = row["ticker"]
            progress.progress((i + 1) / len(valid_rows),
                              text=f"주가 조회 중... {ticker} ({i+1}/{len(valid_rows)})")

            data = fetch_stock_data(ticker)
            if not data or "error" in data:
                results.append({**row, "error": data.get("error", "조회 실패"), "current": None})
                continue

            current = data["current"]
            avg_p = row["avg_price"]
            shares = row["shares"]
            gain_pct = (current - avg_p) / avg_p * 100
            mkt_val = current * shares
            cost = avg_p * shares
            pnl = mkt_val - cost

            zone_label, zone_css, zone_action = get_zone(gain_pct)
            sig_52w = get_52w_signal(data["pos_52w"])

            entry = {
                "ticker": ticker,
                "name": data.get("name", ticker),
                "shares": shares,
                "avg_price": avg_p,
                "current": current,
                "gain_pct": gain_pct,
                "mkt_val": mkt_val,
                "cost": cost,
                "pnl": pnl,
                "pos_52w": data["pos_52w"],
                "low_52w": data["low_52w"],
                "high_52w": data["high_52w"],
                "vol_ratio": data["vol_ratio"],
                "zone_label": zone_label,
                "zone_css": zone_css,
                "zone_action": zone_action,
                "sig_52w": sig_52w,
                "stop_price": avg_p * 0.92,
            }
            results.append(entry)
            total_value += mkt_val
            total_cost += cost

            if "손절" in zone_label or "경계" in zone_label or "익절" in zone_label:
                alerts.append(entry)
            else:
                holds.append(entry)

        progress.empty()

        # ── 결과 표시 ──
        total_gain_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
        pnl_color = "green" if total_value >= total_cost else "red"
        pnl_sign = "+" if total_value >= total_cost else ""

        st.markdown("---")

        # 요약 메트릭
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 평가금", f"${total_value:,.0f}")
        m2.metric("총 원금", f"${total_cost:,.0f}")
        m3.metric("총 손익", f"{pnl_sign}${total_value - total_cost:,.0f}",
                  delta=f"{pnl_sign}{total_gain_pct:.2f}%")
        m4.metric("포트폴리오 존", zone_name)

        st.markdown("---")

        # 종목별 결과 테이블
        st.subheader("📋 종목별 현황")
        df_rows = []
        for r in results:
            if r.get("current") is None:
                df_rows.append({
                    "종목": r["ticker"], "현재가": "조회실패", "수익률": "-",
                    "평가금": "-", "손익": "-", "52주위치": "-", "상태": "❌ 조회실패"
                })
            else:
                df_rows.append({
                    "종목": r["ticker"],
                    "현재가": f"${r['current']:.2f}",
                    "수익률": f"{r['gain_pct']:+.2f}%",
                    "평가금": f"${r['mkt_val']:,.0f}",
                    "손익": f"${r['pnl']:+,.0f}",
                    "52주위치": f"{r['pos_52w']:.0f}%",
                    "상태": r["zone_label"],
                })

        df = pd.DataFrame(df_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # 즉시 액션 종목
        if alerts:
            st.subheader("🎯 즉시 액션 필요 종목")
            for r in alerts:
                with st.container():
                    st.markdown(f"""
                    <div class="{r['zone_css']}">
                    <strong>{r['zone_label']} | {r['ticker']} — {r['name']}</strong><br>
                    현재가 <strong>${r['current']:.2f}</strong> |
                    평균단가 ${r['avg_price']:.2f} |
                    수익률 <strong>{r['gain_pct']:+.2f}%</strong> |
                    평가금 ${r['mkt_val']:,.0f} (손익 ${r['pnl']:+,.0f})<br>
                    손절가(-8%) <strong>${r['stop_price']:.2f}</strong> |
                    현재까지 여유 ${r['current'] - r['stop_price']:+.2f} |
                    52주 {r['pos_52w']:.0f}% {r['sig_52w']}<br>
                    💡 <em>{r['zone_action']}</em>
                    </div>
                    """, unsafe_allow_html=True)

        # 홀딩 종목
        if holds:
            with st.expander(f"✅ 정상 홀딩 종목 ({len(holds)}개)", expanded=False):
                for r in holds:
                    st.markdown(f"""
                    <div class="zone-hold">
                    <strong>{r['ticker']} — {r['name']}</strong> |
                    ${r['current']:.2f} | {r['gain_pct']:+.2f}% |
                    52주 {r['pos_52w']:.0f}% | {r['sig_52w']}
                    </div>
                    """, unsafe_allow_html=True)

        # Claude AI 분석
        st.markdown("---")
        st.subheader("🤖 AI 종합 분석")

        with st.spinner("Claude AI가 포트폴리오를 분석하고 있습니다..."):
            # 포트폴리오 요약 텍스트 생성
            summary_lines = []
            for r in results:
                if r.get("current"):
                    summary_lines.append(
                        f"- {r['ticker']} ({r['name']}): "
                        f"현재 ${r['current']:.2f}, 평균단가 ${r['avg_price']:.2f}, "
                        f"수익률 {r['gain_pct']:+.2f}%, 평가금 ${r['mkt_val']:,.0f}, "
                        f"손익 ${r['pnl']:+,.0f}, 52주위치 {r['pos_52w']:.0f}%, "
                        f"상태: {r['zone_label']}"
                    )
            portfolio_summary = "\n".join(summary_lines)
            portfolio_summary += f"\n\n총 평가금: ${total_value:,.0f} | 총 손익: {total_gain_pct:+.2f}%"

            ai_report = analyze_with_claude(api_key, portfolio_summary, cash_pct, zone_name)

        st.markdown(f'<div class="report-box">{ai_report}</div>', unsafe_allow_html=True)

        # 생성 시각
        st.caption(f"분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 주가 데이터: yfinance (5분 캐시)")

        # 면책 조항
        with st.expander("⚠️ 면책 조항"):
            st.markdown("""
            본 서비스는 개인적인 포트폴리오 현황 파악을 위한 참고 도구입니다.
            투자 조언이나 매수/매도 권유를 목적으로 하지 않습니다.
            모든 투자 결정과 그 결과에 대한 책임은 투자자 본인에게 있습니다.
            주가 데이터는 실시간이 아닐 수 있으며, 정확성을 보장하지 않습니다.
            """)


if __name__ == "__main__":
    main()
