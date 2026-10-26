"""A UCI engine that never answers 'go', for the wall-clock limit tests (Bryan's probe on #18).

It answers the handshake (uci, isready) and accepts ucinewgame, setoption and position, so
StockfishEvaluator opens it like Stockfish. Then 'go' gets no reply at all, not even after 'stop',
as a stuck engine would behave. 'quit' ends it. Run it with the test's own Python:
[sys.executable, "-u", this file].
"""
import sys


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:  # stdin closed: the evaluator has gone
            return
        words = line.split()
        if not words:
            continue
        if words[0] == "uci":
            print("id name fake-hung-engine")
            print("id author pair-b tests")
            print("option name Threads type spin default 1 min 1 max 1")
            print("option name Hash type spin default 16 min 1 max 1024")
            print("option name MultiPV type spin default 1 min 1 max 500")
            print("uciok")
        elif words[0] == "isready":
            print("readyok")
        elif words[0] == "quit":
            return
        # ucinewgame, setoption, position, go, stop: no reply. 'go' never gets a bestmove.
        sys.stdout.flush()


if __name__ == "__main__":
    main()
