"""Runtime source hashes and best-effort hardware identification for loaded players."""

import hashlib
import json
import os
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


def load_hash_rules(path: Path) -> tuple[dict, bytes]:
    """Read and validate the exact rules that will be saved with the run."""
    data = path.read_bytes()
    rules = json.loads(data.decode("utf-8"))
    if not isinstance(rules, dict) or rules.get("version") != "crlf-to-lf-v1" or rules.get("default") != "binary":
        raise ValueError("Hash rules require version crlf-to-lf-v1 and default binary")
    for key in ("text_extensions", "binary_extensions", "text_filenames"):
        values = rules.get(key)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value or value != value.lower() for value in values):
            raise ValueError(f"Hash rules {key} must be a list of lowercase strings")
        if len(values) != len(set(values)):
            raise ValueError(f"Hash rules {key} contains duplicates")
    for key in ("text_extensions", "binary_extensions"):
        if any(not value.startswith(".") or "/" in value or "\\" in value for value in rules[key]):
            raise ValueError(f"Hash rules {key} must contain file extensions")
    if set(rules["text_extensions"]) & set(rules["binary_extensions"]):
        raise ValueError("Text and binary extensions must not overlap")
    return rules, data


def sha256_text_bytes(data: bytes) -> str:
    """Hash bytes after converting CRLF to LF; preserve all other bytes."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha256_tracked_file(path: Path, rules: dict) -> str:
    """Normalize classified text while streaming, preserving binary bytes."""
    name, extension = path.name.lower(), path.suffix.lower()
    if extension in rules["binary_extensions"]:
        return sha256_file(path)
    if extension not in rules["text_extensions"] and name not in rules["text_filenames"]:
        return sha256_file(path)
    hasher = hashlib.sha256()
    pending = b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            chunk = pending + chunk
            pending = b"\r" if chunk.endswith(b"\r") else b""
            if pending:
                chunk = chunk[:-1]
            hasher.update(chunk.replace(b"\r\n", b"\n"))
    hasher.update(pending)
    return hasher.hexdigest()


def git_provenance(root: Path) -> dict:
    """Capture HEAD and porcelain status independently, with failure notes."""
    result = {"git_commit": None, "git_status": None, "git_detection_notes": {}}
    commands = {
        "git_commit": ["git", "rev-parse", "--verify", "HEAD"],
        "git_status": ["git", "-c", "core.quotePath=false", "status", "--porcelain=v1", "--untracked-files=all"],
    }
    for field, command in commands.items():
        try:
            completed = subprocess.run(
                command, cwd=root, capture_output=True, check=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", None)
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            result["git_detection_notes"][field] = (detail or str(error)).strip()
        else:
            result[field] = (completed.stdout.strip() or None) if field == "git_commit" else completed.stdout.splitlines()
            result["git_detection_notes"][field] = None
    return result


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


def _same_directory(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except OSError as error:
        raise RuntimeError(f"Cannot compare Git repository root {first} with {second}: {error}") from error


def discover_sources(root: Path) -> tuple[str, list[str], str | None]:
    """Select tracked files or all files when Git or the repository is absent."""
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=root,
            capture_output=True, timeout=30, env=env,
        )
    except FileNotFoundError as error:
        if not root.is_dir():
            raise RuntimeError(f"Cannot access source root {root}: {error}") from error
        reason = f"Git executable not found: {error}"
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Cannot determine Git repository at {root}: {error}") from error
    else:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode:
            if "not a git repository" not in detail.lower():
                raise RuntimeError(f"Cannot determine Git repository at {root}: {detail or result.returncode}")
            reason = detail
        elif not _same_directory(Path(os.fsdecode(result.stdout.rstrip(b"\r\n"))), root):
            reason = "Project root is not the Git repository root"
        else:
            try:
                tracked = subprocess.run(
                    ["git", "ls-files", "--cached", "--full-name", "-z"],
                    cwd=root, capture_output=True, check=True, timeout=30, env=env,
                )
            except (OSError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", None)
                if isinstance(detail, bytes):
                    detail = detail.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Cannot query Git-tracked files at {root}: {detail or error}") from error
            paths = tracked.stdout.decode("utf-8", errors="surrogateescape").split("\0")
            return "git", sorted(set(paths) - {""}), None

    paths = []
    def scan_error(error):
        raise RuntimeError(f"Cannot scan source directory {error.filename}: {error}") from error

    for directory, directories, filenames in os.walk(root, onerror=scan_error, followlinks=False):
        # Do not traverse directory links, which may escape the root or form cycles.
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink():
                paths.append(path.relative_to(root).as_posix())
        for filename in filenames:
            paths.append((Path(directory) / filename).relative_to(root).as_posix())
    return "filesystem", sorted(paths), reason


def source_file_hashes(root: Path, rules: dict, paths: list[str] | None = None) -> dict:
    """Hash discovered files; retain individual read failures in the result."""
    if paths is None:
        _, paths, _ = discover_sources(root)

    hashes = {}
    for relative in paths:
        path = Path(relative)
        try:
            hashes[relative] = sha256_tracked_file(root / path, rules)
        except FileNotFoundError:
            hashes[relative] = None
        except OSError as error:
            hashes[relative] = {"error": str(error)}
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
        rules, _ = load_hash_rules(Path(__file__).with_name("hash_rules.json"))

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
        assert source_file_hashes(root, rules) == {
            "tracked.py": sha256_file(tracked), "tracked.log": log_hash,
        }
        original = source_file_hashes(root, rules)
        tracked.write_bytes(b"modified without git add\n")
        assert source_file_hashes(root, rules) != original
        tracked.unlink()
        assert source_file_hashes(root, rules) == {"tracked.py": None, "tracked.log": log_hash}
        git("add", "-u")
        assert source_file_hashes(root, rules) == {"tracked.log": log_hash}
    print("Source provenance smoke checks passed.")
