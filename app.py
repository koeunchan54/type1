diff --git a/app.py b/app.py
index 66857ec0e24e78bcd322a0a37becbf42a1dc688d..6acd4284fc2e76f8c56dca5b86aa52099a9bda51 100644
--- a/app.py
+++ b/app.py
@@ -1,13 +1,268 @@
+import math
+import random
+from dataclasses import dataclass
+
+import chess
 import streamlit as st
 
-st.title("Paragraph Splitter")
+st.set_page_config(page_title="로컬 체스 (ELO 600)", layout="wide")
+
+PIECE_VALUES = {
+    chess.PAWN: 100,
+    chess.KNIGHT: 320,
+    chess.BISHOP: 330,
+    chess.ROOK: 500,
+    chess.QUEEN: 900,
+    chess.KING: 0,
+}
+
+UNICODE_PIECES = {
+    "P": "♙",
+    "N": "♘",
+    "B": "♗",
+    "R": "♖",
+    "Q": "♕",
+    "K": "♔",
+    "p": "♟",
+    "n": "♞",
+    "b": "♝",
+    "r": "♜",
+    "q": "♛",
+    "k": "♚",
+}
+
+
+@dataclass
+class MoveInsight:
+    san: str
+    quality: float
+    win_delta: float
+    best_san: str
+
+
+def init_state() -> None:
+    if "board" not in st.session_state:
+        st.session_state.board = chess.Board()
+    if "insights" not in st.session_state:
+        st.session_state.insights = []
+    if "last_ai_move" not in st.session_state:
+        st.session_state.last_ai_move = "-"
+
+
+def evaluate_board(board: chess.Board) -> float:
+    if board.is_checkmate():
+        return -10000 if board.turn == chess.WHITE else 10000
+    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_threefold_repetition():
+        return 0
+
+    score = 0
+    for piece_type, value in PIECE_VALUES.items():
+        score += len(board.pieces(piece_type, chess.WHITE)) * value
+        score -= len(board.pieces(piece_type, chess.BLACK)) * value
+
+    mobility = len(list(board.legal_moves))
+    score += 4 * mobility if board.turn == chess.WHITE else -4 * mobility
+    return score
+
+
+def minimax(board: chess.Board, depth: int, alpha: float, beta: float, maximizing_white: bool) -> float:
+    if depth == 0 or board.is_game_over():
+        return evaluate_board(board)
+
+    legal_moves = list(board.legal_moves)
+    random.shuffle(legal_moves)
+
+    if maximizing_white:
+        best = -math.inf
+        for move in legal_moves:
+            board.push(move)
+            best = max(best, minimax(board, depth - 1, alpha, beta, False))
+            board.pop()
+            alpha = max(alpha, best)
+            if beta <= alpha:
+                break
+        return best
+
+    best = math.inf
+    for move in legal_moves:
+        board.push(move)
+        best = min(best, minimax(board, depth - 1, alpha, beta, True))
+        board.pop()
+        beta = min(beta, best)
+        if beta <= alpha:
+            break
+    return best
+
+
+def win_probability(eval_cp: float) -> float:
+    return 1 / (1 + math.exp(-eval_cp / 400))
+
+
+def score_move(board: chess.Board, move: chess.Move, depth: int = 1) -> float:
+    board.push(move)
+    score = minimax(board, depth, -math.inf, math.inf, board.turn == chess.WHITE)
+    board.pop()
+    return score
+
+
+def ai_pick_move(board: chess.Board) -> chess.Move:
+    candidates = []
+    for move in board.legal_moves:
+        score = score_move(board, move, depth=1)
+        candidates.append((move, score))
+
+    candidates.sort(key=lambda x: x[1], reverse=board.turn == chess.WHITE)
+
+    # ELO 600 느낌: 좋은 수를 자주 두되, 20% 정도는 실수를 허용
+    blunder_roll = random.random()
+    if blunder_roll < 0.2 and len(candidates) > 3:
+        low_pool = candidates[len(candidates) // 2 :]
+        return random.choice(low_pool)[0]
+
+    top_n = min(4, len(candidates))
+    top_moves = candidates[:top_n]
+    move, _ = random.choice(top_moves)
+    return move
+
+
+def render_board(board: chess.Board) -> str:
+    files = "abcdefgh"
+    ranks = "87654321"
+    html = ["<div class='board-wrap'><div class='board'>"]
+
+    for rank in ranks:
+        for file in files:
+            square = chess.parse_square(f"{file}{rank}")
+            piece = board.piece_at(square)
+            symbol = UNICODE_PIECES.get(piece.symbol(), "") if piece else ""
+            is_light = (files.index(file) + ranks.index(rank)) % 2 == 0
+            square_class = "light" if is_light else "dark"
+            html.append(f"<div class='sq {square_class}'>{symbol}</div>")
+
+    html.append("</div></div>")
+    return "".join(html)
+
+
+def get_move_insight(board: chess.Board, move: chess.Move) -> MoveInsight:
+    legal_moves = list(board.legal_moves)
+    current_eval = evaluate_board(board)
+
+    scored = []
+    for candidate in legal_moves:
+        score = score_move(board, candidate)
+        scored.append((candidate, score))
+
+    scored.sort(key=lambda x: x[1], reverse=True)
+    best_move, best_score = scored[0]
+    played_score = next(score for candidate, score in scored if candidate == move)
+
+    quality = max(0.0, min(100.0, 100 - (best_score - played_score) / 8))
+    win_delta = (win_probability(played_score) - win_probability(current_eval)) * 100
+
+    san = board.san(move)
+    best_san = board.san(best_move)
+    return MoveInsight(san=san, quality=quality, win_delta=win_delta, best_san=best_san)
+
+
+init_state()
+board: chess.Board = st.session_state.board
+
+st.title("♟️ 혼자 즐기는 로컬 체스")
+st.caption("당신은 백(White), AI는 흑(Black)입니다. AI는 약 ELO 600 수준으로 설정되어 있습니다.")
+
+st.markdown(
+    """
+<style>
+.board-wrap {display:flex; justify-content:center; margin-top:8px;}
+.board {
+  display:grid;
+  grid-template-columns: repeat(8, 62px);
+  grid-template-rows: repeat(8, 62px);
+  border: 10px solid #2b2f33;
+  border-radius: 6px;
+  box-shadow: 0 4px 14px rgba(0,0,0,0.25);
+}
+.sq {
+  display:flex;
+  justify-content:center;
+  align-items:center;
+  font-size: 41px;
+  user-select:none;
+}
+.light {background:#f0d9b5;}
+.dark {background:#b58863;}
+.metric {
+  border:1px solid #2f3b45;
+  border-radius:8px;
+  padding:10px;
+  background:#11161c;
+}
+.move-pill {
+  border-left:4px solid #2ea043;
+  background:#0f1721;
+  padding:8px;
+  border-radius:6px;
+  margin-bottom:8px;
+}
+</style>
+""",
+    unsafe_allow_html=True,
+)
+
+left, right = st.columns([1.3, 1])
+
+with left:
+    st.markdown(render_board(board), unsafe_allow_html=True)
+
+with right:
+    st.subheader("체스.com 스타일 분석 패널")
+    if st.session_state.insights:
+        latest = st.session_state.insights[-1]
+        st.markdown(f"<div class='metric'><b>최근 수:</b> {latest.san}<br><b>승리 기여도:</b> {latest.win_delta:+.2f}%<br><b>수 정확도:</b> {latest.quality:.1f}%<br><b>추천 수:</b> {latest.best_san}</div>", unsafe_allow_html=True)
+        st.progress(int(latest.quality))
+    else:
+        st.info("첫 수를 두면 승리 기여도/정확도 분석이 표시됩니다.")
+
+    st.markdown(f"**AI 최근 수:** `{st.session_state.last_ai_move}`")
+
+    st.markdown("#### 내 수 로그")
+    if st.session_state.insights:
+        for idx, insight in enumerate(st.session_state.insights, start=1):
+            st.markdown(
+                f"<div class='move-pill'><b>{idx}. {insight.san}</b><br>기여도 {insight.win_delta:+.2f}% · 정확도 {insight.quality:.1f}%</div>",
+                unsafe_allow_html=True,
+            )
+    else:
+        st.caption("아직 기록이 없습니다.")
+
+if board.is_game_over():
+    result = board.result(claim_draw=True)
+    if result == "1-0":
+        st.success("게임 종료: 당신의 승리입니다!")
+    elif result == "0-1":
+        st.error("게임 종료: AI 승리입니다.")
+    else:
+        st.warning("게임 종료: 무승부입니다.")
+else:
+    legal_moves = list(board.legal_moves)
+    move_options = [board.san(move) for move in legal_moves]
+    selected_san = st.selectbox("당신의 수 선택", move_options)
+
+    if st.button("수 두기", type="primary"):
+        chosen_move = legal_moves[move_options.index(selected_san)]
+        insight = get_move_insight(board, chosen_move)
+        st.session_state.insights.append(insight)
+        board.push(chosen_move)
 
-text = st.text_area("Paste text", height=200)
+        if not board.is_game_over():
+            ai_move = ai_pick_move(board)
+            st.session_state.last_ai_move = board.san(ai_move)
+            board.push(ai_move)
 
-if st.button("Split"):
-  paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
-  st.write(f"Number of Paragraphs: {len(paragraphs)}")
+        st.rerun()
 
-  for i, p in enumerate(paragraphs, start=1):
-    st.markdown(f"**Paragraph {i}**")
-    st.write(p)
+if st.button("새 게임"):
+    st.session_state.board = chess.Board()
+    st.session_state.insights = []
+    st.session_state.last_ai_move = "-"
+    st.rerun()
