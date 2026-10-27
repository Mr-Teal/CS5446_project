"""Example factory that creates Pair B's ParticleTracker with player-specific settings.

For another tracker, copy the class and replace the marked ``create_tracker`` body.
Its required interface and relevant source files are documented there.
"""

from __future__ import annotations

from typing import Any, Mapping

from fow_shared.interfaces import BeliefTracker


class Factory:
    """Create an independent belief tracker for one player in each game."""

    def __init__(self, settings: Mapping[str, str]):
        """Store this player's configuration for ``create_tracker``.

        Input:
            ``settings`` is the mapping of string options from one
            ``[player_a]`` or ``[player_b]`` INI section. Player A and Player B
            receive separate factory instances, even when using the same class.

        Return value:
            ``None``. This initializer is framework code; users should leave it
            unchanged and implement ``create_tracker`` below.
        """
        self.settings = settings

    def create_tracker(self, rules: Any, initial_fen: str | None = None) -> BeliefTracker:
        """Create and return a new tracker for this player's next game.

        Input:
            ``rules`` is the rules object used by this game's referee, with the
            interface currently defined in ``pair_b/src/pairb/rules.py``;
            fow_shared does not define a Rules construction interface. Adapt it here if
            your tracker expects a different rules interface, while preserving
            the same game rules. No referee or private game state is supplied.
            ``initial_fen`` is the public starting position, or ``None`` for
            the standard start. The runner supplies the same value to the
            referee and both tracker factories. Forward this argument to your
            tracker rather than reading a separate start from player settings.
            Read tracker-specific options from ``self.settings``. This Pair B
            example requires ``tracker_particles``, ``tracker_hypotheses`` and
            ``tracker_rebuild_tries``. Another tracker may use different options.

        Return value:
            A fresh BeliefTracker object, independent of all previous games and
            the other player. Pair C passes it directly to
            ``fow_shared.evaluation.play_game``, which expects:

            * ``reset(player, seed) -> None``: initialize a game for ``white``
              or ``black`` using the supplied integer seed.
            * ``update(observation, own_move=None) -> Belief``: update after
              every ply, including opponent moves and the terminal observation.

            The shared loop calls reset before the first update. own_move is
            this player's preceding move, or None at the start and after an
            opponent move. Use only observations, own moves and prior internal
            state; never inspect the true board. The protocol is defined in
            ``fow_shared/interfaces.py`` and the shared Belief, Hypothesis and
            Observation types are defined in ``fow_shared/contracts.py``.

        User-owned work:
            Replace the code between the markers. Parse and validate your
            tracker's own options, then construct a new tracker using the
            supplied rules and public start. Return it directly if it already
            has the required interface; otherwise adapt it before returning.
            Ensure its hypotheses contain the information your Agent needs:
            candidate_moves is optional in the shared contract, but an Agent
            may require a complete candidate path. Pair B's ParticleTracker
            leaves that field empty and suits its OnePlyBot example.

            The runner follows play_game's documented fresh-tracker lifecycle.
            Construction sets the rules and public start; reset initializes
            the player's color, random seed and tracking state. The factory
            is reused across games. No factory reset_game method is needed.

        For the exact call sequence, read ``play_game`` in
        ``fow_shared/evaluation.py``. Pair B's tracker implementation is in
        ``pair_b/src/pairb/tracker.py``.
        """
        # --- Your Code Start Here ---
        from pairb.tracker import ParticleTracker

        n_particles = int(self.settings["tracker_particles"])
        n_hypotheses = int(self.settings["tracker_hypotheses"])
        rebuild_tries = int(self.settings["tracker_rebuild_tries"])
        # ParticleTracker validates positive particle/hypothesis counts and
        # a non-negative rebuild budget in its constructor.
        return ParticleTracker(
            rules,
            n_particles=n_particles,
            n_hypotheses=n_hypotheses,
            rebuild_tries=rebuild_tries,
            initial_fen=initial_fen,
        )
        # --- Your Code Ends Here ---
