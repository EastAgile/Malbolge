import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                       # programs/battleship
SESSIONS = sorted((HERE / "sessions").glob("*.in"))

sys.path.insert(0, str(ROOT / "compiler"))


def load(name, path):
    """Import a file under its own name (two files here are battleship.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


battleship_py = load("battleship_py", ROOT / "compare" / "python" / "battleship.py")
battleship_compiler = load("battleship_compiler", ROOT / "compiler" / "battleship.py")


def read_bytes(p):
    return Path(p).read_bytes()


@pytest.fixture(scope="session")
def rust_bin():
    """Build the Rust version once; skip its tests if there is no cargo."""
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo not installed")
    crate = ROOT / "compare" / "rust"
    subprocess.run([cargo, "build", "--release", "--quiet"], cwd=crate, check=True)
    return crate / "target" / "release" / "battleship"


@pytest.fixture(scope="session")
def malbolge():
    """(interpreter, program) for the assembled game, or skip."""
    if os.environ.get("BATTLESHIP_MALBOLGE") != "1":
        pytest.skip("set BATTLESHIP_MALBOLGE=1 to run the Malbolge program itself")
    mu, prog = ROOT / "tools" / "mu", ROOT / "game" / "battleship.mu"
    if not (mu.exists() and prog.exists()):
        pytest.skip("build it first: make")
    return mu, prog
