"""
자산제곱 AI 포트폴리오 분석기
================================
자산제곱 5존 시스템 기반 포트폴리오 분석 웹앱
yfinance / 네이버 금융 실시간 주가 + Claude AI 분석 + 이미지 파싱

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

@st.cache_data(ttl=1800)  # 30분 캐시
def fetch_strategy_context() -> str:
    """GitHub에서 최신 전략 컨텍스트 로드"""
    try:
        import requests
        url = "https://raw.githubusercontent.com/kkyoungh8/assetx2-analyzer/main/strategy/current_strategy.md"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return ""


def compress_strategy_context(ctx: str) -> str:
    """전략 컨텍스트를 채팅용 압축 버전으로 변환 (~400토큰)
    원본 전체 대신 핵심 섹션만 추출해 채팅 토큰 비용 절감
    """
    if not ctx:
        return ""
    lines = ctx.split('\n')
    keep = []
    include = False
    # 상세 분석 텍스트 덤프 섹션은 제외, 전략/판단 섹션만 유지
    skip_headers = {"## 📄 분석된 리포트", "## 📋 분석 내용"}
    for line in lines:
        if line.startswith('## '):
            include = line.strip() not in skip_headers
        if include or line.startswith('#'):
            keep.append(line)
    compressed = '\n'.join(keep).strip()
    # 최대 2000자 (약 500토큰) 제한
    return compressed[:2000] if len(compressed) > 2000 else compressed


@st.cache_data(ttl=60)  # 1분 캐시 (환율은 빠른 반영 필요)
def get_exchange_rates() -> dict:
    """환율 조회 - 네이버 금융 FX API (USD/KRW, JPY/KRW)
    전일 대비 변동폭·방향까지 반환
    """
    def _fetch_naver_fx(code: str) -> dict:
        import requests
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://m.stock.naver.com",
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        d = resp.json()
        def f(v, default=0.0):
            try: return float(str(v).replace(",", "").replace("%", "").strip())
            except: return default
        rate   = f(d.get("closePrice", 0))
        change = f(d.get("compareToPreviousClosePrice", 0))
        chg_pct = f(d.get("fluctuationsRatio", 0))
        return {"rate": rate, "change": change, "change_pct": chg_pct}

    result = {
        "usd": {"rate": 1350.0, "change": 0.0, "change_pct": 0.0},
        "jpy": {"rate": 9.5,    "change": 0.0, "change_pct": 0.0},
    }
    try:
        result["usd"] = _fetch_naver_fx("FX_USDKRW")
    except Exception:
        # fallback: yfinance
        try:
            hist = yf.Ticker("USDKRW=X").history(period="2d")
            if not hist.empty:
                rate  = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else rate
                chg   = rate - prev
                result["usd"] = {"rate": rate, "change": chg, "change_pct": chg/prev*100 if prev else 0}
        except Exception:
            pass
    try:
        result["jpy"] = _fetch_naver_fx("FX_JPYKRW")
    except Exception:
        pass
    return result


def get_usd_krw_rate() -> float:
    """USD/KRW 단순 환율값 (하위 호환용)"""
    return get_exchange_rates()["usd"]["rate"]


def is_korean(text: str) -> bool:
    """한글 포함 여부 확인"""
    return bool(re.search(r'[가-힣]', text))


@st.cache_data(ttl=3600)
def search_naver_stock(query: str) -> list:
    """네이버 금융 자동완성 - 한글 종목명 검색 (1시간 캐시)"""
    try:
        import requests
        url = "https://ac.finance.naver.com/query.naver"
        params = {"query": query, "target": "stock,etf"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://finance.naver.com",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        text = resp.text.strip()

        if text.startswith("[[") or text.startswith("[\""):
            data = json.loads(text)
        else:
            m = re.search(r'\[\[.*?\]\]', text, re.DOTALL)
            data = json.loads(m.group()) if m else []

        results = []
        for item in data:
            if len(item) < 2:
                continue
            name = str(item[0])
            code = str(item[1]).zfill(6)
            results.append({
                "symbol": f"{code}.KS",
                "code": code,
                "name": name,
                "exchange": "KRX",
                "type": "주식",
            })
        return results[:6]
    except Exception:
        return []


@st.cache_data(ttl=60)  # 1분 캐시 (실시간 시세)
def fetch_naver_stock_data(code: str) -> dict:
    """네이버 금융 모바일 API - 실시간 시세 + 52주 고저 + PER/PBR"""
    try:
        import requests
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://m.stock.naver.com",
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        d = resp.json()

        def to_float(val, default=0.0):
            try:
                return float(str(val).replace(",", "").replace("%", "").strip())
            except Exception:
                return default

        current  = to_float(d.get("closePrice", 0))
        high_52w = to_float(d.get("fiftyTwoWeekHighPrice", current * 1.3))
        low_52w  = to_float(d.get("fiftyTwoWeekLowPrice",  current * 0.7))
        volume   = int(to_float(d.get("accumulatedTradingVolume", 0)))

        pos_52w = 0.0
        if high_52w > low_52w:
            pos_52w = round((current - low_52w) / (high_52w - low_52w) * 100, 1)

        return {
            "name":       d.get("stockName", code),
            "current":    current,
            "low_52w":    low_52w,
            "high_52w":   high_52w,
            "pos_52w":    pos_52w,
            "volume":     volume,
            "avg_volume": volume,
            "vol_ratio":  1.0,
            "currency":   "KRW",
            "per":        to_float(d.get("per",  0)),
            "pbr":        to_float(d.get("pbr",  0)),
        }
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=3600)
def search_ticker_by_name(query: str) -> list:
    """종목명 → 티커 검색. 한글이면 네이버, 영문이면 Yahoo Finance 사용."""
    if is_korean(query):
        return search_naver_stock(query)
    try:
        import requests
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {
            "q": query, "lang": "en-US", "region": "US",
            "quotesCount": 8, "newsCount": 0,
            "enableFuzzyQuery": False, "quotesQueryId": "tss_match_phrase_query",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        return [
            {
                "symbol": q.get("symbol", ""),
                "name":   q.get("longname") or q.get("shortname") or q.get("symbol", ""),
                "exchange": q.get("exchDisp", q.get("exchange", "")),
                "type":   q.get("typeDisp", "Stock"),
            }
            for q in resp.json().get("quotes", [])
            if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF")
        ]
    except Exception:
        return []


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
    """실시간 주가 조회. 한국(.KS/.KQ) → 네이버, 미국 → yfinance"""
    t = ticker.upper()

    # ── 한국 주식: 네이버 금융 API ──────────────────────────
    if t.endswith(".KS") or t.endswith(".KQ"):
        code = t[:-3]
        result = fetch_naver_stock_data(code)
        if "error" not in result:
            return result

    # ── 미국 주식 (또는 네이버 실패 fallback): yfinance ────
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        hist_1d = stock.history(period="1d")
        if hist_1d.empty:
            hist_1d = stock.history(period="5d")
        if hist_1d.empty:
            return {"error": f"{ticker} 데이터를 찾을 수 없습니다. 티커를 확인해주세요."}

        hist_1y = stock.history(period="1y")
        current   = float(hist_1d["Close"].iloc[-1])
        low_52w   = float(hist_1y["Low"].min())  if not hist_1y.empty else current * 0.7
        high_52w  = float(hist_1y["High"].max()) if not hist_1y.empty else current * 1.3
        volume    = int(hist_1d["Volume"].iloc[-1]) if not hist_1d.empty else 0
        avg_volume = int(info.get("averageVolume", 0))
        name      = info.get("longName") or info.get("shortName") or ticker

        pos_52w = 0.0
        if high_52w > low_52w:
            pos_52w = round((current - low_52w) / (high_52w - low_52w) * 100, 1)

        return {
            "name":       name,
            "current":    current,
            "low_52w":    low_52w,
            "high_52w":   high_52w,
            "volume":     volume,
            "avg_volume": avg_volume,
            "pos_52w":    pos_52w,
            "vol_ratio":  round(volume / avg_volume, 2) if avg_volume > 0 else 1.0,
            "currency":   info.get("currency", "USD"),
            "per":        0.0,
            "pbr":        0.0,
        }
    except Exception as e:
        return {"error": str(e)}


# ── 이미지 → 포트폴리오 파싱 ────────────────────────────────

def parse_portfolio_from_image(api_key: str, image_bytes: bytes, media_type: str) -> list:
    """Claude Vision으로 보유종목 스크린샷 → 포트폴리오 자동 파싱
    한국 증권사 컬럼명 매핑 강화 + 파싱 결과를 검수 테이블로 분리
    """
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
                        "text": """이 이미지는 한국 또는 미국 주식 증권사 앱의 보유종목 화면입니다.

보유종목 정보를 추출해주세요. 반드시 JSON 배열로만 답변하세요 (다른 설명 없이):
[
  {"ticker": "종목코드", "shares": 보유수량숫자, "avg_price": 평균단가숫자, "currency": "KRW 또는 USD"},
  ...
]

【한국 증권사 컬럼명 매핑 - 증권사마다 이름이 다름에 주의】
수량 컬럼: 보유수량 / 수량 / 잔고수량 / 보유주수 / 잔량 / 보유 → shares
단가 컬럼: 평균단가 / 평균매입가 / 매입단가 / 평균매수가 / 매수평균가 / 평균단가(원) → avg_price
코드 컬럼: 종목코드 / 단축코드 / 코드 → ticker (6자리 숫자)

【처리 규칙】
- 한국 주식(6자리 숫자 코드): 숫자만 입력 (005930 등) — 앱이 자동으로 .KS 추가
- 종목명만 있고 코드 없음: 종목명 그대로 ticker에 입력 (예: "삼성전자")
- 한국 주식 단가 = 원화 → "KRW" / 미국 주식 단가 = 달러 → "USD"
- 미국 주식: 영문 티커 그대로 (AAPL, NVDA, AVGO 등)
- 숫자의 콤마·기호 제거 (1,234,567 → 1234567 / ▲▼ +- 제거)
- 수량 또는 단가가 전혀 식별 불가한 종목은 제외
- ETF도 동일하게 처리""",
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
                        "ticker": str(item["ticker"]).strip(),
                        "shares": float(item["shares"]),
                        "avg_price": float(item["avg_price"]),
                        "currency": item.get("currency", "KRW"),
                    })
            return result
        return []
    except Exception as e:
        st.error(f"이미지 파싱 오류: {e}")
        return []


# ── Claude AI 분석 ───────────────────────────────────────────

def analyze_with_claude(api_key: str, portfolio_summary: str, cash_pct: float, zone_name: str) -> str:
    """Claude API로 포트폴리오 종합 분석 (자산제곱 전략 컨텍스트 반영)"""
    client = anthropic.Anthropic(api_key=api_key)

    strategy_ctx = fetch_strategy_context()
    strategy_section = f"""
## 자산제곱 현재 전략 컨텍스트 (최신 리포트 기반)
{strategy_ctx}
""" if strategy_ctx else ""

    prompt = f"""당신은 자산제곱 프레임워크를 사용하는 전문 포트폴리오 애널리스트입니다.
{strategy_section}
## 현재 포트폴리오 현황
{portfolio_summary}

## 포트폴리오 존 상태
- 현금 비중: {cash_pct:.1f}%
- 주식 비중: {100 - cash_pct:.1f}%
- 포트폴리오 존: {zone_name}

## 분석 요청
위 포트폴리오를 자산제곱 5존 프레임워크와 현재 전략 컨텍스트를 함께 반영해서 분석해주세요.

다음 순서로 작성해주세요:
1. **📊 전체 평가** (현재 시장 국면 대비 이 포트폴리오의 포지션)
2. **🚨 즉시 액션 필요** (손절/익절 필요 종목, 없으면 "없음")
3. **💡 핵심 인사이트** (현재 전략 컨텍스트 기반 2~3가지)
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


def chat_with_claude(api_key: str, messages: list, compressed_ctx: str) -> str:
    """전략 딥다이브 채팅 - Haiku 모델, 슬라이딩 윈도우 6턴
    - claude-haiku: Sonnet 대비 약 20배 저렴
    - 압축 컨텍스트: 전체 전략 문서 대신 핵심 ~400토큰만 사용
    - 슬라이딩 윈도우: 최근 6개 메시지만 전달
    """
    client = anthropic.Anthropic(api_key=api_key)

    ctx_block = f"\n## 현재 전략 컨텍스트\n{compressed_ctx}" if compressed_ctx else ""

    system = f"""당신은 자산제곱 프레임워크 기반 투자 전략 어시스턴트입니다.
사용자의 투자 전략과 시장 판단에 대해 깊이 있는 대화를 제공합니다.
{ctx_block}

답변 원칙:
- 한국어로 간결하게 (3~5문장 기본, 상세 요청 시 확장)
- 자산제곱 5존 프레임워크 기반으로 판단
- 투자 조언이 아닌 프레임워크 기반 분석 관점으로 답변"""

    # 슬라이딩 윈도우: 최근 6개 메시지만 (3턴 대화)
    windowed = messages[-6:] if len(messages) > 6 else messages

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=windowed,
        )
        return resp.content[0].text
    except anthropic.AuthenticationError:
        return "❌ API 키가 올바르지 않습니다."
    except Exception as e:
        return f"❌ 오류: {str(e)}"


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

    # ── 사이드바 ────────────────────────────────────────────
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
        st.caption("💱 환율 모니터링 (1분 캐시)")
        fx = get_exchange_rates()
        usd = fx["usd"]
        jpy = fx["jpy"]
        usd_krw = usd["rate"]

        # USD/KRW
        usd_arrow = "▲" if usd["change"] > 0 else ("▼" if usd["change"] < 0 else "—")
        usd_color = "🔴" if usd["change"] > 0 else ("🔵" if usd["change"] < 0 else "⚪")
        usd_sign  = "+" if usd["change"] > 0 else ""
        st.markdown(
            f"**USD/KRW** &nbsp; ₩{usd_krw:,.1f} &nbsp; "
            f"{usd_color} {usd_arrow} {usd_sign}{usd['change']:,.1f} ({usd_sign}{usd['change_pct']:.2f}%)",
            unsafe_allow_html=True,
        )

        # JPY/KRW (100엔 기준)
        if jpy["rate"] > 0:
            jpy_arrow = "▲" if jpy["change"] > 0 else ("▼" if jpy["change"] < 0 else "—")
            jpy_color = "🔴" if jpy["change"] > 0 else ("🔵" if jpy["change"] < 0 else "⚪")
            jpy_sign  = "+" if jpy["change"] > 0 else ""
            st.markdown(
                f"**JPY/KRW** &nbsp; ₩{jpy['rate']:,.2f} &nbsp; "
                f"{jpy_color} {jpy_arrow} {jpy_sign}{jpy['change']:,.2f} ({jpy_sign}{jpy['change_pct']:.2f}%)",
                unsafe_allow_html=True,
            )

        st.divider()
        ctx = fetch_strategy_context()
        if ctx:
            m = re.search(r'최종 업데이트:\s*([\d-]+)', ctx)
            updated = m.group(1) if m else "날짜 미상"
            st.success(f"📋 전략 컨텍스트 로드됨\n\n업데이트: {updated}", icon="✅")
        else:
            st.warning("전략 컨텍스트 없음", icon="⚠️")

    # ── 탭 구성 ─────────────────────────────────────────────
    tab_analysis, tab_chat = st.tabs(["📊 포트폴리오 분석", "💬 전략 딥다이브"])

    # ════════════════════════════════════════════════════════
    # 탭 1: 포트폴리오 분석
    # ════════════════════════════════════════════════════════
    with tab_analysis:

        st.subheader("📋 보유 종목 입력")
        st.caption("티커: 미국주식(AVGO, AAPL), 한국주식(005930.KS 또는 숫자 6자리 자동변환)")

        if "portfolio" not in st.session_state:
            st.session_state.portfolio = [
                {"ticker": "AVGO",      "shares": 10.0, "avg_price": 333.77, "currency": "USD"},
                {"ticker": "GEV",       "shares":  5.0, "avg_price": 652.63, "currency": "USD"},
                {"ticker": "005930.KS", "shares": 10.0, "avg_price": 75000,  "currency": "KRW"},
            ]

        # ── 종목명 검색 ──────────────────────────────────────
        with st.expander("🔍 종목명으로 검색해서 추가", expanded=False):
            col_q, col_btn = st.columns([4, 1])
            with col_q:
                search_query = st.text_input(
                    "종목명", placeholder="예: 삼성전자, SK하이닉스, NVIDIA, Apple",
                    label_visibility="collapsed", key="search_query"
                )
            with col_btn:
                st.write("")
                search_clicked = st.button("검색", key="search_btn", use_container_width=True)

            if search_clicked and search_query.strip():
                with st.spinner("검색 중..."):
                    results = search_ticker_by_name(search_query.strip())
                st.session_state["search_results"] = results
                if not results:
                    st.warning("검색 결과가 없습니다. 다른 검색어를 입력해보세요.")

            for idx, r in enumerate(st.session_state.get("search_results", [])[:6]):
                col_info, col_add = st.columns([5, 1])
                with col_info:
                    st.markdown(f"**{r['symbol']}** — {r['name']}  `{r['exchange']}` `{r['type']}`")
                with col_add:
                    if st.button("추가", key=f"add_sr_{idx}", use_container_width=True):
                        ticker = normalize_ticker(r["symbol"])
                        if ticker not in [row["ticker"] for row in st.session_state.portfolio]:
                            st.session_state.portfolio.append({
                                "ticker": ticker,
                                "shares": 1.0,
                                "avg_price": 0.0,
                                "currency": detect_currency(ticker),
                            })
                            st.session_state["search_results"] = []
                            st.rerun()
                        else:
                            st.info(f"{ticker} 이미 추가됨")

        # ── 이미지 업로드 + 검수 UI ──────────────────────────
        with st.expander("📸 보유종목 스크린샷으로 자동 추가", expanded=False):
            st.markdown('<div class="upload-box">', unsafe_allow_html=True)
            st.write("**증권사 앱 보유종목 화면을 캡처해서 업로드하면 자동으로 입력됩니다.**")
            st.caption("지원 형식: PNG, JPG, JPEG • Claude Vision이 종목코드·수량·단가를 자동 인식 후 검수 단계 제공")
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
                                st.session_state["parsed_preview"] = parsed
                            else:
                                st.warning("종목을 인식하지 못했습니다. 이미지를 다시 확인해주세요.")

            # ── 검수 테이블: 파싱 결과 확인·수정 후 추가 ──────
            if st.session_state.get("parsed_preview"):
                st.markdown("---")
                st.markdown("#### 📝 인식 결과를 확인하고 수정해주세요")
                st.caption("틀린 값은 직접 수정하거나 행을 삭제한 뒤 '추가' 버튼을 누르세요.")

                preview_df = pd.DataFrame(st.session_state["parsed_preview"])
                edited_df = st.data_editor(
                    preview_df,
                    column_config={
                        "ticker": st.column_config.TextColumn("티커 / 종목코드", width="medium"),
                        "shares": st.column_config.NumberColumn("수량", format="%.4f", min_value=0.0001),
                        "avg_price": st.column_config.NumberColumn("평균단가", format="%.2f", min_value=0.01),
                        "currency": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"], width="small"),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    key="preview_editor",
                )

                col_confirm, col_cancel = st.columns([1, 1])
                with col_confirm:
                    if st.button("✅ 포트폴리오에 추가", type="primary", key="confirm_parse"):
                        added = 0
                        for _, row in edited_df.iterrows():
                            ticker = normalize_ticker(str(row["ticker"]).strip())
                            if not ticker:
                                continue
                            existing = [r["ticker"] for r in st.session_state.portfolio]
                            if ticker not in existing:
                                st.session_state.portfolio.append({
                                    "ticker": ticker,
                                    "shares": float(row["shares"]),
                                    "avg_price": float(row["avg_price"]),
                                    "currency": str(row["currency"]),
                                })
                                added += 1
                        del st.session_state["parsed_preview"]
                        st.success(f"✅ {added}개 종목이 추가되었습니다.")
                        st.rerun()
                with col_cancel:
                    if st.button("❌ 취소", key="cancel_parse"):
                        del st.session_state["parsed_preview"]
                        st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)

        # ── 포트폴리오 테이블 ────────────────────────────────
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

        # ── 분석 실행 ────────────────────────────────────────
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
                    "per": data.get("per", 0.0), "pbr": data.get("pbr", 0.0),
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
                    per_str = f"{r['per']:.1f}x" if r.get("per", 0) > 0 else "-"
                    pbr_str = f"{r['pbr']:.2f}x" if r.get("pbr", 0) > 0 else "-"
                    df_rows.append({
                        "종목": r["ticker"], "종목명": r["name"][:15],
                        "현재가": format_price(r["current"], curr),
                        "수익률": f"{r['gain_pct']:+.2f}%",
                        "평가금": format_value(r["mkt_val"], curr),
                        "손익": format_value(r["pnl"], curr),
                        "52주위치": f"{r['pos_52w']:.0f}%",
                        "PER": per_str, "PBR": pbr_str,
                        "상태": r["zone_label"],
                    })
            st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)

            if alerts:
                st.subheader("🎯 즉시 액션 필요 종목")
                for r in alerts:
                    curr = r.get("currency", "USD")
                    per_pbr = ""
                    if r.get("per", 0) > 0:
                        per_pbr = f" | PER {r['per']:.1f}x · PBR {r['pbr']:.2f}x"
                    st.markdown(f"""<div class="{r['zone_css']}">
                    <strong>{r['zone_label']} | {r['ticker']} — {r['name']}</strong><br>
                    현재가 <strong>{format_price(r['current'], curr)}</strong> |
                    평균단가 {format_price(r['avg_price'], curr)} |
                    수익률 <strong>{r['gain_pct']:+.2f}%</strong> |
                    평가금 {format_value(r['mkt_val'], curr)} (손익 {format_value(r['pnl'], curr)})<br>
                    손절가(-8%) <strong>{format_price(r['stop_price'], curr)}</strong> |
                    52주 {r['pos_52w']:.0f}% {r['sig_52w']}{per_pbr}<br>
                    💡 <em>{r['zone_action']}</em>
                    </div>""", unsafe_allow_html=True)

            if holds:
                with st.expander(f"✅ 정상 홀딩 종목 ({len(holds)}개)", expanded=False):
                    for r in holds:
                        curr = r.get("currency", "USD")
                        per_pbr = f" | PER {r['per']:.1f}x · PBR {r['pbr']:.2f}x" if r.get("per", 0) > 0 else ""
                        st.markdown(f"""<div class="zone-hold">
                        <strong>{r['ticker']} — {r['name']}</strong> |
                        {format_price(r['current'], curr)} | {r['gain_pct']:+.2f}% |
                        52주 {r['pos_52w']:.0f}% | {r['sig_52w']}{per_pbr}
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
            st.caption(f"분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 주가: yfinance/네이버금융 (5분 캐시)")

            with st.expander("⚠️ 면책 조항"):
                st.markdown("""
                본 서비스는 개인적인 포트폴리오 현황 파악을 위한 참고 도구입니다.
                투자 조언이나 매수/매도 권유를 목적으로 하지 않습니다.
                모든 투자 결정과 그 결과에 대한 책임은 투자자 본인에게 있습니다.
                """)

    # ════════════════════════════════════════════════════════
    # 탭 2: 전략 딥다이브 채팅
    # ════════════════════════════════════════════════════════
    with tab_chat:
        st.subheader("💬 전략 딥다이브")
        st.caption("현재 자산제곱 전략 컨텍스트 기반으로 자유롭게 질문하세요.")

        if not api_key:
            st.warning("💡 사이드바에서 Claude API 키를 먼저 입력해주세요.")
        else:
            # 채팅 히스토리 초기화
            if "chat_messages" not in st.session_state:
                st.session_state.chat_messages = []

            # 전략 컨텍스트 상태 표시
            if ctx:
                m = re.search(r'최종 업데이트:\s*([\d-]+)', ctx)
                updated = m.group(1) if m else "날짜 미상"
                st.info(f"📋 전략 컨텍스트 기반 ({updated}) | Haiku 모델 | 최근 3턴 컨텍스트 유지")
            else:
                st.warning("⚠️ 전략 컨텍스트 없음 — 일반 자산제곱 프레임워크 기반으로 답변합니다.")

            # 추천 질문
            if not st.session_state.chat_messages:
                st.markdown("**💡 이런 질문을 해보세요:**")
                sample_qs = [
                    "5월 변동성 구간에서 현금 비중을 어떻게 조절해야 할까요?",
                    "반도체 직접 투자 vs AI 소프트웨어 인프라, 지금은 어느 쪽이 나을까요?",
                    "비트코인 클래리티 법안이 통과되면 포트폴리오에 어떤 영향이 있을까요?",
                    "케빈 워시가 연준 의장이 되면 금리 정책이 어떻게 바뀔 수 있나요?",
                ]
                cols = st.columns(2)
                for i, q in enumerate(sample_qs):
                    with cols[i % 2]:
                        if st.button(q, key=f"sample_q_{i}", use_container_width=True):
                            st.session_state.chat_messages.append({"role": "user", "content": q})
                            compressed = compress_strategy_context(ctx)
                            response = chat_with_claude(api_key, st.session_state.chat_messages, compressed)
                            st.session_state.chat_messages.append({"role": "assistant", "content": response})
                            st.rerun()

            # 대화 히스토리 렌더링
            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # 입력창
            if prompt := st.chat_input("전략에 대해 궁금한 점을 물어보세요..."):
                st.session_state.chat_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner(""):
                        compressed = compress_strategy_context(ctx)
                        response = chat_with_claude(api_key, st.session_state.chat_messages, compressed)
                    st.markdown(response)

                st.session_state.chat_messages.append({"role": "assistant", "content": response})
                st.rerun()

            # 대화 초기화 + 상태 표시
            if st.session_state.chat_messages:
                col_clear, col_info = st.columns([1, 3])
                with col_clear:
                    if st.button("🗑️ 대화 초기화", key="clear_chat"):
                        st.session_state.chat_messages = []
                        st.rerun()
                with col_info:
                    n_turns = len(st.session_state.chat_messages) // 2
                    st.caption(f"💬 {n_turns}턴 대화 중 | 최근 3턴만 전송 (토큰 절약)")


if __name__ == "__main__":
    main()
