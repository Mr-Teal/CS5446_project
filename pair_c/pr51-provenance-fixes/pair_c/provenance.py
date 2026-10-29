"""Runtime source hashes and best-effort hardware identification for loaded players."""

import hashlib
import json
import platform
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Hash the current file bytes in bounded chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _player_component(agent):
    for name in ("scorer", "evaluator"):
        component = getattr(agent, name, None)
        if component is not None:
            return component
    return agent


def checkpoint_provenance(agent) -> tuple[str | None, str | None, str | None]:
    """Read a loader's explicit checkpoint declaration, never an INI guess."""
    component = _player_component(agent)
    if not hasattr(component, "provenance_checkpoint_path"):
        component = agent
    if not hasattr(component, "provenance_checkpoint_path"):
        return None, None, "Agent/scorer/evaluator does not expose provenance_checkpoint_path"
    checkpoint = component.provenance_checkpoint_path
    if checkpoint is None:
        return None, None, None
    path = Path(checkpoint).expanduser().resolve()
    return str(path), sha256_file(path), None


def stockfish_provenance(agent) -> tuple[dict | None, str | None]:
    """Read the existing UCI instance; hash its recorded launch executable."""
    component = _player_component(agent)
    engine_scorer = getattr(component, "stockfish", None)
    if engine_scorer is None and hasattr(component, "engine"):
        engine_scorer = component
    if engine_scorer is None:
        return None, None
    engine = getattr(engine_scorer, "engine", None)
    identity = getattr(engine, "id", {})
    executable = getattr(engine_scorer, "provenance_executable_path", None)
    info = {
        "path": str(Path(executable).resolve()) if executable else None,
        "name": identity.get("name"),
        "author": identity.get("author"),
    }
    if executable is None:
        # Custom factories must identify their actual launch file; do not guess
        # from an INI path that might differ from what they launched.
        info["detection_note"] = "Engine scorer does not expose provenance_executable_path"
        return info, None
    return info, sha256_file(Path(executable))


def source_file_hashes(root: Path) -> dict[str, str | None]:
    """Hash every tracked file discovered at runtime, without file-type filtering."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--full-name", "-z"],
            cwd=root, capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Cannot query Git-tracked files for provenance") from error

    hashes = {}
    # NUL delimiters preserve paths with spaces, newlines or non-ASCII characters.
    paths = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    for relative in sorted(set(paths) - {""}):
        path = Path(relative)
        try:
            hashes[relative] = sha256_file(root / path)
        except FileNotFoundError:
            # A local deletion remains visible in the index until staged.
            hashes[relative] = None
    return hashes


def _command(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=15).stdout.strip()


def cpu_model():
    try:
        system = platform.system()
        if system == "Windows":
            return _command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-CimInstance Win32_Processor).Name") or None
        if system == "Darwin":
            return _command("sysctl", "-n", "machdep.cpu.brand_string") or None
        if system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() in ("model name", "Hardware"):
                    return value.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or None


def player_device(agent, torch):
    """Use loaded tensor placement, then effective device; never infer from config."""
    component = _player_component(agent)
    device = getattr(component, "device", None)
    net = getattr(component, "net", None)
    if net is not None:
        try:
            device = next(net.parameters()).device
        except StopIteration:
            pass
    if device is None and any(
        base.__module__ in ("pairb.material", "pairb.stockfish")
        for base in type(component).__mro__
    ):
        device = "cpu"
    info = {"device": str(device) if device is not None else None,
            "backend": None, "gpu_model": None, "detection_note": None}
    if device is None:
        info["detection_note"] = "Agent/scorer/evaluator does not expose an effective device"
        return info
    backend = str(device).split(":", 1)[0]
    info["backend"] = backend
    try:
        if backend == "cuda" and torch is not None:
            selected = torch.device(device)
            index = selected.index if selected.index is not None else torch.cuda.current_device()
            info["device"] = f"cuda:{index}"
            # Logical indices respect CUDA_VISIBLE_DEVICES remapping.
            info["gpu_model"] = torch.cuda.get_device_name(index)
        elif backend == "mps" and platform.system() == "Darwin":
            displays = json.loads(_command("system_profiler", "SPDisplaysDataType", "-json"))
            models = [item["sppci_model"] for item in displays.get("SPDisplaysDataType", [])
                      if item.get("sppci_model")]
            # MPS exposes no physical adapter ID: do not guess on multi-GPU Macs.
            if len(models) == 1:
                info["gpu_model"] = models[0]
            else:
                info["detection_note"] = "MPS adapter identity unavailable or multiple adapters detected"
        elif backend != "cpu":
            info["detection_note"] = "GPU model detection unavailable for this backend"
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError, AssertionError) as error:
        info["detection_note"] = f"GPU detection failed: {error}"
    return info


if __name__ == "__main__":
    # Optional, isolated smoke check: does not launch engines or evaluations.
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def git(*args):
            return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

        git("init")
        tracked = root / "tracked.py"
        tracked.write_bytes(b"original\n")
        (root / "tracked.log").write_text("log", encoding="utf-8")
        git("add", "tracked.py", "tracked.log")
        (root / "TODO").write_text("temporary note", encoding="utf-8")
        (root / "untracked.py").write_text("temporary code", encoding="utf-8")
        log_hash = sha256_file(root / "tracked.log")
        assert source_file_hashes(root) == {
            "tracked.py": sha256_file(tracked), "tracked.log": log_hash,
        }
        original = source_file_hashes(root)
        tracked.write_bytes(b"modified without git add\n")
        assert source_file_hashes(root) != original
        tracked.unlink()
        assert source_file_hashes(root) == {"tracked.py": None, "tracked.log": log_hash}
        git("add", "-u")
        assert source_file_hashes(root) == {"tracked.log": log_hash}
    print("Source provenance smoke checks passed.")
