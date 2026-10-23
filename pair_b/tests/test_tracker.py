"""The honest particle tracker: a set of possible true positions, each one consistent with what the
player has seen.

The tracker may use only the observations it is given, its own moves and its own past state, never
a true board. These tests feed a tracker for each colour as fow_shared's play_game feeds them, the
game-ending view included (origin/main's play_game sends it too), and check the particles against
the referee's true board, which only a test may look at.
"""
import chess
import pytest

from fog_games import random_game, scripted_game
from fow_shared.contracts import Belief
from fow_shared.values import standard_fen
from pairb.rules import GameReferee, StandinRules, TealRules, teal_available
from pairb.tracker import ParticleTracker, TrackerLost

COLOURS = ("white", "black")
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# Small-material starts, so that 12 plies of uncapped tracking stay quick. Particles that reach one FEN
# by different paths are kept apart, so long walks of unseen kings or rooks (as in a rook-and-king
# ending) would grow to hundreds of thousands; these stay at a few thousand at most.
SMALL = ["4k3/3ppp2/8/8/8/8/3PPP2/4K3 w - - 0 1", "4k3/8/8/3q4/3Q4/8/8/4K3 w - - 0 1",
         "n6k/6pp/8/8/8/8/6PP/N6K w - - 0 1"]
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"  # Re2xe8 takes Black's king, which never sees the rook
KINGS_ONLY = "4k3/8/8/8/8/8/8/4K3 b - - 0 1"
KNIGHT_ON_C3 = "4k3/8/8/8/8/2n5/8/4K3 b - - 0 1"  # as KINGS_ONLY to White's eyes, until Nc3-e2
REBUILD_SEED = 1  # a game in which a one-particle tracker has to rebuild
# White's rook goes a1-b1-a1 while Black's king, unseen by White, goes e8-d8-e8, twice: the start
# position comes back a third time at ply 8, a threefold-repetition draw.
SHUFFLE = "4k3/8/8/8/8/8/8/R6K w - - 0 1"
SHUFFLE_MOVES = ["a1b1", "e8d8", "b1a1", "d8e8"] * 2
KNIGHT_TAKES_E2 = "4k3/8/8/8/8/2n5/4P3/4K3 b - - 0 1"  # Nc3xe2 takes the pawn on e2, which White sees
PAWN_ON_E2 = "4k3/8/8/8/8/8/4P3/4K3 b - - 0 1"  # as KNIGHT_TAKES_E2 to White's eyes, until the knight takes
# Each rules implementation this checkout has: Teal's adapter only where it can be imported, as in the Tests tab's
# stages that hold Teal's branch.
RULES = [pytest.param(StandinRules, id="standin"),
         pytest.param(TealRules, id="teal", marks=pytest.mark.skipif(
             not teal_available(), reason="Teal's rules adapter is not in this checkout"))]


def tracked(rules, seed, plies, fen=None, moves=None, **options):
    """A seeded random game (or the given moves) with a tracker for each colour, fed as
    fow_shared's play_game feeds them: reset(player, seed + index), the start view, then each
    player's view after every ply, the game-ending one too, with their own move when they made it.
    Yields (referee, trackers, observations, beliefs) after the start and after every ply."""
    start = GameReferee(rules, fen)
    trackers = {player: ParticleTracker(rules, initial_fen=fen, **options) for player in COLOURS}
    for index, player in enumerate(COLOURS):
        trackers[player].reset(player, seed + index)
    observations = {player: start.observe(player) for player in COLOURS}
    yield start, trackers, observations, {p: trackers[p].update(observations[p]) for p in COLOURS}
    game = random_game(rules, seed, plies, fen) if moves is None else scripted_game(rules, moves, fen)
    for referee, mover, move, observations in game:
        yield referee, trackers, observations, {
            p: trackers[p].update(observations[p], own_move=move if p == mover else None) for p in COLOURS}


def assert_consistent(rules, tracker, player, observation):
    """The tracker has particles, and every one of them would have shown the player exactly this view."""
    particles = tracker.particles()
    assert particles
    assert all(rules.observe(state, player) == observation for state in particles)


def check_truth_always_among_particles(fen, seed, plies):
    """Uncapped, every particle fits the player's view, and the true position is one of them."""
    rules = StandinRules()
    for referee, trackers, observations, beliefs in tracked(rules, seed, plies, fen, n_particles=None):
        truth = standard_fen(referee.true_board())
        for player, tracker in trackers.items():
            assert truth in tracker.particle_fens()
            assert_consistent(rules, tracker, player, observations[player])
            assert tracker.exact and beliefs[player].population_size == len(tracker.particles())
    assert referee.ply == plies or referee.is_terminal()  # the whole game was tracked


# Catches: a start belief that is not the public start position, a weight or population size that is
# off, or flags that already claim a cap or a rebuild.
def test_start_belief_is_the_start_position():
    rules = StandinRules()
    referee = GameReferee(rules)
    for seed, player in enumerate(COLOURS):
        tracker = ParticleTracker(rules)
        tracker.reset(player, seed)
        belief = tracker.update(referee.observe(player))
        assert [(h.fen, h.weight) for h in belief.hypotheses] == [(START, 1.0)]
        assert (belief.player, belief.ply, belief.population_size, belief.weighting) == (player, 0, 1, "uniform")
        assert tracker.particle_fens() == [START]
        assert (tracker.capped, tracker.rebuilt, tracker.exact) == (False, False, True)


# Catches: the true position dropped while nothing is capped (a missed opponent move, a filter that
# compares the wrong thing, or a move given to the wrong tracker), a particle the player could tell
# apart from the truth, or a game-ending view refused.
@pytest.mark.parametrize("fen", SMALL)
@pytest.mark.parametrize("seed", [1, 2])
def test_truth_always_among_particles_uncapped(fen, seed):
    check_truth_always_among_particles(fen, seed, plies=12)


# Catches: the same from the standard start, where none of the opponent's first moves can be seen.
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_truth_among_particles_from_standard_start_uncapped(seed):
    check_truth_always_among_particles(None, seed, plies=4)


# Catches: a cap that is not applied, particles that no longer fit the view after sampling, a belief
# that is not a valid fow_shared Belief, or a population size still claimed for a sample.
def test_capped_particles_stay_consistent():
    rules = StandinRules()
    was_capped = dict.fromkeys(COLOURS, False)
    for referee, trackers, observations, beliefs in tracked(rules, 4, 30, n_particles=64):
        for player, tracker in trackers.items():
            assert_consistent(rules, tracker, player, observations[player])
            assert len(tracker.particles()) <= 64
            belief = beliefs[player]
            assert isinstance(belief, Belief)  # built, so it passed fow_shared's validation
            assert (belief.player, belief.ply) == (player, observations[player].ply)
            was_capped[player] = was_capped[player] or tracker.capped
            if was_capped[player]:
                assert belief.population_size is None and not tracker.exact
    assert all(was_capped.values())


# Catches: a rebuild that is never tried, that keeps positions contradicting the player's latest view,
# or that leaves the tracker calling its set exact.
def test_rebuild_keeps_beliefs_consistent():
    rules = StandinRules()
    rebuilds = 0
    for referee, trackers, observations, beliefs in tracked(rules, REBUILD_SEED, 20, n_particles=1):
        for player, tracker in trackers.items():
            assert_consistent(rules, tracker, player, observations[player])
            assert len(tracker.particles()) == 1
            if tracker.rebuilt:
                rebuilds += 1
                assert not tracker.exact and beliefs[player].population_size is None
    assert rebuilds > 0


# Catches: a rebuild that stops at its first fit, which can leave the tracker on one wrong particle for
# the rest of the game; it must collect up to min(n_hypotheses, n_particles) distinct particles.
# Seed 12: at ply 2, after Black's own d7d5, none of Black's 8 particles fits; the rebuild finds 8.
def test_a_rebuild_collects_several_particles():
    rules = StandinRules()
    for referee, trackers, observations, beliefs in tracked(rules, 12, 40, n_particles=8, n_hypotheses=8):
        rebuilt = [player for player, tracker in trackers.items() if tracker.rebuilt]
        if rebuilt:
            break
    else:
        pytest.fail("no update had to rebuild")
    player = rebuilt[0]
    tracker, belief = trackers[player], beliefs[player]
    assert 1 < len(tracker.particles()) <= 8
    assert_consistent(rules, tracker, player, observations[player])
    assert isinstance(belief, Belief) and belief.population_size is None  # built, so it passed validation
    assert len(belief.hypotheses) == len(tracker.particles())


# Catches: more guesses than asked for, weights that do not sum to one, guesses that are not
# particles, or FENs not written with standard_fen, which keeps en passant squares fog rules can use.
def test_belief_shape():
    rules = StandinRules()
    referee = GameReferee(rules)
    white, black = ParticleTracker(rules, n_hypotheses=5), ParticleTracker(rules, n_hypotheses=5)
    white.reset("white", 0)
    black.reset("black", 1)
    white.update(referee.observe("white"))
    black.update(referee.observe("black"))
    referee.apply("e2e4")
    white.update(referee.observe("white"), own_move="e2e4")
    belief = black.update(referee.observe("black"))
    # e3 is named although no Black pawn can take there; python-chess's default FEN would drop it
    assert white.particle_fens() == ["rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"]
    first_moves = set()  # Black sees none of White's 20 first moves
    for move in chess.Board().legal_moves:
        board = chess.Board()
        board.push(move)
        first_moves.add(board.fen(en_passant="fen"))
    assert len(black.particle_fens()) == 20 and set(black.particle_fens()) == first_moves
    assert black.particle_fens() == [standard_fen(rules.board(state)) for state in black.particles()]
    fens = [h.fen for h in belief.hypotheses]
    assert len(fens) == len(set(fens)) == 5 and set(fens) <= first_moves
    assert all(h.weight == pytest.approx(0.2) for h in belief.hypotheses)
    assert sum(h.weight for h in belief.hypotheses) == pytest.approx(1.0)
    assert (belief.population_size, belief.weighting, belief.ply) == (20, "uniform", 1)


# Catches: the view of the ply that ends the game refused, or answered with a wrong belief, for the
# side that took the king and for the side that lost it.
def test_the_game_ending_view_is_accepted():
    rules = StandinRules()
    referee = GameReferee(rules, KING_CAPTURE)
    trackers = {player: ParticleTracker(rules, initial_fen=KING_CAPTURE) for player in COLOURS}
    for index, player in enumerate(COLOURS):
        trackers[player].reset(player, index)
        trackers[player].update(referee.observe(player))
    referee.apply("e2e8")
    for player, own_move in (("white", "e2e8"), ("black", None)):
        view = referee.observe(player)
        assert view.terminal
        belief = trackers[player].update(view, own_move=own_move)
        assert [h.fen for h in belief.hypotheses] == ["4R3/8/8/8/8/8/8/4K3 b - - 0 1"]
        assert_consistent(rules, trackers[player], player, view)


# Catches: a threefold-repetition ending lost because particles that reach one FEN by different paths
# were merged into one history that does not repeat; the view that ends the game then raised
# TrackerLost, and play_game sends that view with no except around update. Uncapped, both trackers
# must keep the truth to the end, the draw included, and stay exact.
def test_threefold_repetition_ending_is_tracked_exactly():
    rules = StandinRules()
    for referee, trackers, observations, beliefs in tracked(rules, 0, 0, SHUFFLE, SHUFFLE_MOVES, n_particles=None):
        truth = standard_fen(referee.true_board())
        for player, tracker in trackers.items():
            assert truth in tracker.particle_fens()
            assert tracker.exact and isinstance(beliefs[player], Belief)  # built, so it passed validation
    assert referee.result() == ("draw", "threefold_repetition")
    assert all(view.terminal for view in observations.values())  # the game-ending views were fed


# Catches: hypotheses that reach one FEN by different paths given equal history_ids, which fow_shared's
# Belief refuses, or ids that differ between runs; a FEN that is unique in the belief keeps "". After
# ply 4 of the shuffle, Black's unseen king may be back on e8 by any of several walks.
def test_hypotheses_sharing_a_fen_get_distinct_history_ids():
    rules = StandinRules()

    def white_after_ply_4():
        *_, (referee, trackers, observations, beliefs) = tracked(
            rules, 0, 0, SHUFFLE, SHUFFLE_MOVES[:4], n_particles=None, n_hypotheses=64)
        return trackers["white"], beliefs["white"]

    tracker, belief = white_after_ply_4()
    fens = [h.fen for h in belief.hypotheses]
    assert len(fens) == len(tracker.particles()) and len(set(fens)) < len(fens)
    for h in belief.hypotheses:
        assert (h.history_id == "") == (fens.count(h.fen) == 1)
    assert white_after_ply_4()[1] == belief


# Catches: a game-ending view that no particle can reproduce raising instead of giving a belief. Both
# one-particle trackers in the shuffle (seeds 0 and 1) keep a guess at the other side's unseen moves that
# does not repeat the start position, so the draw fits nothing they can step to, and rebuilt positions
# have no history to repeat.
def test_a_game_ending_view_that_nothing_fits_still_gives_a_belief():
    rules = StandinRules()
    *_, (referee, trackers, observations, beliefs) = tracked(rules, 0, 0, SHUFFLE, SHUFFLE_MOVES, n_particles=1)
    for player, tracker in trackers.items():
        view = observations[player]
        assert view.terminal and tracker.rebuilt and not tracker.exact
        assert isinstance(beliefs[player], Belief) and beliefs[player].population_size is None
        for state in tracker.particles():
            seen = rules.observe(state, player)
            assert (seen.visible_squares, seen.visible_pieces) == (view.visible_squares, view.visible_pieces)


# Catches: when nothing fits a game-ending view, keeping positions the player could tell apart from it,
# or keeping nothing (and raising) when no position shows the same squares and pieces.
def test_with_nothing_fitting_a_game_ending_view_the_lookalikes_are_kept():
    rules = StandinRules()
    # A fifty-move draw: White's tracker is told the halfmove clock is 0, not 99 (neither side sees it).
    # Of Black's five king moves, the two along the back rank stay unseen; the rook on h7 sees the rest.
    referee = GameReferee(rules, "4k3/7R/8/8/8/8/8/4K3 b - - 99 80")
    tracker = ParticleTracker(rules, initial_fen="4k3/7R/8/8/8/8/8/4K3 b - - 0 80", rebuild_tries=0)
    tracker.reset("white", 0)
    tracker.update(referee.observe("white"))
    referee.apply("e8d8")
    assert referee.result() == ("draw", "fifty_move")
    belief = tracker.update(referee.observe("white"))
    assert tracker.rebuilt and isinstance(belief, Belief)
    assert sorted(tracker.particle_fens()) == ["3k4/7R/8/8/8/8/8/4K3 w - - 1 81", "5k2/7R/8/8/8/8/8/4K3 w - - 1 81"]
    # Black's tracker, told the rook starts on a2 and allowed no rebuild tries, cannot show the empty board
    # Black sees once its king is taken, and no position one move on does: it keeps every one of them.
    rook_on_a2 = "4k3/8/8/8/8/8/R7/4K3 w - - 0 1"
    referee = GameReferee(rules, KING_CAPTURE)
    tracker = ParticleTracker(rules, initial_fen=rook_on_a2, rebuild_tries=0)
    tracker.reset("black", 0)
    tracker.update(referee.observe("black"))
    referee.apply("e2e8")
    belief = tracker.update(referee.observe("black"))
    assert tracker.rebuilt and isinstance(belief, Belief)
    assert len(tracker.particles()) == len(rules.legal_moves(rules.initial_state(rook_on_a2)))


# Catches: histories kept apart after an irreversible move, when the rules can no longer tell them apart,
# which makes uncapped sets grow for nothing. After 2...Nb8, Black's knight may have gone out and back by
# several paths; after 3.e3, a pawn move, each FEN is one particle again.
def test_an_irreversible_move_merges_histories():
    rules = StandinRules()
    fens = [trackers["white"].particle_fens() for _, trackers, _, _ in
            tracked(rules, 0, 0, None, ["g1f3", "b8c6", "f3g1", "c6b8", "e2e3"], n_particles=None)]
    assert len(set(fens[4])) < len(fens[4])
    assert len(set(fens[5])) == len(fens[5]) > 1


# Catches: a rebuild that cannot explain a game-ending view. Black's tracker is told the rook starts
# on a2, from where it cannot take the king, so only moving the unseen rook explains the capture.
# Also: random placement tried although moving pieces found some positions. In 30 tries moving finds
# fewer than 8; placing at random would then add positions with the rook anywhere (Black sees nothing).
def test_a_rebuild_can_explain_the_game_ending_view():
    rules = StandinRules()
    referee = GameReferee(rules, KING_CAPTURE)
    tracker = ParticleTracker(rules, initial_fen="4k3/8/8/8/8/8/R7/4K3 w - - 0 1", rebuild_tries=30)
    tracker.reset("black", 0)
    tracker.update(referee.observe("black"))
    referee.apply("e2e8")
    view = referee.observe("black")
    tracker.update(view)
    assert tracker.rebuilt and not tracker.exact
    assert 1 <= len(tracker.particles()) < 8
    assert_consistent(rules, tracker, "black", view)
    for fen in tracker.particle_fens():
        board = chess.Board(fen)
        assert board.piece_at(chess.E8) == chess.Piece(chess.ROOK, chess.WHITE) and board.king(chess.BLACK) is None


# Catches: a rebuild without its fallback. White's tracker is told Black has only a king, so when a
# Black knight appears on e2 no moving of unseen pieces explains it; placing pieces around what the
# view shows does. Also: a fallback that stops at its first fit, or collects more than n_hypotheses
# (8 here, below the cap of 256) distinct positions.
def test_rebuild_falls_back_to_placing_pieces_at_random():
    rules = StandinRules()
    referee = GameReferee(rules, KNIGHT_ON_C3)
    tracker = ParticleTracker(rules, initial_fen=KINGS_ONLY, rebuild_tries=20)
    tracker.reset("white", 0)
    tracker.update(referee.observe("white"))
    referee.apply("c3e2")
    view = referee.observe("white")
    belief = tracker.update(view)
    assert tracker.rebuilt and belief.population_size is None
    assert len(tracker.particles()) == 8
    assert_consistent(rules, tracker, "white", view)
    for fen in tracker.particle_fens():
        board = chess.Board(fen)
        assert board.piece_at(chess.E2) == chess.Piece(chess.KNIGHT, chess.BLACK) and board.king(chess.BLACK) is not None


# Spec 4.4: a particle shows the player the same capture notice as the view. Teal's rules give one
# (captured_own_piece_at), the stand-in's do not. White's tracker was told Black has no knight, so no
# particle explains Nc3xe2, and only the rebuild's second stage, placing Black's pieces around what the
# view shows, does. Catches: a rebuilt particle that is made from a FEN without the view's capture
# notice, which then fits no view that has one: under Teal's rules the tracker lost track (the final
# review saw it in games capped at 4 and 8 particles).
@pytest.mark.parametrize("make_rules", RULES)
def test_a_rebuilt_particle_keeps_the_capture_notice(make_rules):
    rules = make_rules()
    referee = GameReferee(rules, KNIGHT_TAKES_E2)
    tracker = ParticleTracker(rules, initial_fen=PAWN_ON_E2, rebuild_tries=20)
    tracker.reset("white", 0)
    tracker.update(referee.observe("white"))
    referee.apply("c3e2")
    view = referee.observe("white")
    assert view.captured_own_piece_at == ("e2" if isinstance(rules, TealRules) else None)
    belief = tracker.update(view)
    assert tracker.rebuilt and belief.population_size is None and len(tracker.particles()) == 8
    assert_consistent(rules, tracker, "white", view)
    for fen in tracker.particle_fens():
        assert chess.Board(fen).piece_at(chess.E2) == chess.Piece(chess.KNIGHT, chess.BLACK)


# Catches: the same loss in play. Capped at 8 particles with 200 tries per rebuild stage, these seeded
# random games rebuild often, and under Teal's rules a tracker lost track at a view with a capture notice:
# Black's at ply 17 (seed 1, notice on h5), White's at ply 22 (seed 4, on f2). The trackers must keep
# track for 30 plies, with every particle fitting its player's view, under either rules.
@pytest.mark.parametrize("make_rules", RULES)
@pytest.mark.parametrize("seed", [1, 4])
def test_capped_trackers_keep_track_through_rebuilds(make_rules, seed):
    rules = make_rules()
    rebuilds = 0
    for referee, trackers, observations, beliefs in tracked(rules, seed, 30, n_particles=8, n_hypotheses=8,
                                                            rebuild_tries=200):
        for player, tracker in trackers.items():
            assert_consistent(rules, tracker, player, observations[player])
            rebuilds += tracker.rebuilt
    assert rebuilds > 0 and referee.ply == 30


# Catches: a tracker that carries on without a consistent particle instead of raising TrackerLost, or
# that changes its particles when it gives up.
def test_tracker_lost_when_nothing_fits():
    rules = StandinRules()
    referee = GameReferee(rules, "4k3/8/8/8/8/8/3n4/4K3 w - - 0 1")  # White sees the knight at once
    tracker = ParticleTracker(rules, initial_fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    tracker.reset("white", 0)
    with pytest.raises(TrackerLost):
        tracker.update(referee.observe("white"))
    referee = GameReferee(rules, KNIGHT_ON_C3)
    tracker = ParticleTracker(rules, initial_fen=KINGS_ONLY, rebuild_tries=0)  # no rebuild allowed
    tracker.reset("white", 0)
    tracker.update(referee.observe("white"))
    before = tracker.particle_fens()
    referee.apply("c3e2")
    with pytest.raises(TrackerLost):
        tracker.update(referee.observe("white"))
    assert tracker.particle_fens() == before


# Catches: randomness not drawn from the tracker's own seeded generator (the global random module, or
# set and hash order). The bot's two-worlds test needs the same views, own moves and seed to give the
# same beliefs.
def test_same_views_moves_and_seed_give_the_same_beliefs():
    rules = StandinRules()
    start = GameReferee(rules).observe("black")
    plies = [(mover, move, views["black"]) for _, mover, move, views in random_game(rules, 5, 16)]

    def run(seed):
        tracker = ParticleTracker(rules, n_particles=8, n_hypotheses=4)
        tracker.reset("black", seed)
        seen = [(tracker.update(start), tracker.particle_fens())]
        for mover, move, view in plies:
            belief = tracker.update(view, own_move=move if mover == "black" else None)
            seen.append((belief, tracker.particle_fens()))
        return seen

    assert run(3) == run(3)
    assert run(3) != run(4)


# Catches: a tracker used before reset, fed the other player's view, or told of an own move that was
# not legal, carrying on instead of failing; and settings out of range.
def test_misuse_is_refused():
    rules = StandinRules()
    referee = GameReferee(rules)
    tracker = ParticleTracker(rules)
    with pytest.raises(RuntimeError, match="reset"):
        tracker.update(referee.observe("white"))
    tracker.reset("white", 0)
    with pytest.raises(ValueError, match="black"):
        tracker.update(referee.observe("black"))
    tracker.update(referee.observe("white"))
    referee.apply("e2e4")
    with pytest.raises(ValueError, match="e2e5"):
        tracker.update(referee.observe("white"), own_move="e2e5")
    with pytest.raises(ValueError):
        tracker.reset("red", 0)
    for bad in ({"n_particles": 0}, {"n_hypotheses": 0}, {"rebuild_tries": -1}):
        with pytest.raises(ValueError):
            ParticleTracker(rules, **bad)
