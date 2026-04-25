"""
자산제곱 AI 포트폴리오 분석기
================================
자산제곱 5존 시스템 기반 포트폴리오 분석 웹앱
yfinance 실시간 주가 + Claude AI 분석 + 이미지 파싱

사용법:
  pip install -r requirements.txt
  streamlit run app.py
"""

import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import anthropic
import pandas as pd
from datetime import datetime
import base64
import json
import re

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
    .upload-box {
        background: #f0f4ff;
        border: 2px dashed #4361ee;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
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


# ── 유틸 함수 ────────────────────────────────────────────────

def detect_currency(ticker: str) -> str:
    """티커로 통화 자동 감지"""
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "KRW"
    return "USD"

def normalize_ticker(ticker: str) -> str:
    """6자리 숫자 → .KS 자동 변환, 대문자 정리"""
    t = ticker.strip()
    if re.match(r'^\d{6}$', t):
        return t + ".KS"
    return t.upper()

def format_price(price: float, currency: str) -> str:
    if currency == "KRW":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"

def format_value(val: float, currency: str) -> str:
    if currency == "KRW":
        return f"₩{val:,.0f}"
    return f"${val:,.0f}"

def get_tv_symbol(ticker: str) -> str:
    """yfinance 티커 → TradingView 심볼"""
    t = ticker.upper()
    if t.endswith(".KS"):
        return f"KRX:{t[:-3]}"
    elif t.endswith(".KQ"):
        return f"KOSDAQ:{t[:-3]}"
    return t

@st.cache_data(ttl=600)
def get_usd_krw_rate() -> float:
    """USD/KRW 환율 조회 (10분 캐시)"""
    try:
        hist = yf.Ticker("USDKRW=X").history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1350.0


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
    """yfinance로 실시간 주가 + 52주 데이터 조회 (한국/미국 모두 지원)"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # 1d 데이터 먼저 시도, 없으면 5d
        hist_1d = stock.history(period="1d")
        if hist_1d.empty:
            hist_1d = stock.history(period="5d")
        if hist_1d.empty:
            return {"error": f"{ticker} 데이터를 찾을 수 없습니다. 티커를 확인해주세요."}

        hist_1y = stock.history(period="1y")

        current = float(hist_1d["Close"].iloc[-1])
        low_52w  = float(hist_1y["Low"].min())  if not hist_1y.empty else current * 0.7
        high_52w = float(hist_1y["High"].max()) if not hist_1y.empty else current * 1.3
        volume    = int(hist_1d["Volume"].iloc[-1]) if not hist_1d.empty else 0
        avg_volume = int(info.get("averageVolume", 0))

        # 종목명: 한국어 우선
        name = (info.get("longName") or info.get("shortName") or ticker)

        pos_52w = 0.0
        if high_52w > low_52w:
            pos_52w = round((current - low_52w) / (high_52w - low_52w) * 100, 1)

        vol_ratio = round(volume / avg_volume, 2) if avg_volume > 0 else 1.0

        # 통화 (yfinance가 제공하는 경우 사용)
        currency = info.get("currency", "USD")

        return {
            "name": name,
            "current": current,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "volume": volume,
            "avg_volume": avg_volume,
            "pos_52w": pos_52w,
            "vol_ratio": vol_ratio,
            "currency": currency,
        }
    except Exception as e:
        return {"error": str(e)}


# ── 이미지 → 포트폴리오 파싱 ────────────────────────────────

def parse_portfolio_from_image(api_key: str, image_bytes: bytes, media_type: str) -> list:
    """Claude Vision으로 보유종목 스크린샷 → 포트폴리오 자동 파싱"""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        image_b64 = base64.b64encode(image_bytes).decode()

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": """이 이미지는 주식 보유종목 화면입니다. 보유종목 정보를 추출해주세요.

반드시 아래 JSON 배열 형식으로만 답변하세요 (다른 설명 없이):
[
  {"ticker": "종목코드", "shares": 보유수량숫자, "avg_price": 평균단가숫자, "currency": "KRW 또는 USD"},
  ...
]

규칙:
- 한국 주식(숫자 종목코드): .KS 추가 (예: 005930 → 005930.KS)
- 미국 주식: 그대로 (예: AAPL, AVGO)
- 원화 단가 → "KRW", 달러 단가 → "USD"
- 수량·단가가 불명확하면 해당 종목 제외
- 숫자에 콤마 제거 (예: 1,000 → 1000)""",
                    },
                ],
            }],
        )

        text = message.content[0].text.strip()
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            result = []
            for item in parsed:
                if "ticker" in item and "shares" in item and "avg_price" in item:
                    result.append({
                        "ticker": str(item["ticker"]).strip().upper(),
                        "shares": float(item["shares"]),
                        "avg_price": float(item["avg_price"]),
                        "currency": item.get("currency", "USD"),
                    })
            return result
        return []
    except Exception as e:
        st.error(f"이미지 파싱 오류: {e}")
        return []


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
        return "❌ API 키가 올바르지 않습니다."
    except Exception as e:
        return f"❌ 분석 중 오류 발생: {str(e)}"


# ── TradingView 미니 차트 ────────────────────────────────────

def show_tradingview_chart(ticker: str, height: int = 400):
    """TradingView 임베드 차트"""
    tv_symbol = get_tv_symbol(ticker)
    html = f"""
    <div class="tradingview-widget-container" style="height:{height}px; width:100%">
      <div id="tv_{ticker.replace('.','_')}" style="height:{height}px; width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{tv_symbol}",
          "interval": "D",
          "timezone": "Asia/Seoul",
          "theme": "light",
          "style": "1",
          "locale": "kr",
          "toolbar_bg": "#f1f3f6",
          "enable_publishing": false,
          "hide_top_toolbar": false,
          "hide_legend": false,
          "save_image": false,
          "container_id": "tv_{ticker.replace('.','_')}"
        }});
      </script>
    </div>
    """
    components.html(html, height=height + 20)


# ── 메인 앱 ─────────────────────────────────────────────────

def main():
    st.markdown('<p class="main-title">📊 자산제곱 AI 분석기</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">포트폴리오를 입력하고 AI 분석을 받아보세요</p>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("⚙️ 설정")

        _secret_key = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else ""
        if _secret_key:
            api_key = _secret_key
            st.success("✅ API 키 설정 완료", icon="🔑")
        else:
            api_key = st.text_input(
                "Claude API 키", type="password", placeholder="sk-ant-...",
                help="Anthropic Console에서 발급받은 API 키를 입력하세요.",
            )

        st.divider()
        cash_pct = st.slider("💰 현금 비중 (%)", min_value=0, max_value=100, value=27, step=1)
        stock_pct = 100 - cash_pct
        zone_name, zone_desc = get_portfolio_zone(stock_pct)

        st.markdown(f"**포트폴리오 존:** **{zone_name}**<br><small>{zone_desc}</small>", unsafe_allow_html=True)

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

        st.divider()
        st.caption("💱 USD/KRW 환율")
        usd_krw = get_usd_krw_rate()
        st.info(f"₩{usd_krw:,.0f} / $1")

    st.subheader("📋 보유 종목 입력")
    st.caption("티커: 미국주식(AVGO, AAPL), 한국주식(005930.KS 또는 숫자 6자리 자동변환)")

    if "portfolio" not in st.session_state:
        st.session_state.portfolio = [
            {"ticker": "AVGO",      "shares": 10.0, "avg_price": 333.77, "currency": "USD"},
            {"ticker": "GEV",       "shares":  5.0, "avg_price": 652.63, "currency": "USD"},
            {"ticker": "005930.KS", "shares": 10.0, "avg_price": 75000,  "currency": "KRW"},
        ]

    with st.expander("📸 보유종목 스크린샷으로 자동 추가", expanded=False):
        st.markdown('<div class="upload-box">', unsafe_allow_html=True)
        st.write("**증권사 앱 보유종목 화면을 캡처해서 업로드하면 자동으로 입력됩니다.**")
        st.caption("지원 형식: PNG, JPG, JPEG • Claude Vision이 종목코드·수량·단가를 자동 인식")
        uploaded_file = st.file_uploader("이미지 업로드", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
        if uploaded_file is not None:
            col_img, col_btn = st.columns([3, 1])
            with col_img:
                st.image(uploaded_file, caption="업로드된 이미지", use_container_width=True)
            with col_btn:
                st.write(""); st.write("")
                if st.button("🔍 자동 인식", type="primary"):
                    if not api_key:
                        st.error("API 키가 필요합니다.")
                    else:
                        with st.spinner("Claude가 종목을 인식하는 중..."):
                            image_bytes = uploaded_file.getvalue()
                            media_type = f"image/{uploaded_file.type.split('/')[-1]}"
                            if media_type == "image/jpg":
                                media_type = "image/jpeg"
                            parsed = parse_portfolio_from_image(api_key, image_bytes, media_type)
                        if parsed:
                            added = 0
                            for item in parsed:
                                item["ticker"] = normalize_ticker(item["ticker"])
                                existing = [r["ticker"] for r in st.session_state.portfolio]
                                if item["ticker"] not in existing:
                                    st.session_state.portfolio.append(item)
                                    added += 1
                            st.success(f"✅ {added}개 종목 추가됨")
                            st.rerun()
                        else:
                            st.warning("종목을 인식하지 못했습니다.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    col_add, col_clear, _ = st.columns([1, 1, 4])
    with col_add:
        if st.button("➕ 종목 추가"):
            st.session_state.portfolio.append({"ticker": "", "shares": 1.0, "avg_price": 0.0, "currency": "USD"})
            st.rerun()
    with col_clear:
        if st.button("🗑️ 전체 삭제"):
            st.session_state.portfolio = []
            st.rerun()

    if st.session_state.portfolio:
        hcols = st.columns([2, 1.5, 0.9, 2, 0.5])
        hcols[0].markdown("**티커**"); hcols[1].markdown("**수량**")
        hcols[2].markdown("**통화**"); hcols[3].markdown("**평균단가**"); hcols[4].markdown("**삭제**")

    to_delete = []
    for i, row in enumerate(st.session_state.portfolio):
        cols = st.columns([2, 1.5, 0.9, 2, 0.5])
        with cols[0]:
            ticker_raw = st.text_input("티커", value=row["ticker"], key=f"ticker_{i}",
                label_visibility="collapsed", placeholder="AVGO 또는 005930")
            ticker = normalize_ticker(ticker_raw)
            st.session_state.portfolio[i]["ticker"] = ticker
            if ticker != row["ticker"] and ticker:
                st.session_state.portfolio[i]["currency"] = detect_currency(ticker)
        with cols[1]:
            shares = st.number_input("수량", value=float(row["shares"]), min_value=0.0001,
                key=f"shares_{i}", format="%.4f", label_visibility="collapsed")
            st.session_state.portfolio[i]["shares"] = shares
        with cols[2]:
            curr = row.get("currency", "USD")
            currency = st.selectbox("통화", options=["USD", "KRW"],
                index=0 if curr == "USD" else 1, key=f"curr_{i}", label_visibility="collapsed")
            st.session_state.portfolio[i]["currency"] = currency
        with cols[3]:
            if currency == "KRW":
                fmt, label, min_v, step_v = "%.0f", "평균단가 (₩)", 0.0, 100.0
            else:
                fmt, label, min_v, step_v = "%.2f", "평균단가 ($)", 0.0, 0.01
            avg_price = st.number_input(label, value=float(row["avg_price"]),
                min_value=min_v, step=step_v, key=f"avg_{i}", format=fmt, label_visibility="collapsed")
            st.session_state.portfolio[i]["avg_price"] = avg_price
        with cols[4]:
            if st.button("✕", key=f"del_{i}"):
                to_delete.append(i)

    for idx in sorted(to_delete, reverse=True):
        st.session_state.portfolio.pop(idx)
    if to_delete:
        st.rerun()

    st.divider()

    if st.button("🔍 지금 분석해줘!", type="primary"):
        valid_rows = [r for r in st.session_state.portfolio
                      if r["ticker"] and r["shares"] > 0 and r["avg_price"] > 0]
        if not valid_rows:
            st.error("분석할 종목을 먼저 입력해주세요.")
            return
        if not api_key:
            st.error("사이드바에서 Claude API 키를 입력해주세요.")
            return

        usd_krw = get_usd_krw_rate()
        progress = st.progress(0, text="실시간 주가 조회 중...")
        results, alerts, holds = [], [], []
        total_value_usd = total_cost_usd = 0.0

        for i, row in enumerate(valid_rows):
            ticker = row["ticker"]
            input_currency = row.get("currency", "USD")
            progress.progress((i+1)/len(valid_rows), text=f"주가 조회 중... {ticker}")
            data = fetch_stock_data(ticker)
            if not data or "error" in data:
                results.append({**row, "error": data.get("error", "조회 실패"), "current": None})
                continue

            current = data["current"]
            market_currency = data.get("currency", input_currency)
            avg_p, shares = row["avg_price"], row["shares"]
            gain_pct = (current - avg_p) / avg_p * 100 if avg_p > 0 else 0
            mkt_val, cost, pnl = current*shares, avg_p*shares, (current-avg_p)*shares

            if market_currency == "KRW":
                mkt_val_usd, cost_usd = mkt_val/usd_krw, cost/usd_krw
            else:
                mkt_val_usd, cost_usd = mkt_val, cost

            total_value_usd += mkt_val_usd
            total_cost_usd  += cost_usd

            zone_label, zone_css, zone_action = get_zone(gain_pct)
            sig_52w = get_52w_signal(data["pos_52w"])

            entry = {
                "ticker": ticker, "name": data.get("name", ticker),
                "shares": shares, "avg_price": avg_p, "current": current,
                "gain_pct": gain_pct, "mkt_val": mkt_val, "cost": cost, "pnl": pnl,
                "currency": market_currency, "pos_52w": data["pos_52w"],
                "low_52w": data["low_52w"], "high_52w": data["high_52w"],
                "vol_ratio": data["vol_ratio"], "zone_label": zone_label,
                "zone_css": zone_css, "zone_action": zone_action,
                "sig_52w": sig_52w, "stop_price": avg_p * 0.92, "mkt_val_usd": mkt_val_usd,
            }
            results.append(entry)
            if "손절" in zone_label or "경계" in zone_label or "익절" in zone_label:
                alerts.append(entry)
            else:
                holds.append(entry)

        progress.empty()

        total_gain_pct = (total_value_usd-total_cost_usd)/total_cost_usd*100 if total_cost_usd > 0 else 0
        pnl_sign = "+" if total_value_usd >= total_cost_usd else ""

        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 평가금 (USD환산)", f"${total_value_usd:,.0f}")
        m2.metric("총 원금 (USD환산)", f"${total_cost_usd:,.0f}")
        m3.metric("총 손익", f"{pnl_sign}${total_value_usd-total_cost_usd:,.0f}",
                  delta=f"{pnl_sign}{total_gain_pct:.2f}%")
        m4.metric("포트폴리오 존", zone_name)
        st.markdown("---")

        st.subheader("📋 종목별 현황")
        df_rows = []
        for r in results:
            curr = r.get("currency", "USD")
            if r.get("current") is None:
                df_rows.append({"종목": r["ticker"], "종목명": "-", "현재가": "조회실패",
                                 "수익률": "-", "평가금": "-", "손익": "-", "52주위치": "-", "상태": "❌"})
            else:
                df_rows.append({
                    "종목": r["ticker"], "종목명": r["name"][:15],
                    "현재가": format_price(r["current"], curr),
                    "수익률": f"{r['gain_pct']:+.2f}%",
                    "평가금": format_value(r["mkt_val"], curr),
                    "손익": format_value(r["pnl"], curr),
                    "52주위치": f"{r['pos_52w']:.0f}%", "상태": r["zone_label"],
                })
        st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)

        if alerts:
            st.subheader("🎯 즉시 액션 필요 종목")
            for r in alerts:
                curr = r.get("currency", "USD")
                st.markdown(f"""<div class="{r['zone_css']}">
                <strong>{r['zone_label']} | {r['ticker']} — {r['name']}</strong><br>
                현재가 <strong>{format_price(r['current'], curr)}</strong> |
                평균단가 {format_price(r['avg_price'], curr)} |
                수익률 <strong>{r['gain_pct']:+.2f}%</strong> |
                평가금 {format_value(r['mkt_val'], curr)} (손익 {format_value(r['pnl'], curr)})<br>
                손절가(-8%) <strong>{format_price(r['stop_price'], curr)}</strong> |
                52주 {r['pos_52w']:.0f}% {r['sig_52w']}<br>
                💡 <em>{r['zone_action']}</em>
                </div>""", unsafe_allow_html=True)

        if holds:
            with st.expander(f"✅ 정상 홀딩 종목 ({len(holds)}개)", expanded=False):
                for r in holds:
                    curr = r.get("currency", "USD")
                    st.markdown(f"""<div class="zone-hold">
                    <strong>{r['ticker']} — {r['name']}</strong> |
                    {format_price(r['current'], curr)} | {r['gain_pct']:+.2f}% |
                    52주 {r['pos_52w']:.0f}% | {r['sig_52w']}
                    </div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("📈 TradingView 차트")
        valid_results = [r for r in results if r.get("current") is not None]
        if valid_results:
            chart_ticker = st.selectbox("차트 볼 종목 선택",
                options=[r["ticker"] for r in valid_results],
                format_func=lambda t: next(
                    (f"{r['ticker']} — {r['name']}" for r in valid_results if r["ticker"] == t), t))
            if chart_ticker:
                show_tradingview_chart(chart_ticker, height=450)

        st.markdown("---")
        st.subheader("🤖 AI 종합 분석")
        with st.spinner("Claude AI가 포트폴리오를 분석하고 있습니다..."):
            summary_lines = []
            for r in results:
                if r.get("current"):
                    curr = r.get("currency", "USD")
                    summary_lines.append(
                        f"- {r['ticker']} ({r['name']}, {curr}): "
                        f"현재 {format_price(r['current'], curr)}, "
                        f"평균단가 {format_price(r['avg_price'], curr)}, "
                        f"수익률 {r['gain_pct']:+.2f}%, "
                        f"평가금 {format_value(r['mkt_val'], curr)}, "
                        f"상태: {r['zone_label']}"
                    )
            portfolio_summary = "\n".join(summary_lines)
            portfolio_summary += f"\n\n총 평가금(USD환산): ${total_value_usd:,.0f} | 총 손익: {total_gain_pct:+.2f}% | USD/KRW: {usd_krw:,.0f}"
            ai_report = analyze_with_claude(api_key, portfolio_summary, cash_pct, zone_name)

        st.markdown(f'<div class="report-box">{ai_report}</div>', unsafe_allow_html=True)
        st.caption(f"분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 주가: yfinance (5분 캐시)")

        with st.expander("⚠️ 면책 조항"):
            st.markdown("""
            본 서비스는 개인적인 포트폴리오 현황 파악을 위한 참고 도구입니다.
            투자 조언이나 매수/매도 권유를 목적으로 하지 않습니다.
            모든 투자 결정과 그 결과에 대한 책임은 투자자 본인에게 있습니다.
            """)


if __name__ == "__main__":
    main()
