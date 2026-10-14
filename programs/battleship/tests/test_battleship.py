"""
Tests for Battleship in Malbolge and its Python and Rust counterparts.

The files in sessions/ are the contract: each NAME.in is a keyboard session
and NAME.out is what the Malbolge program printed for it, byte for byte.  The
Python and Rust versions must reproduce every one exactly; the `malbolge`
tests re-run the Malbolge program itself to check the recordings are current.
"""
import random
import subprocess

import pytest

from conftest import SESSIONS, battleship_compiler, battleship_py as py, read_bytes

CELLS = [c + str(r) for r in range(1, 9) for c in "ABCDEFGH"]
ids = [p.stem for p in SESSIONS]


def run_python(text):
    return py.run(text).encode()


def run_binary(cmd, text):
    return subprocess.run(cmd, input=text.encode(), capture_output=True,
                          check=True).stdout


def fleets(name, first_shot):
    """(player fleet, enemy fleet) as sets of (row, col), from the Python game."""
    g = py.Game(_reader(name + "\n" + first_shot + "\n"), lambda s: None)
    g.play()
    as_set = lambda b: {divmod(k, 8) for k in range(64) if b[k]}
    return as_set(g.pship), as_set(g.eship)


def _reader(text):
    it = iter(text)
    return lambda: next(it, None)


def ships_of(cells):
    """Split a fleet into its ships; fail if any two ships touch or bend."""
    seen, ships = set(), []
    for p in sorted(cells):
        if p in seen:
            continue
        comp, stack = [], [p]
        seen.add(p)
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    q = (r + dr, c + dc)
                    if q in cells and q not in seen:
                        seen.add(q)
                        stack.append(q)
        rows, cols = {x[0] for x in comp}, {x[1] for x in comp}
        assert len(rows) == 1 or len(cols) == 1, "bent or touching ships: %s" % comp
        span = max(len(rows), len(cols))
        assert span == len(comp), "gap inside a ship: %s" % comp
        ships.append(len(comp))
    return sorted(ships, reverse=True)


def random_session(rnd):
    s = "".join(rnd.choice("abcXYZ Å⚓q") for _ in range(rnd.randint(0, 6))) + "\n"
    if rnd.random() < 0.5:
        order = CELLS[:]
        rnd.shuffle(order)
        return s + "".join(c + "\n\n" for c in order)
    for _ in range(rnd.randint(1, 40)):
        t = rnd.random()
        if t < 0.8:
            s += rnd.choice(CELLS) + "\n\n"
        elif t < 0.9:
            s += rnd.choice(["", "c5", "Z", "C", "C9", "  ", "b2 x"]) + "\n"
        else:
            s += rnd.choice(CELLS).lower() + "\n\n"
    return s[: rnd.randint(0, len(s))] if rnd.random() < 0.3 else s


# ---- every implementation reproduces the recorded Malbolge sessions --------

def test_sessions_cover_every_ending():
    outs = [read_bytes(p.with_suffix(".out")) for p in SESSIONS]
    assert any(b"Victory!" in o for o in outs)
    assert any(b"Defeat." in o for o in outs)
    assert any(b"Abandoning ship" in o for o in outs)


@pytest.mark.parametrize("session", SESSIONS, ids=ids)
def test_python_matches_malbolge(session):
    assert run_python(session.read_text()) == read_bytes(session.with_suffix(".out"))


@pytest.mark.parametrize("session", SESSIONS, ids=ids)
def test_rust_matches_malbolge(rust_bin, session):
    out = run_binary([rust_bin], session.read_text())
    assert out == read_bytes(session.with_suffix(".out"))


@pytest.mark.malbolge
@pytest.mark.parametrize("session", SESSIONS, ids=ids)
def test_malbolge_matches_recording(malbolge, session):
    mu, prog = malbolge
    out = run_binary([mu, prog], session.read_text())
    assert out == read_bytes(session.with_suffix(".out"))


def test_python_and_rust_agree_on_random_sessions(rust_bin):
    rnd = random.Random(2026)
    endings = set()
    for _ in range(300):
        s = random_session(rnd)
        a = run_python(s)
        assert run_binary([rust_bin], s) == a, repr(s[:80])
        endings.add(b"Victory" in a or b"Defeat" in a)
    assert endings == {True, False}, "fuzz should reach both finished and abandoned games"


# ---- the rules the generator has to keep -----------------------------------

def test_every_fleet_is_legal():
    for i in range(400):
        for fleet in fleets("admiral %d" % i, CELLS[i % 64]):
            assert ships_of(fleet) == [5, 4, 3, 2]


def test_same_name_and_first_shot_give_the_same_game():
    assert fleets("Larry", "C5") == fleets("Larry", "C5")
    s = "Larry\nC5\n\nD4\n\nQ\n"
    assert py.run(s) == py.run(s)


def test_name_alone_fixes_the_player_fleet():
    p1, e1 = fleets("Larry", "C5")
    p2, e2 = fleets("Larry", "D4")
    assert p1 == p2
    assert e1 != e2


def test_first_shot_as_typed_matters():
    # 'C5' and 'c5' are different keystrokes, so different enemy fleets
    assert fleets("Larry", "C5")[1] != fleets("Larry", "c5")[1]


def test_different_names_give_different_seas():
    seen = {frozenset(fleets("n%d" % i, "A1")[1]) for i in range(500)}
    assert len(seen) > 490


def test_typing_after_the_first_shot_cannot_steer_anything():
    # every key up to the end of the first shot's line seeds the enemy fleet;
    # junk typed on any later line must change nothing
    clean = "Larry\nC5\n\nD4\n\nE3\n\nQ\n"
    noisy = "Larry\nC5\nqwerty\nD4 junk\nzz\nE3\n\nQ\n"
    shots = lambda out: [l for l in out.splitlines() if "Computer fires at" in l]
    a, b = py.run(clean), py.run(noisy)
    assert shots(a) and shots(a) == shots(b)


def test_first_shot_is_not_favoured_or_punished():
    # The first shot seeds the fleet it is scored against; it must still hit
    # about as often as a shot at an independent fleet: 14 of 64 cells.
    n = 4000
    hits = sum(1 for i in range(n)
               if divmod(CELLS.index(CELLS[i % 64]), 8) in fleets("s%d" % i, CELLS[i % 64])[1])
    assert abs(hits / n - 14 / 64) < 0.03


def test_generator_never_sticks_at_zero():
    r = py.Rng()
    r.x = 0x2A
    r.mix(0x2A)                      # would cancel to zero
    assert r.x != 0


# ---- the Malbolge compiler -------------------------------------------------

def test_python_input_codes_match_the_compiler():
    from getc import char_code
    for cp in range(243):
        if cp != 10:                 # Unshackled reads newline as ...2221
            assert py.code(chr(cp)) == char_code(cp)
    assert py.code("\n") == char_code("NL_MU")
    assert py.code(None) == char_code("EOF")
    # wider characters fold onto a code, as the Malbolge decoder does
    assert py.code(chr(65 + 243)) == py.code("A")


def test_compiler_output_is_deterministic_and_self_contained():
    a, b = battleship_compiler.build(), battleship_compiler.build()
    assert a == b
    assert a.startswith(".CODE")
    assert "ENTRY:" in a


def test_constant_loads_leave_the_stream_unchanged():
    # every Opr operand must be a fixed point of crz(A, operand), so the
    # data cells survive execution and blocks can be re-entered
    from backend import CRZ, const_load_plan, to_trits
    for target in (10, 32, 65, 126, 0x1F6A2, 27):
        a = None
        for kind, arg in const_load_plan(None, to_trits(target)):
            if kind == "rot":
                a = [arg] * 15
            else:
                lead, low = arg
                op = [lead] + list(low)
                assert all(CRZ[x][k] == k for x, k in zip(a, op))
                a = op
        assert a == [0] + to_trits(target)[1]
