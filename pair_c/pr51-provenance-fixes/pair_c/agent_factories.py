"""Example factory that loads Pair B's OnePlyBot with a configured scorer.

For another Agent, copy the class and replace the marked ``load_model`` and ``reset_game`` bodies.
Its required interface and relevant source files are documented there.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping

from pairb.bot import OnePlyBot
from pairb.material import MaterialEvaluator
from pairb.stockfish import StockfishEvaluator

from pair_c.agent_api import project_path


class Factory:
    """Load one independent Agent for one player section."""

    def __init__(self, settings: Mapping[str, str]):
        """Store this player's configuration for ``load_model``.

        Input:
            ``settings`` is the mapping of string options from one
            ``[player_a]`` or ``[player_b]`` INI section. Player A and Player B
            are instantiated separately and therefore load separate models.

        Return value:
            ``None``. This initializer is framework code; users should leave it
            unchanged and implement ``load_model`` and ``reset_game`` below.
        """
        self.settings = settings

    def load_model(self):
        """Load and return the Agent that will play this side.

        Input:
            No explicit argument. Read this player's options from
            ``self.settings``. In this Pair B example, ``scorer_id`` selects a
            scorer, ``checkpoint_path`` is the exact checkpoint file for a
            network scorer, ``device`` selects inference hardware, and
            ``stockfish_path`` locates Stockfish. Another Agent may define
            completely different options.

        Return value:
            A ready-to-play Agent object. Pair C passes it directly to
            ``fow_shared.evaluation.play_game``, which expects:

            * ``name``: a string recorded with the moves.
            * ``reset(player, seed) -> None``: initialize a game for ``white``
              or ``black`` using the supplied integer seed.
            * ``act(turn: AgentInput) -> Decision``: choose and return a move.

            ``Decision.move`` must be in ``turn.observation.legal_moves`` and
            ``Decision.root_policy`` must give a probability for every legal
            move. The shared types are defined in ``fow_shared/contracts.py``;
            the Agent protocol is in ``fow_shared/interfaces.py``.

        User-owned work:
            Replace the code between the markers in both user-owned methods.
            Load your checkpoint and create your Agent. Keep references to
            scorer state that reset_game must clear before each game.
            Return the Agent directly if it already has the
            required interface; otherwise adapt it before returning. Do not
            return a path, checkpoint dictionary, or uninitialized model.

        For the exact call sequence, read ``play_game`` in
        ``fow_shared/evaluation.py``. For the fields in ``turn`` and the
        requirements on ``Decision``, read ``AgentInput`` and ``Decision`` in
        ``fow_shared/contracts.py``.
        """
        # --- Your Code Start Here ---
        scorer_id = self.settings.get("scorer_id", "").strip()
        if not scorer_id:
            raise ValueError("Factory requires scorer_id in the player section")
        expected_depth = {"material": 0, "stockfish-d1": 1, "stockfish-d11": 11,
                          "network1": 1, "belief": 1}.get(scorer_id)
        if expected_depth is not None:
            configured_depth = int(self.settings.get("leaf_depth", str(expected_depth)))
            if configured_depth != expected_depth:
                raise ValueError(f"{scorer_id} requires leaf_depth={expected_depth}; "
                                 f"configured {configured_depth}. Search depth is separate.")

        stockfish_setting = self.settings.get("stockfish_path", "stockfish").strip()
        stockfish_file = project_path(stockfish_setting)
        if stockfish_file.is_file():
            stockfish_path = str(stockfish_file.resolve())
        else:
            executable = shutil.which(stockfish_setting)
            stockfish_path = str(Path(executable).resolve()) if executable else stockfish_setting
        device = self.settings.get("device", "").strip() or None
        checkpoint_setting = self.settings.get("checkpoint_path", "").strip()
        checkpoint_path = None

        if scorer_id == "network1":
            if not checkpoint_setting:
                raise ValueError("network1 requires checkpoint_path pointing to a .pt file")
            from pairb.network_evaluator import NetworkEvaluator

            checkpoint_path = project_path(checkpoint_setting).resolve()
            scorer = NetworkEvaluator.from_checkpoint(
                checkpoint_path,
                stockfish_path=stockfish_path,
                device=device,
                new_game_each_call=False,
            )
        elif scorer_id == "belief":
            if not checkpoint_setting:
                raise ValueError("belief requires checkpoint_path pointing to a .pt file")
            from pairb.belief_evaluator import BeliefNetworkEvaluator

            checkpoint_path = project_path(checkpoint_setting).resolve()
            scorer = BeliefNetworkEvaluator.from_checkpoint(
                checkpoint_path,
                stockfish_path=stockfish_path,
                device=device,
                new_game_each_call=False,
            )
        elif scorer_id == "material":
            scorer = MaterialEvaluator()
        elif scorer_id in ("stockfish-d1", "stockfish-d11"):
            depth = 1 if scorer_id == "stockfish-d1" else 11
            scorer = StockfishEvaluator(depth, path=stockfish_path, new_game_each_call=False)
        else:
            raise ValueError(f"Unknown scorer_id: {scorer_id!r}")

        self._scorer = scorer  # Retain the resources reset_game must clear.
        scorer.provenance_checkpoint_path = checkpoint_path
        # Keep the exact launch path, including PATH resolution, for provenance.
        # Pure belief networks may have no Stockfish instance at all.
        engine_scorer = (getattr(scorer, "stockfish", None)
                         if scorer_id in ("network1", "belief")
                         else scorer if scorer_id in ("stockfish-d1", "stockfish-d11") else None)
        if engine_scorer is not None:
            engine_scorer.provenance_executable_path = stockfish_path
        # Pair B already provides a compatible Agent implementation.
        return OnePlyBot(scorer)
        # --- Your Code Ends Here ---

    def reset_game(self) -> None:
        """Clear this player's game-specific scorer state before a game starts.

        Input:
            No explicit argument. Use resources saved by load_model. Pair C
            calls this once per attempted game, including the first, before
            play_game calls the Agent's reset(player, seed).

        Return value:
            None. The same factory, Agent and model are reused across games.

        User-owned work:
            Replace the code between the markers for your model. Clear any
            state that must not carry over from the previous game. If your
            scorer uses a hash, cache, or similar state, manage its lifetime
            yourself, including any reuse within one game. Stateless scorers
            may do nothing. Do not reload the model or create a new Agent here.
        """
        # --- Your Code Start Here ---
        scorer_id = self.settings.get("scorer_id", "").strip()
        if scorer_id in ("network1", "belief"):
            engine = self._scorer.stockfish
        elif scorer_id in ("stockfish-d1", "stockfish-d11"):
            engine = self._scorer
        else:  # MaterialEvaluator does not own an engine.
            engine = None
        if engine is not None:
            engine.new_game()
        # --- Your Code Ends Here ---
