"""Print the table in information_example.md from Pair A's toy reference values, with the standard library only.

    python3 pair_b/experiments/small_games/make_information_table.py [--reference pair_a_prep/results/toy_reference.json]   (from the repository root)

Every number comes from the JSON that pair_a_prep/toy_games.py writes: the LP solution of each game's full
normal form. Values are for player 0 (the file's payoff_perspective is "player_0"); player 1 gets the negative.
A strategy is printed per information set: an action's probability there is the total weight of the pure
policies that choose it. That is the behavior strategy, because in these games each player moves at most once.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "pair_a_prep" / "results" / "toy_reference.json"
GAMES = [  # (key in the JSON, row label, who sees what)
    ("matching_pennies_hidden", "Matching pennies, hidden", "Player 1 cannot see the coin"),
    ("matching_pennies_revealed", "Matching pennies, revealed", "Player 1 sees the coin"),
    ("coin_hidden", "Coin game, hidden", "Player 0 cannot see the coin"),
    ("coin_revealed", "Coin game, revealed", "Player 0 sees the coin"),
]
HEADER = ("Game", "Who sees what", "Value for player 0", "Player 0 strategy", "Player 1 strategy")


def number(x: float) -> str:
    return str(round(x, 3) + 0.0)  # + 0.0 turns -0.0 into 0.0


def strategy(policies: list, weights: list) -> str:
    """'infoset: action' when one action has all the weight, else 'infoset: H 0.5, T 0.5'; 'no move' if none."""
    if len(policies) != len(weights):
        raise ValueError("need one weight per pure policy")
    infosets = {}
    for policy, weight in zip(policies, weights):
        for infoset, action in policy.items():
            actions = infosets.setdefault(infoset, {})
            actions[action] = actions.get(action, 0.0) + weight
    parts = []
    for infoset, actions in infosets.items():
        played = [(a, p) for a, p in actions.items() if round(p, 3) > 0]
        if len(played) == 1:
            parts.append(f"{infoset}: {played[0][0]}")
        else:
            parts.append(f"{infoset}: " + ", ".join(f"{a} {number(p)}" for a, p in played))
    return "; ".join(parts) or "no move"


def rows(report: dict) -> list:
    if report.get("payoff_perspective") != "player_0":
        raise ValueError("expected values from player 0's view (payoff_perspective 'player_0')")
    out = []
    for key, label, sees in GAMES:
        game = report["games"][key]
        if abs(game["profile_value"] - game["expected_value"]) > 1e-8 or game["nash_gap"] > 1e-8:
            raise ValueError(f"{key} is not solved to its expected value")
        out.append((label, sees, number(game["profile_value"]),
                    strategy(game["row_pure_policies"], game["row_strategy"]),
                    strategy(game["column_pure_policies"], game["column_strategy"])))
    return out


def table(report: dict) -> str:
    lines = [HEADER, ("---",) * len(HEADER), *rows(report)]
    return "\n".join("| " + " | ".join(cells) + " |" for cells in lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    args = parser.parse_args(argv)
    print(table(json.loads(args.reference.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
