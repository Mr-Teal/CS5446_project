"""Pair A's search agent as a Fog Lab bot (pairb.lab.pair_a_bot): the "pair-a-subgame" entry of BOTS.

These tests play real opening moves with Teal's rules, Pair A's ChessSubgameAgent and its browser tracker,
over piece-value spies that count their closes. The search is given 300 ms instead of 5 s where it really runs. The
whole module is skipped on a checkout without pair_a_prep.
"""
import functools
import http.client
import json
import threading

import pytest

# The guards name the submodules the bot imports, not the package: an untracked pair_a_prep/ folder would import as an
# empty package.
pytest.importorskip("pair_a_prep.chess_subgame_agent")
pytest.importorskip("pair_a_prep.evaluation_factories")

from fow_shared.contracts import Decision
from no_torch import PAIR_B
from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
from pairb.lab import server
from pairb.lab.pair_a_bot import make_pair_a_agent, make_pair_a_tracker, unavailable_reason
from pairb.lab.scorers import ScorerOptions
from pairb.lab.server import LabApp, make_server
from pairb.lab.session import BOTS, BotSpec, GameOptions, Session
from pairb.material import MaterialEvaluator
from pairb.rules import StandinRules, TealRules

PAIR_A = "pair-a-subgame"
LABEL = "Pair A subgame agent (5 s search)"
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"


class Spy:
    """Piece values that count their closes."""

    def __init__(self):
        self._inner = MaterialEvaluator()
        self.name = self._inner.name
        self.closes = 0

    def evaluate_children(self, fen):
        return self._inner.evaluate_children(fen)

    def close(self):
        self.closes += 1


@pytest.fixture
def quick_pair_a(monkeypatch):
    """A BOTS entry for one test: Pair A's bot with 300 ms per move instead of 5 s."""
    monkeypatch.setitem(BOTS, "pair-a-quick", BotSpec(LABEL, functools.partial(make_pair_a_agent, budget_ms=300),
                                                     make_pair_a_tracker, unavailable_reason))
    return "pair-a-quick"


def session_for(rules, bot, **options):
    """A session over piece-value spies with 4 guesses, the human playing Black, so the bot moves first."""
    return Session(GameOptions(bot=bot, human="black", guesses=4, **options), rules, Spy(), Spy())


# Catches: the entry missing, renamed or relabelled, and Pair B's bot no longer first (the page's default).
def test_the_registry_offers_pair_a_after_pair_b():
    assert list(BOTS)[:2] == ["pairb-one-ply", PAIR_A]
    assert BOTS[PAIR_A].label == LABEL
    assert GameOptions().bot == "pairb-one-ply"
    assert unavailable_reason(TealRules()) is None
    assert "--rules teal" in unavailable_reason(StandinRules())


# Catches: an agent or tracker that does not fit the session (no move, an illegal one, a policy that is not over the
# legal moves), a record that names another bot, and an empty belief.
def test_pair_a_plays_the_first_move(quick_pair_a):
    session = session_for(TealRules(), quick_pair_a)
    record = session.record
    assert session.error is None, session.error
    assert record.bot == PAIR_A
    assert len(record.plies) == 1 and record.plies[0].player == "white"
    legal = record.start_observations["white"]["legal_moves"]
    assert record.plies[0].move in legal
    turn = record.bot_turns[0]
    assert turn.error is None
    assert turn.explanation["app_inspection"] is True
    assert set(turn.explanation["policy"]) == set(legal)
    assert turn.belief
    session.close()


# Catches: Pair A's bot started under rules it cannot replay histories with, a refusal that does not say what to do,
# and scorers left open (or closed twice) when the session refuses.
def test_pair_a_refuses_other_rules_and_closes_both_scorers():
    scorer, inspector = Spy(), Spy()
    with pytest.raises(ValueError, match="--rules teal"):
        Session(GameOptions(bot=PAIR_A, human="black", guesses=4), StandinRules(), scorer, inspector)
    assert (scorer.closes, inspector.closes) == (1, 1)


# Catches: a start the agent was not told about, since the agent is made from the scorer alone.
def test_pair_a_refuses_a_start_other_than_the_standard_one():
    scorer, inspector = Spy(), Spy()
    with pytest.raises(ValueError, match="standard start"):
        Session(GameOptions(bot=PAIR_A, human="black", guesses=4, start_fen=KING_CAPTURE), TealRules(), scorer,
                inspector)
    assert (scorer.closes, inspector.closes) == (1, 1)


# Catches: the agent handed Fog Lab's 60 s instead of its own 5 s.
def test_the_agent_gets_at_most_five_seconds(monkeypatch):
    budgets = []

    def act(self, turn):
        budgets.append(turn.time_budget_ms)
        moves = turn.observation.legal_moves
        return Decision(moves[0], {move: 1 / len(moves) for move in moves})

    monkeypatch.setattr(ChessSubgameAgent, "act", act)
    session = session_for(TealRules(), PAIR_A)
    assert session.error is None, session.error
    assert budgets == [5000]
    session.close()


# ---- the server ----

@pytest.fixture
def start_lab(tmp_path):
    """start_lab(rules) -> call(method, path, body=None) -> (status, JSON) against a running server."""
    started = []

    def start(rules):
        app = LabApp(PAIR_B.parent, ScorerOptions(checkpoints=tmp_path / "no-checkpoints"), rules,
                     home=tmp_path / "fog_lab")
        httpd = make_server(app, port=0)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        started.append((app, httpd, thread))

        def call(method, path, body=None):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=120)
            try:
                connection.request(method, path, None if body is None else json.dumps(body))
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        return call

    yield start
    for app, httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=30)
        app.close()


# Catches: a bot list that is missing, out of order, or that offers Pair A's bot under rules it cannot play by.
@pytest.mark.parametrize("rules", [TealRules, StandinRules])
def test_config_lists_the_bots_with_their_availability(start_lab, rules):
    status, config = start_lab(rules())("GET", "/api/config")
    assert status == 200
    assert config["default_bot"] == "pairb-one-ply"
    assert [row["id"] for row in config["bots"]][:2] == ["pairb-one-ply", PAIR_A]
    rows = {row["id"]: row for row in config["bots"]}
    assert rows["pairb-one-ply"] == {"id": "pairb-one-ply", "label": BOTS["pairb-one-ply"].label, "available": True,
                                     "reason": None}
    expected = unavailable_reason(rules())
    assert rows[PAIR_A] == {"id": PAIR_A, "label": LABEL, "available": expected is None, "reason": expected}


# Catches: a game opened (and its scorers started) for a bot that cannot play, and a refusal without the reason.
def test_new_game_refuses_an_unavailable_bot(start_lab, monkeypatch):
    opened = []
    monkeypatch.setattr(server, "open_scorer", lambda scorer_id, opts: opened.append(scorer_id) or Spy())
    status, refused = start_lab(StandinRules())("POST", "/api/games", {"scorer": "material", "bot": PAIR_A})
    assert status == 400 and "--rules teal" in refused["error"]
    assert opened == []


def test_browser_tracker_preserves_exact_history_until_pruning_then_reports_approximation():
    from pair_a_prep.belief_tracker import BeliefTracker
    from pair_a_prep.rules_adapter import RulesAdapter
    from pairb.lab.pair_a_bot import BrowserHistoryTracker

    rules = RulesAdapter()
    fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
    plain = BeliefTracker(fen, sample_size=1, max_candidates=None, backend="python")
    wrapped = BrowserHistoryTracker(
        BeliefTracker(fen, sample_size=1, max_candidates=None, backend="python"), 1)
    for tracker in (plain, wrapped):
        tracker.reset("white", 17)
    state = rules.initial_state(fen)
    for move in (None, "a1b1", "h8g8"):
        own = move if move == "a1b1" else None
        if move is not None:
            state = rules.apply_move(state, move)
        observation = rules.observe(state, "white")
        assert wrapped.update(observation, own) == plain.update(observation, own)
        assert wrapped.support_complete
        assert wrapped.prunes == 0
    assert wrapped.state_count == 3
    # An own move preserves each represented history, so pruning can be checked
    # without assuming the randomly retained hidden move was the referee's.
    state = rules.apply_move(state, "b1a1")
    belief = wrapped.update(rules.observe(state, "white"), "b1a1")
    assert wrapped.prunes == 1
    assert not wrapped.support_complete
    assert not wrapped.last_update.support_complete
    assert belief.population_size is None
    assert belief.weighting == "uniform_over_returned_histories"
    assert wrapped.population_size == 1
    assert len(belief.hypotheses[0].candidate_moves) == 3
    wrapped.reset("white", 17)
    assert wrapped.support_complete and wrapped.prunes == 0
    assert wrapped.state_count == 1


def test_browser_tracker_does_not_hide_a_failed_update():
    from pairb.lab.pair_a_bot import BrowserHistoryTracker

    class FailedTracker:
        state_count = 2

        def prune(self, count):
            self.state_count = count

        def update(self, observation, own_move):
            raise RuntimeError("no_candidate")

    tracker = BrowserHistoryTracker(FailedTracker(), 1)
    with pytest.raises(RuntimeError, match="no_candidate"):
        tracker.update(object())
    assert tracker.prunes == 1
