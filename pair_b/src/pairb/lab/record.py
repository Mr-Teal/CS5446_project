"""Game records for Fog Lab, and the page's view of a game.

A GameRecord holds everything one game produces: the moves, the true position after each move, both
players' observations, and for each bot turn its belief, explanation and inspection. The session fills it in
as the game is played, to_json and from_json save it as JSON and load it back, and view_state turns it into
the dictionary the page draws. Live play and stepping through a saved game draw the same screens because both
come from view_state.

A record holds plain JSON values only: dicts, lists, text, numbers, booleans and None. Observations are kept
as the dicts observation_json writes, so one form serves the record, the file and the page.

- to_json copies, and from_json builds a record from copies, so neither shares a list or a dict with the
  other side.
- from_json accepts what to_json writes. Another version, a missing key or a value of the wrong kind is a
  ValueError that says where the fault is ("plies[2].true_fen must be text") and never what the value was:
  a value may be a position, and an error message can reach the page. Keys it does not know are dropped.
  Everything view_state reads is checked, so a record that loads can be viewed at every step.
- options["human"] is the human's colour, "white" or "black" (resolved: never "random"), and options["fair"]
  means False when it is absent.
- PlyRecord.ply is the number of moves before that move, so plies[i].ply == i. BotTurn.ply is the number of
  moves before the bot's move, which is the ply of the move it played. A turn that failed has no move
  after it: its ply is len(plies), it stays in the saved game, and no step of view_state shows it as played.

view_state(record, upto) is the game after `upto` moves (default: all). The game is over only at the end of
a record that has a result, so stepping back through a finished game shows what live play showed at each
move: no result and no banner before the last one.

Fair game. Until a fair game ends the page may get only what the human is entitled to: their own
observations, their own moves, whose turn it is and whether the game is over. view_state(reveal=False) is
exactly that, the keys in HIDDEN_KEYS and no others, built from the human's side of the record alone. The
true position, the bot's observations and the bot's turns are not read at all.
"""
import copy
from dataclasses import dataclass

from fow_shared.contracts import Observation

VERSION = 1
COLOURS = ("white", "black")
HIDDEN_KEYS = ("fair", "human", "over", "ply", "result", "to_move", "you", "your_moves")


def observation_json(obs: Observation) -> dict:
    """An Observation as plain JSON values: lists for the tuples, a dict for the mapping. The halfmove clock
    (never shown here) and the schema version are left out."""
    return {
        "player": obs.player,
        "side_to_move": obs.side_to_move,
        "ply": obs.ply,
        "visible_squares": list(obs.visible_squares),
        "visible_pieces": dict(obs.visible_pieces),
        "legal_moves": list(obs.legal_moves),
        "captured_own_piece_at": obs.captured_own_piece_at,
        "terminal": obs.terminal,
        "outcome": obs.outcome,
    }


@dataclass
class PlyRecord:
    """One move: who made it, the true position after it and both players' observations after it."""

    ply: int  # the number of moves before this one
    player: str
    move: str
    true_fen: str  # fow_shared.values.standard_fen after the move
    observations: dict  # {"white": observation_json, "black": observation_json}, after the move

    def to_json(self) -> dict:
        return {"ply": self.ply, "player": self.player, "move": self.move, "true_fen": self.true_fen,
                "observations": copy.deepcopy(self.observations)}

    @classmethod
    def from_json(cls, data: dict, where: str = "ply record") -> "PlyRecord":
        """`where` names this record in a ValueError, such as "plies[2]"."""
        data = _object(data, where)
        return cls(ply=_field(data, "ply", where, *_INT),
                   player=_field(data, "player", where, *_COLOUR),
                   move=_field(data, "move", where, *_TEXT),
                   true_fen=_field(data, "true_fen", where, *_TEXT),
                   observations=_observations(_field(data, "observations", where, *_OBJECT), f"{where}.observations"))


@dataclass
class BotTurn:
    """One turn of the bot: what it believed, why it chose, and what the app saw by looking at the true board."""

    ply: int  # the number of moves before the bot's move
    belief: list[dict]  # [{"fen", "weight"}]
    population_size: int | None
    explanation: dict  # Explanation.to_json(), or {"policy", "values", "averages", "app_inspection": True}
    inspection: dict  # {"true_values", "best_on_true_board", "lost_by_not_knowing", "particles",
    #                    "truth_in_particles", "rebuilt", "capped"}
    error: str | None = None  # set when the turn raised: nothing was played

    def to_json(self) -> dict:
        return {"ply": self.ply, "belief": copy.deepcopy(self.belief), "population_size": self.population_size,
                "explanation": copy.deepcopy(self.explanation), "inspection": copy.deepcopy(self.inspection),
                "error": self.error}

    @classmethod
    def from_json(cls, data: dict, where: str = "bot turn") -> "BotTurn":
        """`where` names this turn in a ValueError, such as "bot_turns[1]". A missing "error" means None."""
        data = _object(data, where)
        return cls(ply=_field(data, "ply", where, *_INT),
                   belief=_copy(_field(data, "belief", where, *_BELIEF)),
                   population_size=_field(data, "population_size", where, *_or_null(_INT)),
                   explanation=_copy(_field(data, "explanation", where, *_OBJECT)),
                   inspection=_copy(_field(data, "inspection", where, *_OBJECT)),
                   error=_field(data, "error", where, *_or_null(_TEXT)) if "error" in data else None)


@dataclass
class GameRecord:
    """A whole game: how it was set up, where it started, every move and every bot turn, and how it ended."""

    options: dict  # the game's options; options["human"] is the human's colour
    rules: str  # the rules implementation's name
    scorer: str
    bot: str  # the bot's name
    start_fen: str
    start_observations: dict  # {"white": observation_json, "black": observation_json}, before any move
    plies: list[PlyRecord]
    bot_turns: list[BotTurn]
    result: dict | None  # {"winner", "reason"} once the game has ended
    version: int = VERSION

    def to_json(self) -> dict:
        """Plain JSON values, copied: lists and dicts, never tuples, so json.dumps and json.loads give it back."""
        return {
            "version": self.version,
            "options": copy.deepcopy(self.options),
            "rules": self.rules,
            "scorer": self.scorer,
            "bot": self.bot,
            "start_fen": self.start_fen,
            "start_observations": copy.deepcopy(self.start_observations),
            "plies": [ply.to_json() for ply in self.plies],
            "bot_turns": [turn.to_json() for turn in self.bot_turns],
            "result": copy.deepcopy(self.result),
        }

    @classmethod
    def from_json(cls, data: dict) -> "GameRecord":
        """The record that `data` (what json.loads gave for a saved game) describes.

        ValueError, naming the fault by its place and never by its value, for another version, for a missing
        key and for a value of the wrong kind.
        """
        data = _object(data, "")
        version = _field(data, "version", "", *_INT)
        if version != VERSION:
            raise ValueError(f"game record version {version} is not supported; this app reads version {VERSION}")
        options = _field(data, "options", "", *_OBJECT)
        _field(options, "human", "options", *_COLOUR)
        if "fair" in options:
            _field(options, "fair", "options", *_FLAG)
        plies = []
        for index, item in enumerate(_field(data, "plies", "", *_LIST)):
            ply = PlyRecord.from_json(item, f"plies[{index}]")
            if ply.ply != index:
                raise ValueError(f"plies[{index}].ply must be {index}")
            plies.append(ply)
        turns = [BotTurn.from_json(item, f"bot_turns[{index}]")
                 for index, item in enumerate(_field(data, "bot_turns", "", *_LIST))]
        result = _field(data, "result", "", *_RESULT)
        return cls(options=_copy(options),
                   rules=_field(data, "rules", "", *_TEXT),
                   scorer=_field(data, "scorer", "", *_TEXT),
                   bot=_field(data, "bot", "", *_TEXT),
                   start_fen=_field(data, "start_fen", "", *_TEXT),
                   start_observations=_observations(_field(data, "start_observations", "", *_OBJECT),
                                                    "start_observations"),
                   plies=plies, bot_turns=turns,
                   result=None if result is None else {"winner": result["winner"], "reason": result["reason"]},
                   version=version)


def view_state(record: GameRecord, upto: int | None = None, reveal: bool = True) -> dict:
    """The page's view of the game after `upto` moves (default: all of them), as plain JSON values that share
    nothing with the record. ValueError when `upto` is not a whole number from 0 to the number of moves, and
    when options["human"] is not a colour.

    reveal=False gives the keys of HIDDEN_KEYS and no others, the most a human may know of a fair game that
    is still going:
    - fair, human: from the options;
    - ply: how many moves have been made;
    - to_move: whose turn it is;
    - you: the human's own observation after those moves;
    - your_moves: the human's own moves so far, in UCI;
    - over, result: whether the game has ended, and how. The game is over only after the last move of a
      record that has a result, and the result is None until then.
    reveal=True adds what the human may see once the game is over, or at any time outside a fair game:
    - moves: every move so far, [{ply, player, move}];
    - bot: the bot's latest turn that has been played by now (BotTurn.ply < upto), as JSON, or None;
    - true_fen: the true position;
    - bot_view: the bot's observation after those moves;
    - rules, scorer, bot_name: the rules implementation, the scorer and the bot, by name.
    """
    total = len(record.plies)
    if upto is None:
        upto = total
    elif not _is_int(upto) or not 0 <= upto <= total:
        raise ValueError(f"ply must be a whole number from 0 to {total}")
    human = record.options.get("human")
    if human not in COLOURS:
        raise ValueError('options["human"] must be "white" or "black"')
    observations = record.start_observations if upto == 0 else record.plies[upto - 1].observations
    you = observations[human]
    over = record.result is not None and upto == total
    state = {
        "fair": bool(record.options.get("fair", False)),
        "human": human,
        "over": over,
        "ply": upto,
        "result": copy.deepcopy(record.result) if over else None,
        "to_move": you["side_to_move"],
        "you": copy.deepcopy(you),
        "your_moves": [ply.move for ply in record.plies[:upto] if ply.player == human],
    }
    if not reveal:
        return state
    # Nothing above this line has read the bot's side of the record.
    bot_colour = "black" if human == "white" else "white"
    played = [turn for turn in record.bot_turns if turn.ply < upto]
    state.update(
        moves=[{"ply": ply.ply, "player": ply.player, "move": ply.move} for ply in record.plies[:upto]],
        bot=max(played, key=lambda turn: turn.ply).to_json() if played else None,
        true_fen=record.start_fen if upto == 0 else record.plies[upto - 1].true_fen,
        bot_view=copy.deepcopy(observations[bot_colour]),
        rules=record.rules,
        scorer=record.scorer,
        bot_name=record.bot,
    )
    return state


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_pieces(value) -> bool:
    """Squares, each with its piece's letter, or None for a square seen empty."""
    return isinstance(value, dict) and all(
        isinstance(square, str) and (piece is None or isinstance(piece, str)) for square, piece in value.items())


def _is_belief(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(entry, dict) and isinstance(entry.get("fen"), str) and _is_number(entry.get("weight"))
        for entry in value)


def _is_result(value) -> bool:
    return value is None or (isinstance(value, dict) and isinstance(value.get("winner"), str)
                             and isinstance(value.get("reason"), str))


# What a value in a saved record may be: (a test for it, how an error message names what is wanted).
_TEXT = (lambda value: isinstance(value, str), "text")
_INT = (_is_int, "a whole number")
_NUMBER = (_is_number, "a number")
_FLAG = (lambda value: isinstance(value, bool), "true or false")
_LIST = (lambda value: isinstance(value, list), "a list")
_OBJECT = (lambda value: isinstance(value, dict), "an object")
_COLOUR = (lambda value: isinstance(value, str) and value in COLOURS, 'either "white" or "black"')
_TEXT_LIST = (lambda value: isinstance(value, list) and all(isinstance(item, str) for item in value), "a list of text")
_PIECES = (_is_pieces, "an object of squares and pieces")
_BELIEF = (_is_belief, 'a list of objects with text "fen" and a number "weight"')
_RESULT = (_is_result, 'null or an object with text "winner" and "reason"')


def _or_null(kind: tuple) -> tuple:
    test, wanted = kind
    return (lambda value: value is None or test(value)), f"{wanted} or null"


def _copy(value):
    """A deep copy of a value that is kept as it is. json.loads reads far more levels than a copy can follow,
    so a value nested too deeply is a bad record (ValueError), not a RecursionError."""
    try:
        return copy.deepcopy(value)
    except RecursionError:
        raise ValueError("a value in the record is nested too deeply to read") from None


def _object(data, where: str) -> dict:
    """`data` itself, which must be a dict. `where` is "" for the whole record."""
    if not isinstance(data, dict):
        raise ValueError(f"{where or 'the record'} must be an object")
    return data


def _field(data: dict, key: str, where: str, test, wanted: str):
    """data[key], which must be there and pass `test`. The ValueError names the place and what is wanted,
    never the value."""
    if key not in data:
        raise ValueError(f"{where or 'the record'} is missing '{key}'")
    if not test(data[key]):
        raise ValueError(f"{where + '.' if where else ''}{key} must be {wanted}")
    return data[key]


def _observations(data: dict, where: str) -> dict:
    """{"white": ..., "black": ...} of checked observation dicts."""
    return {colour: _observation(_field(data, colour, where, *_OBJECT), f"{where}.{colour}", colour)
            for colour in COLOURS}


def _observation(data: dict, where: str, colour: str) -> dict:
    """A checked copy of one observation dict with the nine keys observation_json writes, and no others.
    It must be `colour`'s own view: a record that files one player's view under the other would show the
    wrong player their own board."""
    view = {
        "player": _field(data, "player", where, *_COLOUR),
        "side_to_move": _field(data, "side_to_move", where, *_COLOUR),
        "ply": _field(data, "ply", where, *_INT),
        "visible_squares": list(_field(data, "visible_squares", where, *_TEXT_LIST)),
        "visible_pieces": dict(_field(data, "visible_pieces", where, *_PIECES)),
        "legal_moves": list(_field(data, "legal_moves", where, *_TEXT_LIST)),
        "captured_own_piece_at": _field(data, "captured_own_piece_at", where, *_or_null(_TEXT)),
        "terminal": _field(data, "terminal", where, *_FLAG),
        "outcome": _field(data, "outcome", where, *_or_null(_NUMBER)),
    }
    if view["player"] != colour:
        raise ValueError(f"{where}.player must be '{colour}'")
    return view
