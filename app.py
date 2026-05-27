from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

import requests
import streamlit as st

st.set_page_config(page_title="삼성전자 vs SK하이닉스 시가총액", layout="wide")

REQUEST_TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (MarketCapMonitor/1.0)"
UTC = timezone.utc

SYMBOLS = {
    "삼성전자": {"krx": "005930", "yahoo": "005930.KS", "investing_slug": "samsung-elec"},
    "SK하이닉스": {"krx": "000660", "yahoo": "000660.KS", "investing_slug": "sk-hynix-inc"},
}


@dataclass
class Quote:
    source: str
    company: str
    price_krw: float
    market_cap_krw: float
    updated_at: datetime


def fetch_yahoo_quote(yahoo_symbol: str, company: str) -> Quote | None:
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={yahoo_symbol}"
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        res.raise_for_status()
        data = res.json()["quoteResponse"]["result"][0]
        price = float(data["regularMarketPrice"])
        mcap = float(data["marketCap"])
        ts = datetime.fromtimestamp(int(data.get("regularMarketTime", datetime.now(tz=UTC).timestamp())), tz=UTC)
        return Quote("Yahoo Finance", company, price, mcap, ts)
    except Exception:
        return None


def fetch_investing_price(slug: str, company: str) -> tuple[str, float, datetime] | None:
    url = f"https://www.investing.com/equities/{slug}"
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        res.raise_for_status()
        m = re.search(r'"last"\s*:\s*"([0-9,]+(?:\\.[0-9]+)?)"', res.text)
        if not m:
            m = re.search(r'data-test="instrument-price-last">\s*([0-9,]+(?:\.[0-9]+)?)\s*<', res.text)
        if not m:
            return None
        price = float(m.group(1).replace(",", ""))
        return ("Investing.com", price, datetime.now(tz=UTC))
    except Exception:
        return None


def get_live_quotes() -> tuple[list[Quote], list[str]]:
    quotes: list[Quote] = []
    warnings: list[str] = []

    for company, ids in SYMBOLS.items():
        y = fetch_yahoo_quote(ids["yahoo"], company)
        if y:
            quotes.append(y)
        else:
            warnings.append(f"{company}: Yahoo Finance 데이터를 불러오지 못했습니다.")

        inv = fetch_investing_price(ids["investing_slug"], company)
        if inv and y:
            # investing은 가격만 제공하므로 시총은 Yahoo 주식수 역산값을 사용
            inferred_shares = y.market_cap_krw / y.price_krw if y.price_krw else 0.0
            quotes.append(
                Quote(
                    source=inv[0],
                    company=company,
                    price_krw=inv[1],
                    market_cap_krw=inv[1] * inferred_shares,
                    updated_at=inv[2],
                )
            )
        elif not inv:
            warnings.append(f"{company}: Investing.com 가격 파싱에 실패했습니다.")

    return quotes, warnings


def fmt_krw(v: float) -> str:
    return f"₩{v:,.0f}"


st.title("📊 삼성전자 vs SK하이닉스 실시간 시가총액 비교")
st.caption("소스: Yahoo Finance + Investing.com (Toss/Google은 공식 실시간 공개 API 부재로 미연동)")

if st.button("지금 새로고침", type="primary"):
    st.cache_data.clear()


@st.cache_data(ttl=20)
def cached_quotes() -> tuple[list[Quote], list[str]]:
    return get_live_quotes()


quotes, warnings = cached_quotes()

if warnings:
    for w in warnings:
        st.warning(w)

if not quotes:
    st.error("실시간 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

source = st.selectbox("비교 데이터 소스", sorted({q.source for q in quotes}))
chosen = [q for q in quotes if q.source == source]

samsung = next((q for q in chosen if q.company == "삼성전자"), None)
hynix = next((q for q in chosen if q.company == "SK하이닉스"), None)

if not samsung or not hynix:
    st.error("선택한 소스에 두 종목 데이터가 모두 없습니다.")
    st.stop()

ratio = (hynix.market_cap_krw / samsung.market_cap_krw * 100) if samsung.market_cap_krw else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("삼성전자 시가총액", fmt_krw(samsung.market_cap_krw), f"주가 {fmt_krw(samsung.price_krw)}")
c2.metric("SK하이닉스 시가총액", fmt_krw(hynix.market_cap_krw), f"주가 {fmt_krw(hynix.price_krw)}")
c3.metric("하이닉스/삼성 비율", f"{ratio:.2f}%")

st.progress(min(max(ratio / 100, 0.0), 1.0), text=f"현재 SK하이닉스 시총은 삼성전자의 {ratio:.2f}%")

st.markdown("### 원시 데이터")
st.dataframe(
    [
        {
            "source": q.source,
            "company": q.company,
            "price_krw": round(q.price_krw, 2),
            "market_cap_krw": round(q.market_cap_krw, 2),
            "updated_at_utc": q.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for q in chosen
    ],
    use_container_width=True,
)

st.info(
    "참고: Investing.com은 페이지 파싱 기반이라 구조 변경 시 실패할 수 있습니다. "
    "Google Finance/Toss는 공식 무료 실시간 시세 API가 없어 현재 버전에서는 연동하지 않았습니다."
)
