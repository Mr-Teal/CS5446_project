# Chessboard viewer

This is the actual chessboard interface. The separate `toy_explorer.html`
visualizes solver internals; it is not a chessboard.

## Start

### First-time setup for teammates

Run these commands from your local repository checkout. The viewer must be
committed and pushed to `pair-a/rules-interface` before teammates can fetch it.

```powershell
git fetch origin
git switch pair-a/rules-interface
git pull --ff-only
python -m venv pair_a_prep/.venv
pair_a_prep/.venv/Scripts/python -m pip install -e .
pair_a_prep/.venv/Scripts/python -m pair_a_prep.board_viewer
```

Use Python 3.9 or newer. Creating the virtual environment and installing the
shared package are first-time steps; an existing environment with the shared
dependencies can be reused. No PowerShell environment activation is necessary.
If the viewer has since merged into `main`, use that branch instead.

Once the terminal prints the viewer address, open **http://127.0.0.1:8766/**
in your browser. `127.0.0.1` always means **your own computer**: a teammate
must start their own server and cannot use this address to reach someone
else's running viewer. Each locally started server has an independent game.

On macOS or Linux, use `python3` to create the environment, then
`pair_a_prep/.venv/bin/python` instead of the Windows `Scripts/python` path.

### Subsequent launches

From the repository root, with the shared dependencies installed:

```powershell
python -m pair_a_prep.board_viewer
```

If using the preparation virtual environment:

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.board_viewer
```

Open **http://127.0.0.1:8766/** in Edge, Chrome or Firefox. Keep the terminal
running; Ctrl+C stops the server. Use `--port 8767` if the default port is busy.
Fog Lab defaults to 8765, so both apps can run with their respective defaults.
Do not open the asset HTML directly: it needs the local Python rules API.
No Stockfish, PyTorch, external service, new UI package or internet is required.

## Use

- Click a piece, then a highlighted destination. Promotions offer all four
  choices. All moves are checked by the existing `RulesAdapter` in Python.
- Choose Full board, White's fog view or Black's fog view. Black's board is
  rotated for normal chessboard viewing. Hidden squares have a dark pattern.
- A fog view can move only when that player acts. Switch to the other player
  or Full board to play the reply. The page displays the current turn.
- Load a sample, then click Next or Play replay: opening to king capture,
  castling out of check, en passant, promotion, or threefold repetition.
- Navigate with the slider, history, Previous/Next or first/last buttons.
  Making a move in a past position replaces the future with a new branch.
- New standard game resets everything. A custom FEN starts a new history;
  it cannot restore earlier repetitions. Current FEN is shown only in Full view.

Last-move highlighting is shown only when the chosen view knows the move.
Only the losing player gets an own-piece capture notification in fog views.
The opponent's move coordinates are redacted in that view's history. The API
response also omits hidden pieces, opponent moves and full FEN in fog mode.

This is a single shared local debugging session. Tabs share state; a stale
tab's move is rejected and refreshed. It deliberately allows switching to the
full board and replaying history. It is not a secure human match platform.
Sessions are in memory and are lost when the server stops. This version does
not run Obscuro, generate beliefs or automatically select moves.

## Verification

`tests/test_board_viewer.py` checks actual board transitions, fog payloads,
replay branching, stale revisions, sample legality, repetition, promotion and
the HTTP boundary. Existing observation and move tests remain authoritative
for detailed FoW rules.
