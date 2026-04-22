diff --git a/app.py b/app.py
index 6acd4284fc2e76f8c56dca5b86aa52099a9bda51..6a069db0a796956ff1a865fb0d4f3810ea91cf74 100644
--- a/app.py
+++ b/app.py
@@ -1,268 +1,402 @@
-import math
-import random
+from __future__ import annotations
+
 from dataclasses import dataclass
+from datetime import datetime, timedelta, timezone
+from html import unescape
+from urllib.parse import quote_plus
+import re
+import xml.etree.ElementTree as ET
 
-import chess
+import requests
 import streamlit as st
 
-st.set_page_config(page_title="로컬 체스 (ELO 600)", layout="wide")
-
-PIECE_VALUES = {
-    chess.PAWN: 100,
-    chess.KNIGHT: 320,
-    chess.BISHOP: 330,
-    chess.ROOK: 500,
-    chess.QUEEN: 900,
-    chess.KING: 0,
-}
+st.set_page_config(page_title="미국 증시 뉴스 터미널", layout="wide")
 
-UNICODE_PIECES = {
-    "P": "♙",
-    "N": "♘",
-    "B": "♗",
-    "R": "♖",
-    "Q": "♕",
-    "K": "♔",
-    "p": "♟",
-    "n": "♞",
-    "b": "♝",
-    "r": "♜",
-    "q": "♛",
-    "k": "♚",
-}
+UTC = timezone.utc
+REQUEST_TIMEOUT = 8
+MAX_ITEMS_PER_SOURCE = 18
 
 
 @dataclass
-class MoveInsight:
-    san: str
-    quality: float
-    win_delta: float
-    best_san: str
-
-
-def init_state() -> None:
-    if "board" not in st.session_state:
-        st.session_state.board = chess.Board()
-    if "insights" not in st.session_state:
-        st.session_state.insights = []
-    if "last_ai_move" not in st.session_state:
-        st.session_state.last_ai_move = "-"
-
-
-def evaluate_board(board: chess.Board) -> float:
-    if board.is_checkmate():
-        return -10000 if board.turn == chess.WHITE else 10000
-    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_threefold_repetition():
-        return 0
-
-    score = 0
-    for piece_type, value in PIECE_VALUES.items():
-        score += len(board.pieces(piece_type, chess.WHITE)) * value
-        score -= len(board.pieces(piece_type, chess.BLACK)) * value
-
-    mobility = len(list(board.legal_moves))
-    score += 4 * mobility if board.turn == chess.WHITE else -4 * mobility
-    return score
+class SourceConfig:
+    name: str
+    url: str
+    source_type: str  # media | social
+    credibility: int  # 1~5
+    note: str
 
 
-def minimax(board: chess.Board, depth: int, alpha: float, beta: float, maximizing_white: bool) -> float:
-    if depth == 0 or board.is_game_over():
-        return evaluate_board(board)
-
-    legal_moves = list(board.legal_moves)
-    random.shuffle(legal_moves)
-
-    if maximizing_white:
-        best = -math.inf
-        for move in legal_moves:
-            board.push(move)
-            best = max(best, minimax(board, depth - 1, alpha, beta, False))
-            board.pop()
-            alpha = max(alpha, best)
-            if beta <= alpha:
-                break
-        return best
-
-    best = math.inf
-    for move in legal_moves:
-        board.push(move)
-        best = min(best, minimax(board, depth - 1, alpha, beta, True))
-        board.pop()
-        beta = min(beta, best)
-        if beta <= alpha:
-            break
-    return best
-
-
-def win_probability(eval_cp: float) -> float:
-    return 1 / (1 + math.exp(-eval_cp / 400))
-
-
-def score_move(board: chess.Board, move: chess.Move, depth: int = 1) -> float:
-    board.push(move)
-    score = minimax(board, depth, -math.inf, math.inf, board.turn == chess.WHITE)
-    board.pop()
-    return score
-
-
-def ai_pick_move(board: chess.Board) -> chess.Move:
-    candidates = []
-    for move in board.legal_moves:
-        score = score_move(board, move, depth=1)
-        candidates.append((move, score))
-
-    candidates.sort(key=lambda x: x[1], reverse=board.turn == chess.WHITE)
-
-    # ELO 600 느낌: 좋은 수를 자주 두되, 20% 정도는 실수를 허용
-    blunder_roll = random.random()
-    if blunder_roll < 0.2 and len(candidates) > 3:
-        low_pool = candidates[len(candidates) // 2 :]
-        return random.choice(low_pool)[0]
-
-    top_n = min(4, len(candidates))
-    top_moves = candidates[:top_n]
-    move, _ = random.choice(top_moves)
-    return move
-
-
-def render_board(board: chess.Board) -> str:
-    files = "abcdefgh"
-    ranks = "87654321"
-    html = ["<div class='board-wrap'><div class='board'>"]
-
-    for rank in ranks:
-        for file in files:
-            square = chess.parse_square(f"{file}{rank}")
-            piece = board.piece_at(square)
-            symbol = UNICODE_PIECES.get(piece.symbol(), "") if piece else ""
-            is_light = (files.index(file) + ranks.index(rank)) % 2 == 0
-            square_class = "light" if is_light else "dark"
-            html.append(f"<div class='sq {square_class}'>{symbol}</div>")
-
-    html.append("</div></div>")
-    return "".join(html)
-
-
-def get_move_insight(board: chess.Board, move: chess.Move) -> MoveInsight:
-    legal_moves = list(board.legal_moves)
-    current_eval = evaluate_board(board)
-
-    scored = []
-    for candidate in legal_moves:
-        score = score_move(board, candidate)
-        scored.append((candidate, score))
-
-    scored.sort(key=lambda x: x[1], reverse=True)
-    best_move, best_score = scored[0]
-    played_score = next(score for candidate, score in scored if candidate == move)
-
-    quality = max(0.0, min(100.0, 100 - (best_score - played_score) / 8))
-    win_delta = (win_probability(played_score) - win_probability(current_eval)) * 100
-
-    san = board.san(move)
-    best_san = board.san(best_move)
-    return MoveInsight(san=san, quality=quality, win_delta=win_delta, best_san=best_san)
-
-
-init_state()
-board: chess.Board = st.session_state.board
-
-st.title("♟️ 혼자 즐기는 로컬 체스")
-st.caption("당신은 백(White), AI는 흑(Black)입니다. AI는 약 ELO 600 수준으로 설정되어 있습니다.")
-
-st.markdown(
-    """
-<style>
-.board-wrap {display:flex; justify-content:center; margin-top:8px;}
-.board {
-  display:grid;
-  grid-template-columns: repeat(8, 62px);
-  grid-template-rows: repeat(8, 62px);
-  border: 10px solid #2b2f33;
-  border-radius: 6px;
-  box-shadow: 0 4px 14px rgba(0,0,0,0.25);
+@dataclass
+class NewsItem:
+    id: str
+    source: str
+    source_type: str
+    credibility: int
+    title_en: str
+    title_ko: str
+    link: str
+    published: datetime | None
+    summary: str
+    impact_score: float
+    impact_label: str
+    importance_stars: int
+
+
+TRUSTED_MEDIA_SOURCES: list[SourceConfig] = [
+    SourceConfig("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "media", 5, "국제 통신사"),
+    SourceConfig("AP Business", "https://apnews.com/hub/business/rss", "media", 5, "국제 통신사"),
+    SourceConfig("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "media", 4, "금융 전문 매체"),
+    SourceConfig("Financial Times US", "https://www.ft.com/us?format=rss", "media", 5, "글로벌 경제지"),
+    SourceConfig("WSJ World", "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "media", 5, "글로벌 경제지"),
+]
+
+
+def social_sources(keyword: str) -> list[SourceConfig]:
+    encoded = quote_plus(keyword)
+    return [
+        SourceConfig("Reddit r/investing", "https://www.reddit.com/r/investing/.rss", "social", 2, "커뮤니티 여론"),
+        SourceConfig(
+            "Reddit r/stocks",
+            f"https://www.reddit.com/r/stocks/search.rss?q={encoded}&restrict_sr=1&sort=new",
+            "social",
+            2,
+            "커뮤니티 여론",
+        ),
+    ]
+
+
+POSITIVE_TERMS = {
+    "rate cut",
+    "cooling inflation",
+    "beat expectations",
+    "record profit",
+    "stimulus",
+    "soft landing",
+    "trade deal",
+    "approval",
+    "upgrade",
+    "rally",
+    "strong demand",
+    "growth",
 }
-.sq {
-  display:flex;
-  justify-content:center;
-  align-items:center;
-  font-size: 41px;
-  user-select:none;
+
+NEGATIVE_TERMS = {
+    "rate hike",
+    "hot inflation",
+    "missed expectations",
+    "guidance cut",
+    "war",
+    "sanction",
+    "default",
+    "recession",
+    "layoffs",
+    "downgrade",
+    "selloff",
+    "antitrust",
 }
-.light {background:#f0d9b5;}
-.dark {background:#b58863;}
-.metric {
-  border:1px solid #2f3b45;
-  border-radius:8px;
-  padding:10px;
-  background:#11161c;
+
+HIGH_IMPACT_TERMS = {
+    "federal reserve",
+    "fed",
+    "cpi",
+    "inflation",
+    "jobs report",
+    "treasury",
+    "oil",
+    "opec",
+    "china",
+    "earnings",
+    "gdp",
+    "tariff",
+    "bank of japan",
+    "ecb",
 }
-.move-pill {
-  border-left:4px solid #2ea043;
-  background:#0f1721;
-  padding:8px;
-  border-radius:6px;
-  margin-bottom:8px;
+
+TRANSLATION_DICT = {
+    "federal reserve": "미 연준",
+    "fed": "연준",
+    "inflation": "인플레이션",
+    "rate cut": "금리 인하",
+    "rate hike": "금리 인상",
+    "stocks": "주식",
+    "stock": "주식",
+    "oil": "원유",
+    "earnings": "실적",
+    "recession": "경기침체",
+    "treasury": "미 국채",
+    "dollar": "달러",
+    "tariff": "관세",
+    "china": "중국",
+    "us": "미국",
+    "bank": "은행",
+    "profit": "이익",
+    "loss": "손실",
+    "market": "시장",
+    "economy": "경제",
 }
-</style>
-""",
-    unsafe_allow_html=True,
-)
 
-left, right = st.columns([1.3, 1])
 
-with left:
-    st.markdown(render_board(board), unsafe_allow_html=True)
+def parse_dt(raw: str | None) -> datetime | None:
+    if not raw:
+        return None
 
-with right:
-    st.subheader("체스.com 스타일 분석 패널")
-    if st.session_state.insights:
-        latest = st.session_state.insights[-1]
-        st.markdown(f"<div class='metric'><b>최근 수:</b> {latest.san}<br><b>승리 기여도:</b> {latest.win_delta:+.2f}%<br><b>수 정확도:</b> {latest.quality:.1f}%<br><b>추천 수:</b> {latest.best_san}</div>", unsafe_allow_html=True)
-        st.progress(int(latest.quality))
-    else:
-        st.info("첫 수를 두면 승리 기여도/정확도 분석이 표시됩니다.")
+    formats = [
+        "%a, %d %b %Y %H:%M:%S %z",
+        "%a, %d %b %Y %H:%M:%S GMT",
+        "%Y-%m-%dT%H:%M:%SZ",
+        "%Y-%m-%dT%H:%M:%S%z",
+    ]
+    for fmt in formats:
+        try:
+            parsed = datetime.strptime(raw, fmt)
+            if parsed.tzinfo is None:
+                parsed = parsed.replace(tzinfo=UTC)
+            return parsed.astimezone(UTC)
+        except ValueError:
+            continue
+    return None
 
-    st.markdown(f"**AI 최근 수:** `{st.session_state.last_ai_move}`")
 
-    st.markdown("#### 내 수 로그")
-    if st.session_state.insights:
-        for idx, insight in enumerate(st.session_state.insights, start=1):
-            st.markdown(
-                f"<div class='move-pill'><b>{idx}. {insight.san}</b><br>기여도 {insight.win_delta:+.2f}% · 정확도 {insight.quality:.1f}%</div>",
-                unsafe_allow_html=True,
-            )
-    else:
-        st.caption("아직 기록이 없습니다.")
-
-if board.is_game_over():
-    result = board.result(claim_draw=True)
-    if result == "1-0":
-        st.success("게임 종료: 당신의 승리입니다!")
-    elif result == "0-1":
-        st.error("게임 종료: AI 승리입니다.")
+def clean_html(text: str) -> str:
+    text = unescape(text or "")
+    text = re.sub(r"<[^>]+>", " ", text)
+    text = re.sub(r"\s+", " ", text).strip()
+    return text
+
+
+def translate_headline(title_en: str) -> str:
+    translated = title_en
+    # 긴 키를 먼저 치환해야 부분 치환 부작용이 줄어듭니다.
+    for en in sorted(TRANSLATION_DICT.keys(), key=len, reverse=True):
+        ko = TRANSLATION_DICT[en]
+        translated = re.sub(fr"\b{re.escape(en)}\b", ko, translated, flags=re.IGNORECASE)
+
+    if translated == title_en:
+        return f"[원문] {title_en}"
+    return translated
+
+
+def score_impact(title: str, summary: str, source_type: str) -> tuple[float, str, int]:
+    text = f"{title} {summary}".lower()
+    score = 0.0
+
+    for term in POSITIVE_TERMS:
+        if term in text:
+            score += 1.15
+
+    for term in NEGATIVE_TERMS:
+        if term in text:
+            score -= 1.15
+
+    for term in HIGH_IMPACT_TERMS:
+        if term in text:
+            score += 0.45 if score >= 0 else -0.45
+
+    if source_type == "social":
+        score *= 0.75
+
+    score = max(-5.0, min(5.0, score))
+
+    if score > 0.5:
+        label = "📈 긍정"
+    elif score < -0.5:
+        label = "📉 부정"
     else:
-        st.warning("게임 종료: 무승부입니다.")
-else:
-    legal_moves = list(board.legal_moves)
-    move_options = [board.san(move) for move in legal_moves]
-    selected_san = st.selectbox("당신의 수 선택", move_options)
-
-    if st.button("수 두기", type="primary"):
-        chosen_move = legal_moves[move_options.index(selected_san)]
-        insight = get_move_insight(board, chosen_move)
-        st.session_state.insights.append(insight)
-        board.push(chosen_move)
-
-        if not board.is_game_over():
-            ai_move = ai_pick_move(board)
-            st.session_state.last_ai_move = board.san(ai_move)
-            board.push(ai_move)
-
-        st.rerun()
-
-if st.button("새 게임"):
-    st.session_state.board = chess.Board()
-    st.session_state.insights = []
-    st.session_state.last_ai_move = "-"
-    st.rerun()
+        label = "➖ 중립"
+
+    stars = max(1, min(5, int(abs(score)) + 1))
+    return score, label, stars
+
+
+def extract_entries(feed_xml: str) -> list[ET.Element]:
+    root = ET.fromstring(feed_xml)
+    return root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry")
+
+
+def item_text(item: ET.Element, names: list[str]) -> str:
+    for name in names:
+        node = item.find(name)
+        if node is not None and node.text:
+            return clean_html(node.text)
+    return ""
+
+
+def item_link(item: ET.Element) -> str:
+    plain = item_text(item, ["link"])
+    if plain.startswith("http"):
+        return plain
+
+    atom_link = item.find("{http://www.w3.org/2005/Atom}link")
+    if atom_link is not None:
+        return atom_link.attrib.get("href", "")
+    return ""
+
+
+def fetch_source(source: SourceConfig) -> list[NewsItem]:
+    try:
+        response = requests.get(
+            source.url,
+            headers={"User-Agent": "Mozilla/5.0 (StockNewsTerminal/1.1)"},
+            timeout=REQUEST_TIMEOUT,
+        )
+        response.raise_for_status()
+    except requests.RequestException:
+        return []
+
+    try:
+        entries = extract_entries(response.text)
+    except ET.ParseError:
+        return []
+
+    items: list[NewsItem] = []
+    for idx, entry in enumerate(entries[:MAX_ITEMS_PER_SOURCE], start=1):
+        title = item_text(entry, ["title", "{http://www.w3.org/2005/Atom}title"])
+        if not title:
+            continue
+
+        summary = item_text(
+            entry,
+            [
+                "description",
+                "summary",
+                "{http://www.w3.org/2005/Atom}summary",
+                "{http://purl.org/rss/1.0/modules/content/}encoded",
+            ],
+        )
+        raw_date = item_text(entry, ["pubDate", "published", "{http://www.w3.org/2005/Atom}published", "updated"])
+        published = parse_dt(raw_date)
+        impact_score, impact_label, stars = score_impact(title, summary, source.source_type)
+
+        items.append(
+            NewsItem(
+                id=f"{source.name}-{idx}-{title[:24]}",
+                source=source.name,
+                source_type=source.source_type,
+                credibility=source.credibility,
+                title_en=title,
+                title_ko=translate_headline(title),
+                link=item_link(entry),
+                published=published,
+                summary=summary,
+                impact_score=impact_score,
+                impact_label=impact_label,
+                importance_stars=stars,
+            )
+        )
+    return items
+
+
+def collect_news(keyword: str) -> list[NewsItem]:
+    sources = TRUSTED_MEDIA_SOURCES + social_sources(keyword)
+    news: list[NewsItem] = []
+    for source in sources:
+        news.extend(fetch_source(source))
+
+    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
+    recent = [item for item in news if item.published is None or item.published >= cutoff]
+    recent.sort(
+        key=lambda item: (
+            item.importance_stars,
+            abs(item.impact_score),
+            item.published or datetime(1970, 1, 1, tzinfo=UTC),
+        ),
+        reverse=True,
+    )
+    return recent[:40]
+
+
+def source_tag(source_type: str) -> str:
+    return "검증 매체" if source_type == "media" else "소셜"
+
+
+def render_feed_list(items: list[NewsItem]) -> None:
+    st.markdown("#### 헤드라인 피드")
+    for i, item in enumerate(items):
+        stars = "⭐" * item.importance_stars
+        published = item.published.strftime("%m-%d %H:%M") if item.published else "시각 미상"
+        label = f"{item.impact_label} · {stars} · {source_tag(item.source_type)}"
+        button_text = f"{item.title_ko}\n{label} · {published}"
+        if st.button(button_text, key=f"news_btn_{item.id}_{i}", use_container_width=True):
+            st.session_state["selected_news_id"] = item.id
+
+
+def render_detail(items: list[NewsItem]) -> None:
+    if not items:
+        st.info("표시할 뉴스가 없습니다.")
+        return
+
+    selected_id = st.session_state.get("selected_news_id", items[0].id)
+    selected = next((x for x in items if x.id == selected_id), items[0])
+
+    st.markdown("#### 상세 본문")
+    st.subheader(selected.title_ko)
+    st.caption(selected.title_en)
+
+    c1, c2, c3 = st.columns(3)
+    c1.metric("증시 영향", selected.impact_label)
+    c2.metric("중요도", "⭐" * selected.importance_stars)
+    c3.metric("출처 신뢰도", "★" * selected.credibility + "☆" * (5 - selected.credibility))
+
+    when = selected.published.strftime("%Y-%m-%d %H:%M UTC") if selected.published else "시간 정보 없음"
+    st.markdown(f"- **출처:** {selected.source} ({source_tag(selected.source_type)})")
+    st.markdown(f"- **게시 시각:** {when}")
+    st.markdown(f"- **영향 점수:** {selected.impact_score:+.2f}")
+
+    st.markdown("**요약**")
+    st.write(selected.summary[:1200] if selected.summary else "요약 텍스트가 없습니다.")
+
+    if selected.link:
+        st.link_button("원문 기사 열기", selected.link, use_container_width=True)
+
+
+def apply_filters(items: list[NewsItem], impact_filter: str, source_filter: str) -> list[NewsItem]:
+    filtered = items
+
+    if impact_filter == "긍정만":
+        filtered = [item for item in filtered if item.impact_score > 0.5]
+    elif impact_filter == "부정만":
+        filtered = [item for item in filtered if item.impact_score < -0.5]
+
+    if source_filter == "검증 매체만":
+        filtered = [item for item in filtered if item.source_type == "media"]
+    elif source_filter == "소셜만":
+        filtered = [item for item in filtered if item.source_type == "social"]
+
+    return filtered
+
+
+st.title("🇺🇸 미국 주식 영향 뉴스 터미널")
+st.caption("국제/경제 뉴스 + 소셜 트렌드를 모아 증시 영향도를 빠르게 확인합니다.")
+
+with st.sidebar:
+    st.markdown("### 설정")
+    keyword = st.text_input("소셜 키워드", value="US stocks")
+    impact_filter = st.selectbox("영향 필터", ["전체", "긍정만", "부정만"])
+    source_filter = st.selectbox("소스 필터", ["전체", "검증 매체만", "소셜만"])
+
+    if st.button("새로고침", type="primary", use_container_width=True):
+        st.session_state["news_items"] = collect_news(keyword)
+        st.session_state.pop("selected_news_id", None)
+
+    st.markdown("---")
+    st.markdown("### 팩트체킹 반영 소스")
+    for src in TRUSTED_MEDIA_SOURCES:
+        st.markdown(f"- {src.name} · 신뢰도 {'★' * src.credibility}{'☆' * (5 - src.credibility)}")
+
+if "news_items" not in st.session_state:
+    st.session_state["news_items"] = collect_news(keyword)
+
+all_items: list[NewsItem] = st.session_state["news_items"]
+filtered_items = apply_filters(all_items, impact_filter, source_filter)
+
+m1, m2, m3, m4 = st.columns(4)
+m1.metric("수집 기사", f"{len(all_items)}건")
+m2.metric("표시 기사", f"{len(filtered_items)}건")
+m3.metric("긍정", f"{sum(1 for x in filtered_items if x.impact_score > 0.5)}건")
+m4.metric("부정", f"{sum(1 for x in filtered_items if x.impact_score < -0.5)}건")
+
+left, right = st.columns([1.1, 1.4])
+with left:
+    render_feed_list(filtered_items)
+with right:
+    render_detail(filtered_items)
