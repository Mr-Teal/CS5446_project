"""Import every module the runner can reach, to find missing dependencies before
spending queue time on them. pyproject declares only numpy and python-chess, but
pair_a_prep needs scipy too, and a batch task discovers that four seconds in."""
import importlib, pkgutil

bad = {}
for pkg in ("pair_a_prep", "pair_c", "pair_b", "fow_shared"):
    try:
        mod = importlib.import_module(pkg)
    except Exception as exc:
        bad[pkg] = f"{type(exc).__name__}: {exc}"
        continue
    for info in pkgutil.walk_packages(mod.__path__, pkg + "."):
        if ".tests" in info.name or info.name.endswith("_test"):
            continue
        try:
            importlib.import_module(info.name)
        except Exception as exc:
            bad[info.name] = f"{type(exc).__name__}: {exc}"

missing = sorted({v.split("No module named ")[-1].strip() for v in bad.values()
                  if "No module named" in v})
print("missing third-party modules:", missing or "none")
other = {k: v for k, v in bad.items() if "No module named" not in v}
print("other import failures:", len(other))
for name, err in sorted(other.items())[:10]:
    print("  ", name, "->", err[:100])
