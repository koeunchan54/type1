from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote_plus
import re
import xml.etree.ElementTree as ET

import requests
import streamlit as st

st.set_page_config(page_title="미국 증시 뉴스 터미널", layout="wide")

UTC = timezone.utc
REQUEST_TIMEOUT = 8
MAX_ITEMS_PER_SOURCE = 18


@dataclass
class SourceConfig:
    name: str
    url: str
    source_type: str  # media | social
    credibility: int  # 1~5
    note: str


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
    impact_label: str
    importance_stars: int


TRUSTED_MEDIA_SOURCES: list[SourceConfig] = [
    SourceConfig("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "media", 5, "국제 통신사"),
    SourceConfig("AP Business", "https://apnews.com/hub/business/rss", "media", 5, "국제 통신사"),
    SourceConfig("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "media", 4, "금융 전문 매체"),
    SourceConfig("Financial Times US", "https://www.ft.com/us?format=rss", "media", 5, "글로벌 경제지"),
    SourceConfig("WSJ World", "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "media", 5, "글로벌 경제지"),
]


def social_sources(keyword: str) -> list[SourceConfig]:
    encoded = quote_plus(keyword)
    return [
        SourceConfig("Reddit r/investing", "https://www.reddit.com/r/investing/.rss", "social", 2, "커뮤니티 여론"),
        SourceConfig(
            "Reddit r/stocks",
            f"https://www.reddit.com/r/stocks/search.rss?q={encoded}&restrict_sr=1&sort=new",
            "social",
            2,
            "커뮤니티 여론",
        ),
    ]


POSITIVE_TERMS = {
    "rate cut",
    "cooling inflation",
    "beat expectations",
    "record profit",
    "stimulus",
    "soft landing",
    "trade deal",
    "approval",
    "upgrade",
    "rally",
    "strong demand",
    "growth",
}

NEGATIVE_TERMS = {
    "rate hike",
    "hot inflation",
    "missed expectations",
    "guidance cut",
    "war",
    "sanction",
    "default",
    "recession",
    "layoffs",
    "downgrade",
    "selloff",
    "antitrust",
}

HIGH_IMPACT_TERMS = {
    "federal reserve",
    "fed",
    "cpi",
    "inflation",
    "jobs report",
    "treasury",
    "oil",
    "opec",
    "china",
    "earnings",
    "gdp",
    "tariff",
    "bank of japan",
    "ecb",
}

TRANSLATION_DICT = {
    "federal reserve": "미 연준",
    "fed": "연준",
    "inflation": "인플레이션",
    "rate cut": "금리 인하",
    "rate hike": "금리 인상",
    "stocks": "주식",
    "stock": "주식",
    "oil": "원유",
    "earnings": "실적",
    "recession": "경기침체",
    "treasury": "미 국채",
    "dollar": "달러",
    "tariff": "관세",
    "china": "중국",
    "us": "미국",
    "bank": "은행",
    "profit": "이익",
    "loss": "손실",
    "market": "시장",
    "economy": "경제",
}


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    return None


def clean_html(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def translate_headline(title_en: str) -> str:
    translated = title_en
    # 긴 키를 먼저 치환해야 부분 치환 부작용이 줄어듭니다.
    for en in sorted(TRANSLATION_DICT.keys(), key=len, reverse=True):
        ko = TRANSLATION_DICT[en]
        translated = re.sub(fr"\b{re.escape(en)}\b", ko, translated, flags=re.IGNORECASE)

    if translated == title_en:
        return f"[원문] {title_en}"
    return translated


def score_impact(title: str, summary: str, source_type: str) -> tuple[float, str, int]:
    text = f"{title} {summary}".lower()
    score = 0.0

    for term in POSITIVE_TERMS:
        if term in text:
            score += 1.15

    for term in NEGATIVE_TERMS:
        if term in text:
            score -= 1.15

    for term in HIGH_IMPACT_TERMS:
        if term in text:
            score += 0.45 if score >= 0 else -0.45

    if source_type == "social":
        score *= 0.75

    score = max(-5.0, min(5.0, score))

    if score > 0.5:
        label = "📈 긍정"
    elif score < -0.5:
        label = "📉 부정"
    else:
        label = "➖ 중립"

    stars = max(1, min(5, int(abs(score)) + 1))
    return score, label, stars


def extract_entries(feed_xml: str) -> list[ET.Element]:
    root = ET.fromstring(feed_xml)
    return root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry")


def item_text(item: ET.Element, names: list[str]) -> str:
    for name in names:
        node = item.find(name)
        if node is not None and node.text:
            return clean_html(node.text)
    return ""


def item_link(item: ET.Element) -> str:
    plain = item_text(item, ["link"])
    if plain.startswith("http"):
        return plain

    atom_link = item.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        return atom_link.attrib.get("href", "")
    return ""


def fetch_source(source: SourceConfig) -> list[NewsItem]:
    try:
        response = requests.get(
            source.url,
            headers={"User-Agent": "Mozilla/5.0 (StockNewsTerminal/1.1)"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    try:
        entries = extract_entries(response.text)
    except ET.ParseError:
        return []

    items: list[NewsItem] = []
    for idx, entry in enumerate(entries[:MAX_ITEMS_PER_SOURCE], start=1):
        title = item_text(entry, ["title", "{http://www.w3.org/2005/Atom}title"])
        if not title:
            continue

        summary = item_text(
            entry,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://purl.org/rss/1.0/modules/content/}encoded",
            ],
        )
        raw_date = item_text(entry, ["pubDate", "published", "{http://www.w3.org/2005/Atom}published", "updated"])
        published = parse_dt(raw_date)
        impact_score, impact_label, stars = score_impact(title, summary, source.source_type)

        items.append(
            NewsItem(
                id=f"{source.name}-{idx}-{title[:24]}",
                source=source.name,
                source_type=source.source_type,
                credibility=source.credibility,
                title_en=title,
                title_ko=translate_headline(title),
                link=item_link(entry),
                published=published,
                summary=summary,
                impact_score=impact_score,
                impact_label=impact_label,
                importance_stars=stars,
            )
        )
    return items


def collect_news(keyword: str) -> list[NewsItem]:
    sources = TRUSTED_MEDIA_SOURCES + social_sources(keyword)
    news: list[NewsItem] = []
    for source in sources:
        news.extend(fetch_source(source))

    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    recent = [item for item in news if item.published is None or item.published >= cutoff]
    recent.sort(
        key=lambda item: (
            item.importance_stars,
            abs(item.impact_score),
            item.published or datetime(1970, 1, 1, tzinfo=UTC),
        ),
        reverse=True,
    )
    return recent[:40]


def source_tag(source_type: str) -> str:
    return "검증 매체" if source_type == "media" else "소셜"


def render_feed_list(items: list[NewsItem]) -> None:
    st.markdown("#### 헤드라인 피드")
    for i, item in enumerate(items):
        stars = "⭐" * item.importance_stars
        published = item.published.strftime("%m-%d %H:%M") if item.published else "시각 미상"
        label = f"{item.impact_label} · {stars} · {source_tag(item.source_type)}"
        button_text = f"{item.title_ko}\n{label} · {published}"
        if st.button(button_text, key=f"news_btn_{item.id}_{i}", use_container_width=True):
            st.session_state["selected_news_id"] = item.id


def render_detail(items: list[NewsItem]) -> None:
    if not items:
        st.info("표시할 뉴스가 없습니다.")
        return

    selected_id = st.session_state.get("selected_news_id", items[0].id)
    selected = next((x for x in items if x.id == selected_id), items[0])

    st.markdown("#### 상세 본문")
    st.subheader(selected.title_ko)
    st.caption(selected.title_en)

    c1, c2, c3 = st.columns(3)
    c1.metric("증시 영향", selected.impact_label)
    c2.metric("중요도", "⭐" * selected.importance_stars)
    c3.metric("출처 신뢰도", "★" * selected.credibility + "☆" * (5 - selected.credibility))

    when = selected.published.strftime("%Y-%m-%d %H:%M UTC") if selected.published else "시간 정보 없음"
    st.markdown(f"- **출처:** {selected.source} ({source_tag(selected.source_type)})")
    st.markdown(f"- **게시 시각:** {when}")
    st.markdown(f"- **영향 점수:** {selected.impact_score:+.2f}")

    st.markdown("**요약**")
    st.write(selected.summary[:1200] if selected.summary else "요약 텍스트가 없습니다.")

    if selected.link:
        st.link_button("원문 기사 열기", selected.link, use_container_width=True)


def apply_filters(items: list[NewsItem], impact_filter: str, source_filter: str) -> list[NewsItem]:
    filtered = items

    if impact_filter == "긍정만":
        filtered = [item for item in filtered if item.impact_score > 0.5]
    elif impact_filter == "부정만":
        filtered = [item for item in filtered if item.impact_score < -0.5]

    if source_filter == "검증 매체만":
        filtered = [item for item in filtered if item.source_type == "media"]
    elif source_filter == "소셜만":
        filtered = [item for item in filtered if item.source_type == "social"]

    return filtered


st.title("🇺🇸 미국 주식 영향 뉴스 터미널")
st.caption("국제/경제 뉴스 + 소셜 트렌드를 모아 증시 영향도를 빠르게 확인합니다.")

with st.sidebar:
    st.markdown("### 설정")
    keyword = st.text_input("소셜 키워드", value="US stocks")
    impact_filter = st.selectbox("영향 필터", ["전체", "긍정만", "부정만"])
    source_filter = st.selectbox("소스 필터", ["전체", "검증 매체만", "소셜만"])

    if st.button("새로고침", type="primary", use_container_width=True):
        st.session_state["news_items"] = collect_news(keyword)
        st.session_state.pop("selected_news_id", None)

    st.markdown("---")
    st.markdown("### 팩트체킹 반영 소스")
    for src in TRUSTED_MEDIA_SOURCES:
        st.markdown(f"- {src.name} · 신뢰도 {'★' * src.credibility}{'☆' * (5 - src.credibility)}")

if "news_items" not in st.session_state:
    st.session_state["news_items"] = collect_news(keyword)

all_items: list[NewsItem] = st.session_state["news_items"]
filtered_items = apply_filters(all_items, impact_filter, source_filter)

m1, m2, m3, m4 = st.columns(4)
m1.metric("수집 기사", f"{len(all_items)}건")
m2.metric("표시 기사", f"{len(filtered_items)}건")
m3.metric("긍정", f"{sum(1 for x in filtered_items if x.impact_score > 0.5)}건")
m4.metric("부정", f"{sum(1 for x in filtered_items if x.impact_score < -0.5)}건")

left, right = st.columns([1.1, 1.4])
with left:
    render_feed_list(filtered_items)
with right:
    render_detail(filtered_items)
