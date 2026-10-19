"""Test helper: seeded random fog-of-war games, with both players' views after every ply.

The referee it yields holds the true board. Only tests may look at it, to check what a player's
tracker believes; nothing in pairb's trackers or bots ever sees it.
"""
import random

from pairb.rules import GameReferee, Rules


def random_game(rules: Rules, seed: int, plies: int, fen: str | None = None):
    """Play up to `plies` moves from `fen` (the standard start if None), each drawn uniformly from
    the mover's legal moves with random.Random(seed), and stop early once the game is over.

    Yields (referee, mover, move, observations) after each ply, the game-ending one too:
    observations maps "white" and "black" to each player's view of the position the move led to.
    A position whose side to move has no legal moves also ends the game.
    """
    rng = random.Random(seed)
    referee = GameReferee(rules, fen)
    referee.reset(seed)
    for _ in range(plies):
        if referee.is_terminal():
            return
        mover = referee.current_player()
        moves = referee.observe(mover).legal_moves
        if not moves:
            return
        move = rng.choice(moves)
        referee.apply(move)
        yield referee, mover, move, {player: referee.observe(player) for player in ("white", "black")}
