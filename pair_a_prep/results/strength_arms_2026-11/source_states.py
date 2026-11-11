"""Did the code change while an arm ran? Reads the SHA-256 of every source file that the runner recorded in each
chunk's provenance.json (network arms only) and lists the distinct code states with the files that changed.

usage:  python3 source_states.py [folder with the extracted records]     (default: ./records)
Only code files are compared (.py, .cpp, .toml, .cfg, .so), excluding run outputs, checkpoints, docs and tests."""
import collections, glob, json, os
import sys
root = sys.argv[1] if len(sys.argv) > 1 else "records"
def code(files):
    keep = {}
    for k, v in files.items():
        if k.startswith(("pair_c/runs/", "pair_b/checkpoints/", ".git")) or "/docs/" in k or "/tests/" in k or "/results/" in k:
            continue
        if k.endswith((".py", ".cpp", ".toml", ".cfg", ".so")):
            keep[k] = v
    return keep
for arm in ("net-fe-s16", "netv2-fe-s16", "netv2-vs-fe-s16", "netv2-vs-fe-guard-s16"):
    sets = collections.OrderedDict()
    for folder in sorted(glob.glob(os.path.join(root, f"strength-{arm}-c*")), key=lambda f: int(f.rsplit("-c", 1)[1])):
        path = os.path.join(folder, "provenance.json")
        if not os.path.exists(path):
            continue
        p = json.load(open(path))
        files = code(p["sha256"]["source_files"])
        sets.setdefault(json.dumps(files, sort_keys=True), []).append((int(folder.rsplit("-c", 1)[1]), p["started_at"][:16]))
    sigs = list(sets)
    print(f"{arm}: {sum(len(v) for v in sets.values())} chunks, {len(sigs)} distinct CODE states ({len(json.loads(sigs[0]))} code files)")
    prev = json.loads(sigs[0])
    print(f"   state 1: chunks {[c for c, _ in sets[sigs[0]]]} from {sets[sigs[0]][0][1]}")
    for i, other in enumerate(sigs[1:], 2):
        o = json.loads(other)
        diff = sorted(k for k in set(prev) | set(o) if prev.get(k) != o.get(k))
        print(f"   state {i}: chunks {[c for c, _ in sets[other]]} from {sets[other][0][1]}; changed against the previous state: {diff}")
        prev = o
