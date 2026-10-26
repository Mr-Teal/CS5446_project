# How information changes a decision

This answers #19. Values are for player 0 (`payoff_perspective` is `player_0`). They come from `pair_a_prep/results/toy_reference.json`, which Pair A's LP solver `pair_a_prep/toy_games.py` writes. A 24 October rerun gave the same values for the four games below.

## Matching pennies

Player 0 plays H or T, then player 1 does. A match pays player 0 +1, otherwise -1.

**Hidden.** After "player 0 played H" or "player 0 played T", player 1 sees only that it must move. So both histories form one information set, `p1_hidden`: one decision for player 1. Any lean is exploited, so both mix 50/50. Value 0.0.

**Revealed.** Player 1 sees the coin, so the two histories are two information sets, `p1_after_H` and `p1_after_T`. Player 1 mismatches and always wins. Value -1.0. (Any mix gives player 0 -1.0; the LP returns H.)

## Coin game

A coin lands heads with probability 0.75. Only player 0 moves, guessing it: +1 if right, -1 if wrong.

**Hidden.** Histories "heads" and "tails" look the same to player 0, so both are in `guess_hidden`: one guess for both. Player 0's belief is the coin's odds, so H is best: 0.75 - 0.25 = 0.5.

**Revealed.** Player 0 sees the coin: two information sets, `guess_H` and `guess_T`, and every guess is right. Value 1.0.

## Table from `make_information_table.py`

| Game | Who sees what | Value for player 0 | Player 0 strategy | Player 1 strategy |
| --- | --- | --- | --- | --- |
| Matching pennies, hidden | Player 1 cannot see the coin | 0.0 | p0: H 0.5, T 0.5 | p1_hidden: H 0.5, T 0.5 |
| Matching pennies, revealed | Player 1 sees the coin | -1.0 | p0: H | p1_after_H: T; p1_after_T: H |
| Coin game, hidden | Player 0 cannot see the coin | 0.5 | guess_hidden: H | no move |
| Coin game, revealed | Player 0 sees the coin | 1.0 | guess_H: H; guess_T: T | no move |

## For the report

What a player sees changes the value (0.0 vs -1.0; 0.5 vs 1.0). It also changes the decision: one choice for both histories, or one per history. A belief over hidden states records which histories a player cannot tell apart, and how likely each is.

Teal confirmed on #19 that `p1_hidden` and `guess_hidden` match the code.
