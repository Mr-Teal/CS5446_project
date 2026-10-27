"""Generate editable SVG slide assets from replay-checked chess evidence."""

from dataclasses import asdict
from html import escape
import json
from pathlib import Path

import chess
import chess.svg
import numpy as np

from fow_shared.contracts import AgentInput, Belief, HistoryEvent, Hypothesis
from fow_shared.values import fog_legal_moves
from .chess_search import build_chess_tree, expand_chess_tree, observation_key, reconstruct_roots
from .pcfr import PCFRPlus
from .rules_adapter import RulesAdapter


START = "7k/8/8/8/8/8/8/K7 w - - 0 1"
PATHS = (("a1b1", "h8g8"), ("a1b1", "h8g7"))
OUT = Path(__file__).with_name("presentation")


class ZeroLeaf:
    name = "presentation-zero-heuristic"

    def evaluate_children(self, fen):
        return {move.uci(): 0.0 for move in fog_legal_moves(chess.Board(fen))}


def evidence():
    rules, candidates, snapshots, histories = RulesAdapter(), [], [], []
    for index, path in enumerate(PATHS):
        state, history = rules.initial_state(START), []
        for move in path:
            observation = rules.observe(state, "white")
            own = move if rules.current_player(state) == "white" else None
            history.append(HistoryEvent(observation, own))
            state = rules.apply_move(state, move)
        snapshots.append(rules.observe(state, "white"))
        histories.append(tuple(history))
        candidates.append(Hypothesis(state.fen, 0.5, "slide-" + str(index), path))
    assert observation_key(snapshots[0]) == observation_key(snapshots[1])
    assert histories[0] == histories[1]
    turn = AgentInput(snapshots[0], Belief("white", 2, tuple(candidates)), 1000, histories[0])
    roots = reconstruct_roots(turn, rules, START)
    assert roots[0].memories[0] == roots[1].memories[0]
    assert roots[0].memories[1] != roots[1].memories[1]
    initial = rules.initial_state(START)
    view = rules.observe(initial, "white")
    initial_turn = AgentInput(view, Belief("white", 0, (Hypothesis(initial.fen, 1, "start"),)), 1000)
    tree = build_chess_tree(initial_turn, ZeroLeaf(), initial_fen=START, depth=1)
    solver = PCFRPlus(tree.root, schedule="alternating")
    solver.run(3)
    retained = {key: (item, item.regrets.copy(), solver._sums[p][key].copy())
                for p in (0, 1) for key, item in solver.minimizers[p].items()}
    grown = expand_chess_tree(tree, solver, ZeroLeaf())
    preserved = all(solver.minimizers[p][key] is item
                    and np.array_equal(item.regrets, regrets)
                    and np.array_equal(solver._sums[p][key], sums)
                    for p in (0, 1) for key, (item, regrets, sums) in retained.items()
                    if key in solver.minimizers[p])
    assert preserved and solver.rounds == 3
    return dict(start_fen=START, viewer="white", paths=PATHS,
                hypotheses=[asdict(h) for h in candidates], observation=asdict(snapshots[0]),
                same_private_history=True, own_memory_equal=True, opponent_memories_differ=True,
                weights_note="Illustrative equal weights over these two selected histories, not a full posterior.",
                growth=dict(before_nodes=tree.nodes, after_nodes=grown.nodes,
                            before_frontiers=tree.frontier_leaves, after_frontiers=grown.frontier_leaves,
                            solver_rounds=solver.rounds, old_minimizers_regrets_averages_preserved=preserved,
                            actions=list(tree.continuations[0].children),
                            new_infosets=len(solver.sets[1]), heuristic=ZeroLeaf.name))


def text(x, y, value, size=24, colour="#eaf0ff", weight="400"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{colour}" font-weight="{weight}">{escape(value)}</text>'


def line(x1, y1, x2, y2, colour="#76859f", dashed=False):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
            f'stroke-width="3"' + (' stroke-dasharray="9 7"' if dashed else '') + '/>')


def card(x, y, w, h, colour="#17253d", border="#38516e"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{colour}" stroke="{border}" stroke-width="2"/>'


def slide(title, subtitle, body, footer):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">'
            '<rect width="1600" height="900" fill="#0b1426"/>'
            '<g font-family="Segoe UI,Arial,sans-serif">'
            + text(65, 65, "FOG OF WAR CHESS / PAIR A", 19, "#70dac5", "600")
            + text(65, 125, title, 43, weight="700")
            + text(65, 171, subtitle, 23, "#b1bfd5") + body
            + line(65, 837, 1535, 837, "#293b55")
            + text(65, 872, footer, 17, "#a3b3cc") + '</g></svg>')


def board_svg(fen, x, y, observation=None):
    board = chess.Board(fen)
    fill = {}
    if observation is not None:
        visible = {chess.parse_square(square) for square in observation["visible_squares"]}
        for square in list(board.piece_map()):
            if square not in visible:
                board.remove_piece_at(square)
        fill = {square: "#26354c" for square in chess.SQUARES if square not in visible}
    return f'<g transform="translate({x},{y})">' + chess.svg.board(board, size=270, fill=fill) + '</g>'


def slide4(data):
    body = ""
    labels = [("REFEREE", "True state stays private"), ("OBSERVATION", "Visible pieces + legal moves"),
              ("BELIEF TRACKER", "Consistent history hypotheses"), ("AGENT", "One executable policy")]
    for i, (title, detail) in enumerate(labels):
        x = 65 + i * 385
        body += card(x, 215, 315, 115)
        body += text(x + 20, 253, title, 24, "#70dac5", "700") + text(x + 20, 298, detail, 19)
        if i < 3:
            body += line(x + 320, 270, x + 370, 270) + text(x + 348, 278, ">", 28)
    body += text(65, 382, "Same White evidence, two different hidden histories", 30, weight="600")
    boards = [("White's observation", data["hypotheses"][0]["fen"], data["observation"], 65),
              ("Hypothesis A: ...Kg8", data["hypotheses"][0]["fen"], None, 435),
              ("Hypothesis B: ...Kg7", data["hypotheses"][1]["fen"], None, 805)]
    for title, fen, view, x in boards:
        body += text(x, 427, title, 23, weight="600") + board_svg(fen, x, 445, view)
    body += card(1165, 425, 365, 295)
    for j, label in enumerate(["Shared private history", "Shared legal-move feedback", "Same White information set", "Different opponent memories"]):
        body += text(1185, 468 + j * 49, label, 20)
    body += text(1185, 690, "Unknown squares are shaded.", 19, "#70dac5")
    body += text(65, 767, "Evaluator: scores hypothetical candidates; labels and diagnostics are separate outputs.", 23)
    body += text(65, 804, "Exact history tracking is distinct from Pair B's bounded particle match configuration.", 21, "#b1bfd5")
    return slide("Hidden state stays behind the referee", "The player receives evidence, not the referee's true board.", body,
                 "Slide 4 | Replay-checked public kings fixture | Two selected hypotheses, not the full belief | Draft")


def slide5(data):
    body = card(65, 215, 670, 500) + card(790, 215, 745, 500)
    body += text(90, 260, "BEFORE: depth 1", 27, "#70dac5", "600")
    body += text(815, 260, "AFTER: depth 2", 27, "#70dac5", "600")
    def node(x, y, label, new=False, frontier=False):
        colour = "#f8c36a" if frontier else "#70dac5" if new else "#91b5ff"
        return (f'<circle cx="{x}" cy="{y}" r="20" fill="{colour}"/>'
                + text(x - 25, y - 35, label, 18))
    body += node(390, 350, "White") + node(1160, 350, "White")
    body += line(935, 505, 1385, 505, "#91b5ff", dashed=True)
    for index, (x, action) in enumerate(zip((190, 390, 590), data["growth"]["actions"])):
        body += line(390, 370, x, 485) + text((390 + x) / 2 - 20, 420, action, 18)
        body += node(x, 505, "estimate", frontier=True)
        right = 935 + index * 225
        body += line(1160, 370, right, 485) + text((1160 + right) / 2 - 25, 420, action, 18)
        body += node(right, 505, "Black", new=True)
        for delta in (-65, 0, 65):
            body += line(right, 525, right + delta, 615, "#70dac5")
            body += node(right + delta, 635, "", frontier=True)
    body += text(90, 675, "3 estimated frontiers", 22, "#b1bfd5")
    body += text(815, 690, "All 3 frontiers expanded; 9 new estimates", 22, "#b1bfd5")
    body += text(80, 758, "Preserved: old minimizers, regrets, averages, completed rounds", 29, "#91b5ff", "600")
    body += text(80, 805, "Growth fails -> keep the old tree. Initial build fails -> legal action fallback, no invented labels.", 23)
    return slide("Grow search without restarting its learning", "Our baseline grows the whole cut; the paper selects leaves with one-sided exploration.", body,
                 "Slide 5 | Chance parent omitted | Black nodes share one policy | Within-turn retention, cooperative deadlines | Draft")


def main():
    OUT.mkdir(exist_ok=True)
    data = evidence()
    (OUT / "evidence.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (OUT / "slide4.svg").write_text(slide4(data), encoding="utf-8")
    (OUT / "slide5.svg").write_text(slide5(data), encoding="utf-8")
    (OUT / "index.html").write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Pair A: slides 4-5 materials</title><style>
body{background:#0b1426;color:#eaf0ff;font:18px "Segoe UI",sans-serif;margin:25px}
nav{display:flex;gap:24px}a{color:#70dac5}object{width:100%;max-height:88vh;display:block;margin:25px 0}
@media print{body{margin:0}nav,p{display:none}object{height:100vh;max-height:none;break-after:page}}
</style><nav><a href="slide4.svg">Slide 4 SVG</a><a href="slide5.svg">Slide 5 SVG</a>
<a href="speaker_notes.md">Speaker notes</a><a href="evidence.json">Replay evidence</a></nav>
<p>Draft content/visuals. Speaker allocation is open. Open the SVGs directly to export or insert into slides.</p>
<object data="slide4.svg" type="image/svg+xml"></object><object data="slide5.svg" type="image/svg+xml"></object>
</html>''', encoding="utf-8")
    print(json.dumps(dict(same_private_history=data["same_private_history"], growth=data["growth"])))


if __name__ == "__main__":
    main()
