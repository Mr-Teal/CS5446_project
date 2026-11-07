"""Current Windows release identity, doctor and compiler architecture checks."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

from pair_a_prep import build_belief_kernel as build
from zs21_runtime.scripts import doctor


ROOT = Path(__file__).resolve().parents[2]


def test_current_native_manifests_match_source_and_binary():
    assets = json.loads((ROOT / "zs21_runtime/assets.manifest.json").read_text(encoding="utf-8"))
    native = json.loads((ROOT / "pair_a_prep/zs21/native/inference.manifest.json").read_text(encoding="utf-8"))
    for path, field in (("pair_a_prep/zs21/native/inference.cpp", "source_sha256"),
                        ("pair_a_prep/zs21/native/inference.dll", "dll_sha256")):
        actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert assets["files"][path] == native[field] == actual


@pytest.mark.skipif(sys.platform != "win32", reason="audited doctor delivery is Windows-only")
def test_real_windows_doctor_verifies_assets_abi_and_four_workers(monkeypatch, tmp_path):
    output = tmp_path / "doctor.json"
    monkeypatch.setattr(sys, "argv", ["doctor", "--output", str(output)])
    doctor.main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["assets_verified"] >= 66
    assert report["workers"] == 4 and report["threads_per_worker"] == 1


@pytest.mark.parametrize("missing", (False, True))
def test_doctor_rejects_tampered_or_missing_assets_before_loading(monkeypatch, tmp_path, missing):
    asset = tmp_path / "inference.cpp"
    original = b"original release source"
    if not missing:
        asset.write_bytes(original + b"tampered")
    (tmp_path / "assets.manifest.json").write_text(json.dumps({
        "files": {"inference.cpp": hashlib.sha256(original).hexdigest()}
    }), encoding="utf-8")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor, "RUNTIME", tmp_path)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(doctor, "load", lambda: {})
    monkeypatch.setattr(sys, "argv", ["doctor", "--output", str(tmp_path / "result.json")])

    def forbidden():
        raise AssertionError("invalid release must fail before loading native code")

    monkeypatch.setattr(doctor, "library", forbidden)
    with pytest.raises((RuntimeError, FileNotFoundError), match="inference.cpp"):
        doctor.main()
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("machine,target,bits", (
    ("AMD64", "x86_64-w64-mingw32", 64),
    ("x86_64", "x86_64-linux-gnu", 64),
    ("aarch64", "aarch64-linux-gnu", 64),
    ("arm64", "arm64-apple-darwin24", 64),
    ("AMD64", "i686-w64-mingw32", 32),
))
def test_compiler_matches_interpreter_architecture(machine, target, bits):
    build.validate_compiler_target(target, machine=machine, pointer_bits=bits)


@pytest.mark.parametrize("machine,target,bits", (
    ("AMD64", "aarch64-linux-gnu", 64),
    ("arm64", "x86_64-apple-darwin24", 64),
    ("AMD64", "i686-w64-mingw32", 64),
    ("AMD64", "x86_64-w64-mingw32", 32),
))
def test_wrong_compiler_architecture_is_rejected(machine, target, bits):
    with pytest.raises(SystemExit, match="compiler"):
        build.validate_compiler_target(target, machine=machine, pointer_bits=bits)
