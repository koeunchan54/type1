from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote_plus
import re
import xml.etree.ElementTree as ET

import requests
import streamlit as st

st.set_page_config(page_title="증시 모니터링 통합 대시보드", layout="wide")

UTC = timezone.utc
REQUEST_TIMEOUT = 8
MAX_ITEMS_PER_SOURCE = 18
USER_AGENT = "Mozilla/5.0 (MarketCapMonitor/1.0)"


# ---------- 시총 비교 ----------
SYMBOLS = {
    "삼성전자": {"yahoo": "005930.KS", "investing_slug": "samsung-elec", "google": "KRX:005930"},
    "SK하이닉스": {"yahoo": "000660.KS", "investing_slug": "sk-hynix-inc", "google": "KRX:000660"},
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
        return Quote(
            "Yahoo Finance",
            company,
            float(data["regularMarketPrice"]),
            float(data["marketCap"]),
            datetime.fromtimestamp(int(data.get("regularMarketTime", datetime.now(tz=UTC).timestamp())), tz=UTC),
        )
    except Exception:
        return None


def fetch_investing_price(slug: str) -> tuple[str, float, datetime] | None:
    try:
        res = requests.get(
            f"https://www.investing.com/equities/{slug}",
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
        res.raise_for_status()
        m = re.search(r'"last"\s*:\s*"([0-9,]+(?:\\.[0-9]+)?)"', res.text) or re.search(
            r'data-test="instrument-price-last">\s*([0-9,]+(?:\.[0-9]+)?)\s*<', res.text
        )
        if not m:
            return None
        return "Investing.com", float(m.group(1).replace(",", "")), datetime.now(tz=UTC)
    except Exception:
        return None


def fetch_google_price(symbol: str) -> tuple[str, float, datetime] | None:
    try:
        res = requests.get(
            f"https://www.google.com/finance/quote/{symbol}",
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
        res.raise_for_status()
        m = re.search(r'data-last-price="([0-9,.]+)"', res.text) or re.search(r'"price"\s*:\s*"([0-9,.]+)"', res.text)
        if not m:
            return None
        return "Google Finance", float(m.group(1).replace(",", "")), datetime.now(tz=UTC)
    except Exception:
        return None


def get_live_quotes() -> tuple[list[Quote], list[str]]:
    quotes: list[Quote] = []
    warns: list[str] = []
    for company, ids in SYMBOLS.items():
        y = fetch_yahoo_quote(ids["yahoo"], company)
        if y:
            quotes.append(y)
        else:
            warns.append(f"{company}: Yahoo Finance 수집 실패")
            continue

        shares = y.market_cap_krw / y.price_krw if y.price_krw else 0.0

        inv = fetch_investing_price(ids["investing_slug"])
        if inv:
            quotes.append(Quote(inv[0], company, inv[1], inv[1] * shares, inv[2]))
        else:
            warns.append(f"{company}: Investing.com 파싱 실패")

        goog = fetch_google_price(ids["google"])
        if goog:
            quotes.append(Quote(goog[0], company, goog[1], goog[1] * shares, goog[2]))
        else:
            warns.append(f"{company}: Google Finance 파싱 실패")

    return quotes, warns


# ---------- 뉴스 터미널(복원) ----------
@dataclass
class SourceConfig:
    name: str
    url: str
    source_type: str
    credibility: int


@dataclass
class NewsItem:
    id: str
    source: str
    source_type: str
    credibility: int
    title_en: str
    title_ko: str
    link: str
    published: datetime | None
    summary: str
    impact_score: float


TRUSTED_MEDIA_SOURCES: list[SourceConfig] = [
    SourceConfig("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "media", 5),
    SourceConfig("AP Business", "https://apnews.com/hub/business/rss", "media", 5),
    SourceConfig("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "media", 4),
]


def social_sources(keyword: str) -> list[SourceConfig]:
    encoded = quote_plus(keyword)
    return [
        SourceConfig("Reddit r/investing", "https://www.reddit.com/r/investing/.rss", "social", 2),
        SourceConfig("Reddit r/stocks", f"https://www.reddit.com/r/stocks/search.rss?q={encoded}&restrict_sr=1&sort=new", "social", 2),
    ]


def clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(text or ""))).strip()


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(raw, fmt).astimezone(UTC)
        except ValueError:
            pass
    return None


def translate_title(t: str) -> str:
    return t.replace("inflation", "인플레이션").replace("rate cut", "금리 인하")


def fetch_source(src: SourceConfig) -> list[NewsItem]:
    try:
        r = requests.get(src.url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception:
        return []
    entries = root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out: list[NewsItem] = []
    for i, it in enumerate(entries[:MAX_ITEMS_PER_SOURCE], 1):
        title = clean_html((it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or ""))
        if not title:
            continue
        desc = clean_html(it.findtext("description") or it.findtext("summary") or "")
        dt = parse_dt(it.findtext("pubDate") or it.findtext("published"))
        link = clean_html(it.findtext("link") or "")
        score = (1.0 if "beat" in (title + desc).lower() else 0.0) - (1.0 if "miss" in (title + desc).lower() else 0.0)
        out.append(NewsItem(f"{src.name}-{i}", src.name, src.source_type, src.credibility, title, translate_title(title), link, dt, desc, score))
    return out


def collect_news(keyword: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for src in TRUSTED_MEDIA_SOURCES + social_sources(keyword):
        items.extend(fetch_source(src))
    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    filtered = [x for x in items if x.published is None or x.published >= cutoff]
    return sorted(filtered, key=lambda x: (abs(x.impact_score), x.published or datetime(1970, 1, 1, tzinfo=UTC)), reverse=True)[:40]


@st.cache_data(ttl=20)
def cached_quotes() -> tuple[list[Quote], list[str]]:
    return get_live_quotes()


@st.cache_data(ttl=120)
def cached_news(keyword: str) -> list[NewsItem]:
    return collect_news(keyword)


# ---------- UI ----------
st.title("📈 증시 모니터링 통합 대시보드")
tab1, tab2 = st.tabs(["시가총액 비교", "미국 증시 뉴스 터미널"])

with tab1:
    st.caption("소스: Yahoo Finance + Investing.com + Google Finance (Toss는 공식 실시간 API 부재)")
    if st.button("시총 데이터 새로고침", type="primary"):
        st.cache_data.clear()
    quotes, warnings = cached_quotes()
    for w in warnings:
        st.warning(w)
    if not quotes:
        st.error("실시간 데이터를 가져오지 못했습니다.")
    else:
        source = st.selectbox("비교 데이터 소스", sorted({q.source for q in quotes}))
        chosen = [q for q in quotes if q.source == source]
        samsung = next((q for q in chosen if q.company == "삼성전자"), None)
        hynix = next((q for q in chosen if q.company == "SK하이닉스"), None)
        if samsung and hynix:
            ratio = (hynix.market_cap_krw / samsung.market_cap_krw * 100) if samsung.market_cap_krw else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("삼성전자 시총", f"₩{samsung.market_cap_krw:,.0f}", f"주가 ₩{samsung.price_krw:,.0f}")
            c2.metric("SK하이닉스 시총", f"₩{hynix.market_cap_krw:,.0f}", f"주가 ₩{hynix.price_krw:,.0f}")
            c3.metric("하이닉스/삼성", f"{ratio:.2f}%")

with tab2:
    kw = st.text_input("소셜 키워드", value="US stocks")
    if st.button("뉴스 새로고침"):
        cached_news.clear()
    news = cached_news(kw)
    st.write(f"수집 기사: {len(news)}건")
    for n in news[:20]:
        when = n.published.strftime("%m-%d %H:%M") if n.published else "시각 미상"
        st.markdown(f"- **{n.title_ko}** ({n.source}, {when})")
        if n.summary:
            st.caption(n.summary[:160])
