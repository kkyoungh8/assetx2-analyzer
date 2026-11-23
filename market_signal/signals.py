"""
장세 판정기 (미국·한국 지표 체크리스트) — LLM 없이 도는 결정론적 부분.

  python3 market_signal/signals.py            # 수집 + 판정 + 리포트 출력
  python3 market_signal/signals.py --json     # 판정 결과 JSON

입력:
  - FRED CSV (공식)         : 금리·가산금리·환율·실업률·CPI·VIX·S&P500·삼의법칙·IC4WSA·NFCI
  - Yahoo chart (근사치)    : FRED보다 새 날짜가 있을 때만 VIX/S&P500/환율 보충, 코스피
  - 네이버 증권 (근사치)    : 외국인 코스피 순매매(억원)
  - market_signal/research.json : 웹검색으로만 얻는 항목(6·7·8·11·일정) — 리서치 에이전트가 채움
"""
import csv, io, json, sys, time, datetime as dt
from pathlib import Path
import urllib.request


class _Resp:
    def __init__(self, code, body):
        self.status_code, self.text = code, body

    def json(self):
        return json.loads(self.text)

HERE = Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
G, Y, R, U = "🟢", "🟡", "🔴", "⚪"


# ───────────────────────── 수집 ─────────────────────────
def _get(url, tries=3, headers=UA):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    return _Resp(200, r.read().decode("utf-8", "replace"))
        except Exception:  # 표준 라이브러리만 사용(새 세션에 requests 설치 불필요)
            pass
        time.sleep(2 * (i + 1))
    return None


def fred(sid, start="2024-01-01"):
    r = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}", headers={"User-Agent": "curl/8.5.0"})  # FRED는 브라우저 UA를 지연시킴
    out = []
    if r:
        for row in list(csv.reader(io.StringIO(r.text)))[1:]:
            if len(row) == 2 and row[1] not in ("", "."):
                out.append((row[0], float(row[1])))
    return out  # [(YYYY-MM-DD, value)]


def yahoo(sym, rng="2y"):
    r = _get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d")
    out = []
    try:
        res = r.json()["chart"]["result"][0]
        off = res["meta"].get("gmtoffset", 0)
        for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
            if c is not None:
                out.append((dt.datetime.fromtimestamp(t + off, dt.timezone.utc).strftime("%Y-%m-%d"), float(c)))
    except Exception:
        pass
    # 같은 날짜 중복 제거(마지막 값 유지)
    d = dict(out)
    return sorted(d.items())


def us_cutoff():
    """아직 마감 안 된 미국 거래일(장중 값)은 제외: 미 동부 16:30 이전이면 오늘 날짜 제외."""
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    return now.date().isoformat() if now.hour * 60 + now.minute >= 16 * 60 + 30 else (now.date() - dt.timedelta(days=1)).isoformat()


def merge(official, approx):
    """FRED 값을 기본으로, FRED 마지막 날짜 이후~최근 미국장 마감일까지의 Yahoo 값만 덧붙임."""
    last = official[-1][0] if official else "0000"
    cut = us_cutoff()
    tail = [(d, v) for d, v in approx if last < d <= cut]
    series = official + tail
    src = "FRED" if not tail else f"FRED+Yahoo(근사치, {tail[0][0]}~)"
    if not official:
        src = "Yahoo(근사치)"
    return series, src


def naver_foreign(n=25):
    """외국인 코스피 순매매(억원), 최근 n거래일. 최신이 앞."""
    out, d = [], dt.date.today()
    tried = 0
    while len(out) < n and tried < n * 2:
        if d.weekday() < 5:
            r = _get(f"https://m.stock.naver.com/api/index/KOSPI/trend?bizdate={d:%Y%m%d}", tries=2)
            try:
                j = r.json()
                if j.get("bizdate") == f"{d:%Y%m%d}" and j.get("foreignValue"):
                    out.append((d.isoformat(), int(j["foreignValue"].replace(",", "").replace("+", ""))))
            except Exception:
                pass
        d -= dt.timedelta(days=1)
        tried += 1
    # 같은 값이 연속으로 오면(휴장일에 직전값 반환) 제거
    dedup = []
    for x in out:
        if not dedup or x[1] != dedup[-1][1]:
            dedup.append(x)
    return dedup


def collect():
    s = {k: fred(k) for k in ["DGS10", "DGS2", "DFEDTARU", "BAMLH0A0HYM2", "DEXJPUS", "DEXKOUS",
                                "VIXCLS", "SP500", "SAHMREALTIME", "IC4WSA", "NFCI"]}
    s["UNRATE"] = fred("UNRATE", "2025-01-01")
    s["CPILFESL"] = fred("CPILFESL", "2025-01-01")
    src = {k: "FRED" for k in s}
    for k, sym in [("VIXCLS", "%5EVIX"), ("SP500", "%5EGSPC"), ("DEXJPUS", "JPY%3DX"), ("DEXKOUS", "KRW%3DX")]:
        s[k], src[k] = merge(s[k], yahoo(sym))
    s["KOSPI"], src["KOSPI"] = yahoo("%5EKS11"), "Yahoo(근사치)"
    s["FOREIGN"], src["FOREIGN"] = naver_foreign(), "네이버증권(근사치)"
    s["_src"] = src
    return s


# ───────────────────────── 계산 도우미 ─────────────────────────
def last(series):
    return series[-1] if series else (None, None)


def value_on_or_before(series, date):
    v = None
    for d, x in series:
        if d <= date:
            v = (d, x)
    return v


def ma(series, n):
    return sum(v for _, v in series[-n:]) / n if len(series) >= n else None


def streak(series, cond):
    """끝에서부터 cond 를 만족하는 연속 관측 수."""
    c = 0
    for _, v in reversed(series):
        if cond(v):
            c += 1
        else:
            break
    return c


def ago(date, days):
    return (dt.date.fromisoformat(date) - dt.timedelta(days=days)).isoformat()


def f2(x, n=2):
    return "확인 불가" if x is None else f"{x:.{n}f}"


# ───────────────────────── 판정 ─────────────────────────
def evaluate(s, rs):
    sig, aux, notes = {}, {}, []

    # 1. 10년물
    d, v = last(s["DGS10"])
    n5 = streak(s["DGS10"], lambda x: x > 5)
    sig[1] = dict(name="미국 10년물", color=(R if v > 5 else G) if v else U,
                  text=f"{f2(v)}% ({d}, FRED) · 5% 위 {n5}거래일 연속", v=v, over5=n5)

    # 2. 2년물 − 기준금리 상단
    d2, v2 = last(s["DGS2"]); df_, ff = last(s["DFEDTARU"])
    gap = None if v2 is None or ff is None else v2 - ff
    sig[2] = dict(name="2년물−기준금리상단", color=U if gap is None else (R if gap > 0 else G),
                  text=f"{f2(v2)}% − {f2(ff)}% = {gap:+.2f}%p ({d2}/{df_}, FRED)" if gap is not None else "확인 불가",
                  gap=gap, cpi_ok=None)

    # 3. 하이일드
    hy = s["BAMLH0A0HYM2"]; dh, h = last(hy)
    six = [x for x in hy if x[0] >= ago(dh, 182)] if dh else []
    if six:
        mn = min(six, key=lambda x: x[1]); mx = max(six, key=lambda x: x[1])
        rise = h - mn[1]
        col = R if rise >= 0.5 else Y if rise >= 0.3 else G
        sig[3] = dict(name="하이일드 가산금리", color=col, v=h, rise=rise, peak=mx[1], low=mn[1],
                      text=f"{h:.2f}%p ({dh}, FRED) · 6개월 최저 {mn[1]:.2f}({mn[0]}) 대비 {rise:+.2f}%p · 최근 고점 {mx[1]:.2f}({mx[0]})")
    else:
        sig[3] = dict(name="하이일드 가산금리", color=U, text="확인 불가", v=None, rise=None, peak=None)

    # 4. USD/JPY 1개월 엔 절상률
    jp = s["DEXJPUS"]; dj, j = last(jp)
    p = value_on_or_before(jp, ago(dj, 30)) if dj else None
    if p:
        yen = (p[1] / j - 1) * 100  # +면 엔 절상
        sig[4] = dict(name="USD/JPY", color=R if yen >= 5 else Y if yen >= 3 else G,
                      text=f"{j:.2f} ({dj}) vs {p[1]:.2f} ({p[0]}) → 엔 {yen:+.1f}% · {s['_src']['DEXJPUS']}")
    else:
        sig[4] = dict(name="USD/JPY", color=U, text="확인 불가")

    # 5. 실업률
    un = s["UNRATE"]
    if len(un) >= 2:
        (dp, pv), (du, uv) = un[-2], un[-1]
        aug = dict(un).get("2026-08-01")
        base = 4.1
        if aug is not None and abs(aug - base) > 1e-9:
            notes.append(f"FRED 2026-08 실업률은 {aug}%로, 요청 기준값 4.1%와 다름 — 규칙대로 4.1% 사용")
        col = R if uv - base >= 0.3 - 1e-9 else Y if uv > pv else G
        sig[5] = dict(name="미국 실업률", color=col,
                      text=f"{uv}% ({du[:7]}, FRED) · 직전 {pv}% ({dp[:7]}) · 8월 4.1% 대비 {uv-base:+.1f}%p")
    else:
        sig[5] = dict(name="미국 실업률", color=U, text="확인 불가")

    # 10. 근원 CPI 전월비 (BLS 발표처럼 소수 1자리 반올림으로 판정)
    c = s["CPILFESL"]
    core = None
    if len(c) >= 2:
        core_raw = (c[-1][1] / c[-2][1] - 1) * 100
        core = round(core_raw, 1)
        col = R if core >= 0.3 else G if core < 0.2 else Y
        sig[10] = dict(name="근원 CPI 전월비", color=col,
                       text=f"{core:.1f}% (원값 {core_raw:.3f}%, {c[-1][0][:7]}분, FRED CPILFESL 계절조정)")
    else:
        sig[10] = dict(name="근원 CPI 전월비", color=U, text="확인 불가")

    # 9. 외국인 순매매
    fo = s["FOREIGN"]  # 최신이 앞
    if fo:
        def run(sign):
            k = 0
            for _, x in fo:
                if (x < 0) == (sign < 0) and x != 0:
                    k += 1
                else:
                    break
            return k
        sell, buy = run(-1), run(+1)
        cum20 = sum(x for _, x in fo[:20])
        big = sell >= 5 or cum20 <= -50000  # ※ '대규모 지속' 수치 기준은 임의 설정(추론)
        sig[9] = dict(name="외국인 코스피 순매매", color=Y if big else G, buy=buy,
                      text=f"{fo[0][0]} {fo[0][1]:+,}억 · 연속 순매도 {sell}일 / 연속 순매수 {buy}일 · 최근 {min(20,len(fo))}일 누적 {cum20:+,}억 (네이버, 근사치)")
    else:
        sig[9] = dict(name="외국인 코스피 순매매", color=U, text="확인 불가", buy=0)

    # 6·7·8·11 — research.json (웹검색, 근사치)
    def rget(k):
        """research 항목의 date 가 14일보다 오래되면 판정에는 쓰지 않음(표시만)."""
        x = dict(rs.get(k) or {})
        d = x.get("date")
        if d and d < ago(dt.date.today().isoformat(), 14):
            notes.append(f"{k}: 기준일 {d} 자료가 14일 넘게 지나 판정에서 제외(⚪)")
            for key in ("samsung_3m_pct", "hynix_3m_pct", "pct", "direction", "growth_pct"):
                x.pop(key, None)
        return x
    r6 = rget("memory_eps")
    revs = [x for x in [r6.get("samsung_3m_pct"), r6.get("hynix_3m_pct")] if x is not None]
    sig[6] = dict(name="삼성전자·SK하이닉스 이익 컨센서스", color=U if not revs else (R if min(revs) < -5 else G),
                  text=r6.get("text", "확인 불가"))
    r7 = rget("breadth200")
    b = r7.get("pct")
    sig[7] = dict(name="S&P500 200일선 위 비율", color=U if b is None else (R if b < 60 else G),
                  text=r7.get("text", "확인 불가"), v=b)
    r8 = rget("mag7_eps")
    dirn = r8.get("direction")  # up / flat / down
    sig[8] = dict(name="M7 이익 전망", color=U if not dirn else (R if dirn == "down" else G),
                  text=r8.get("text", "확인 불가"))
    r11 = rget("capex")
    g = {k: v for k, v in (r11.get("growth_pct") or {}).items() if v is not None}
    below = [k for k, v in g.items() if v < 20]
    sig[11] = dict(name="빅테크 내년 설비투자 가이던스", color=U if not g else (R if below else G),
                   text=r11.get("text", "확인 불가"), below=len(below))

    # ── 보조지표
    dv, vix = last(s["VIXCLS"]); ds, spx = last(s["SP500"])
    m50, m200 = ma(s["SP500"], 50), ma(s["SP500"], 200)
    sp = s["SP500"]
    below200 = 0
    for i in range(len(sp) - 1, 199, -1):
        if sp[i][1] < sum(x for _, x in sp[i - 199:i + 1]) / 200:
            below200 += 1
        else:
            break
    above200 = 0
    for i in range(len(sp) - 1, 199, -1):
        if sp[i][1] > sum(x for _, x in sp[i - 199:i + 1]) / 200:
            above200 += 1
        else:
            break
    dsa, sahm = last(s["SAHMREALTIME"]); dic, ic = last(s["IC4WSA"]); dn, nfci = last(s["NFCI"])
    kr = s["DEXKOUS"]; dk, k = last(kr); kp = value_on_or_before(kr, ago(dk, 30)) if dk else None
    krw1m = (k / kp[1] - 1) * 100 if kp else None
    ks = s["KOSPI"]; dks, kos = last(ks); kma = ma(ks, 200)
    aux.update(vix=vix, vix_d=dv, spx=spx, spx_d=ds, m50=m50, m200=m200, below200=below200, above200=above200,
               sahm=sahm, sahm_d=dsa, ic=ic, ic_d=dic, nfci=nfci, nfci_d=dn, krw=k, krw_d=dk, krw1m=krw1m,
               kospi=kos, kospi_d=dks, kospi200=kma,
               vix25=streak(s["VIXCLS"], lambda x: x >= 25), vix30=streak(s["VIXCLS"], lambda x: x >= 30),
               vixlt25=streak(s["VIXCLS"], lambda x: x < 25))

    # ── 악화 신호(a~h)
    hyv, rise, peak = sig[3].get("v"), sig[3].get("rise"), sig[3].get("peak")
    kospi_below = kos is not None and kma is not None and kos < kma
    W = {
        "a": None if hyv is None else (hyv >= 3.5 or rise >= 1.0),
        "b": aux["vix25"] >= 2,
        "c": below200 >= 3,
        "d": None if core is None else core >= 0.3,
        "e": sig[1].get("over5", 0) >= 10,
        "f": None if not g else len(below) >= 2,
        "g": (sahm is not None and sahm >= 0.3) or (ic is not None and ic >= 250000),
        "h": None if krw1m is None else (kospi_below and krw1m >= 5),
    }
    # ── 위험 신호(①~⑤)
    D = {
        "①": None if hyv is None else (hyv >= 4.0 or rise >= 1.5),
        "②": aux["vix30"] >= 3,
        "③": (m50 is not None and m200 is not None and m50 < m200) or (spx is not None and m200 and spx <= m200 * 0.95),
        "④": sahm is not None and sahm >= 0.5,
        "⑤": nfci is not None and nfci >= 0,
    }
    # ── 회복 신호(R1~R6)
    Rc = {
        "R1": aux["vixlt25"] >= 5,
        "R2": None if hyv is None else ((peak - hyv) >= 0.5 or rise < 0.5),
        "R3": above200 >= 3,
        "R4": None if b is None else b >= 60,
        "R5": (gap is not None and gap <= 0) or (core is not None and core <= 0.2),
        "R6": sig[9].get("buy", 0) >= 5 or (kos is not None and kma is not None and kos > kma),
    }

    reds = [i for i in sig if sig[i]["color"] == R]
    unknown = [i for i in sig if sig[i]["color"] == U]
    hy_red = sig[3]["color"] == R
    w_on = [k for k, v in W.items() if v]
    d_on = [k for k, v in D.items() if v]
    r_on = [k for k, v in Rc.items() if v]
    st2 = len(reds) >= 3 or hy_red
    if len(d_on) >= 2:
        esc = 4
    elif st2 and len(w_on) >= 2:
        esc = 3
    elif st2:
        esc = 2
    else:
        esc = 1

    if len(r_on) >= 5 and "R3" in r_on and esc <= 2:
        rec = 3
    elif len(r_on) >= 4 and not d_on:
        rec = 2
    elif len(r_on) >= 2:
        rec = 1  # 4개 이상인데 위험신호가 있으면 1단계로 둠(추론)
    else:
        rec = 0

    # 시나리오
    if hy_red:
        scen = "07년 서브프라임·2000년 닷컴형(하락폭 큼)"
    elif sig[3]["color"] == G and gap is not None and gap > 0 and core is not None and core >= 0.2:
        scen = "22년 하락장형(얕지만 오래 감)"
    elif gap is not None and gap < 0 and core is not None and core < 0.2:
        scen = "23년 10월형(상승장) — '예상보다 낮음'은 컨센서스 대신 0.2% 미만으로 대체(추론)"
    else:
        scen = "세 시나리오 조건 어느 것에도 완전히 해당하지 않음(혼합)"

    return dict(sig=sig, aux=aux, W=W, D=D, Rc=Rc, reds=reds, unknown=unknown, w_on=w_on, d_on=d_on,
                r_on=r_on, esc=esc, rec=rec, st2=st2, scen=scen, notes=notes,
                schedule=rs.get("schedule", "확인 불가"), src=s["_src"])


# ───────────────────────── 리포트 ─────────────────────────
ESC_NAME = {1: "관찰", 2: "경계", 3: "방어 준비", 4: "회피"}
ESC_DO = {1: "지켜보기", 2: "새 매수 줄이고 현금 비중 점검", 3: "위험자산 줄일 계획 세우기", 4: "위험자산 축소 실제 검토"}
REC_NAME = {0: "하락 진행", 1: "바닥 탐색", 2: "분할 재진입 검토", 3: "추세 회복"}
W_TXT = {"a": "하이일드 3.5%p↑/6M최저+1.0%p↑", "b": "VIX 25↑ 2일", "c": "S&P 200일선 아래 3일",
         "d": "근원CPI 0.3%↑", "e": "10년물 5%↑ 10일", "f": "빅테크 2곳↑ capex<20%",
         "g": "삼의법칙 0.3↑/IC4WSA 25만↑", "h": "코스피<200일선 & 원달러 1M +5%↑"}
D_TXT = {"①": "하이일드 4.0%p↑/6M최저+1.5%p↑", "②": "VIX 30↑ 3일", "③": "데드크로스/200일선 -5%↓",
         "④": "삼의법칙 0.5↑", "⑤": "NFCI 0↑"}
R_TXT = {"R1": "VIX<25 5일", "R2": "하이일드 고점-0.5%p/6M최저+0.5%p 미만", "R3": "S&P 200일선 위 3일",
         "R4": "200일선 위 종목 60%↑", "R5": "2년물≤기준금리 또는 근원CPI≤0.2%", "R6": "외국인 5일 순매수/코스피>200일선"}


def fmt_flags(flags, txt):
    on = [f"{k}({txt[k]})" for k, v in flags.items() if v]
    unk = [k for k, v in flags.items() if v is None]
    s = ", ".join(on) if on else "없음"
    return s + (f" · 확인 불가: {','.join(unk)}" if unk else "")


def render(e):
    a, sig = e["aux"], e["sig"]
    esc, rec = e["esc"], e["rec"]
    # 다음 단계까지 남은 조건
    if esc == 1:
        nxt = f"빨강 {3-len(e['reds'])}개 더 또는 하이일드 빨강(6M최저 대비 +0.5%p) → 2단계"
    elif esc == 2:
        nxt = f"악화 신호 {max(0,2-len(e['w_on']))}개 더 → 3단계 / 위험 신호 {max(0,2-len(e['d_on']))}개 더 → 4단계"
    elif esc == 3:
        nxt = f"위험 신호 {max(0,2-len(e['d_on']))}개 더 → 4단계"
    else:
        nxt = "최고 단계"
    if rec == 0:
        rn = f"회복 신호 {2-len(e['r_on'])}개 더 → 1단계"
    elif rec == 1:
        rn = f"회복 신호 {max(0,4-len(e['r_on']))}개 더" + (" + 위험 신호 0개" if e["d_on"] else "") + " → 2단계"
    elif rec == 2:
        rn = f"회복 신호 {max(0,5-len(e['r_on']))}개 더" + ("" if "R3" in e["r_on"] else " + R3 포함") + \
             ("" if esc <= 2 else " + 탈출 2단계 이하") + " → 3단계"
    else:
        rn = "최고 단계"
    off = [k for k, v in e["Rc"].items() if not v]

    L = []
    L.append(f"📊 장세 판정 — 기준: 미국장 {a['spx_d']} 마감 (FRED 최신 관측일 기준, 지표별 기준일 별도)")
    L.append("")
    L.append(f"1) 탈출 {esc}단계({ESC_NAME[esc]}) + 회복 {rec}단계({REC_NAME[rec]}): "
             f"빨강 {len(e['reds'])}개·악화 {len(e['w_on'])}개·위험 {len(e['d_on'])}개·회복 {len(e['r_on'])}개 → {ESC_DO[esc]}.")
    L.append(f"2) 탈출 {esc}단계 — 악화: {fmt_flags(e['W'], W_TXT)} / 위험: {fmt_flags(e['D'], D_TXT)}")
    L.append(f"   ↳ 다음 단계: {nxt}")
    L.append(f"3) 회복 {rec}단계 — 켜짐: {fmt_flags(e['Rc'], R_TXT)}")
    L.append(f"   ↳ 다음 단계: {rn} (꺼진 신호: {', '.join(off) or '없음'})")
    L.append("4) 11개 신호")
    for i in range(1, 12):
        L.append(f"   {sig[i]['color']} {i}. {sig[i]['name']}: {sig[i]['text']}")
    kos_pos = "확인 불가" if a["kospi200"] is None else ("위" if a["kospi"] > a["kospi200"] else "아래")
    L.append(f"5) 보조: VIX {f2(a['vix'])}({a['vix_d']}) · S&P {f2(a['spx'])}({a['spx_d']}) 50일 {f2(a['m50'],0)}/200일 {f2(a['m200'],0)} · "
             f"삼의법칙 {f2(a['sahm'])}({a['sahm_d'][:7] if a['sahm_d'] else '-'}) · IC4WSA {a['ic']:,.0f}({a['ic_d']}) · "
             f"NFCI {f2(a['nfci'])}({a['nfci_d']}) · 원달러 {f2(a['krw'],1)}({a['krw_d']}) 1M {a['krw1m']:+.1f}% · "
             f"코스피 {f2(a['kospi'])}({a['kospi_d']}) 200일선({f2(a['kospi200'],0)}) {kos_pos}")
    L.append(f"   시나리오: {e['scen']}")
    L.append(f"   일정: {e['schedule']}")
    if e["unknown"]:
        L.append(f"   ⚪ 확인 불가 신호 {e['unknown']} 는 빨강 개수에서 제외했습니다.")
    for n in e["notes"]:
        L.append(f"   ※ {n}")
    L.append("※ 지표는 거짓 경보를 낼 수 있고, 웹검색 항목(6·7·8·11·9·일부 시장가)은 근사치입니다.")
    L.append("지표 모니터링이며 매매 권유가 아닙니다.")
    return "\n".join(L)


if __name__ == "__main__":
    rp = HERE / "research.json"
    rs = json.loads(rp.read_text()) if rp.exists() else {}
    s = collect()
    (HERE / "out").mkdir(exist_ok=True)
    e = evaluate(s, rs)
    rep = render(e)
    (HERE / "out" / "latest_report.txt").write_text(rep)
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in e.items() if k != "sig"} | {"sig": e["sig"]}, ensure_ascii=False, default=str, indent=1))
    else:
        print(rep)
