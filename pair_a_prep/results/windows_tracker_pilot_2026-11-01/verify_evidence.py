"""Verify published bytes and the explicit historical-profiler provenance mapping."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def verify():
    artifacts = json.loads((HERE / "artifact-sha256.json").read_text(encoding="utf-8"))
    for name, expected in artifacts.items():
        assert digest(HERE / name) == expected, name
    correction = json.loads((HERE / "provenance-correction.json").read_text(encoding="utf-8"))
    for name, expected in correction["measurements_preserved"].items():
        assert digest(HERE / name) == expected, name
    for key in ("historical_profiler", "windows_profiler"):
        entry = correction[key]
        assert digest(ROOT / entry["path"]) == entry["sha256"], key
    old = ROOT / "pair_a_prep/results/tracker_budget_profile_2026-10-31"
    historical = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in historical.items():
        assert digest(old / name) == expected, "historical: " + name
    execution = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    mapped = correction["historical_profiler"]["path"]
    for name, expected in execution["source_sha256"].items():
        path = ROOT / (correction["windows_profiler"]["path"] if name == mapped else name)
        actual = sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert actual == expected, "execution: " + name
    print(f"Verified {len(artifacts)} published artifacts, {len(historical)} historical files, "
          f"and {len(execution['source_sha256'])} execution sources with the recorded profiler mapping.")

if __name__ == "__main__":
    verify()
