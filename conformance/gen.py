#!/usr/bin/env python3
"""Generate the conformance cases and record expected behaviour.

Expected output comes from the oracles, never from fastbolge:
  classic  Ben Olmstead's reference interpreter (malbolge.c, 1998)
  fast20   fast20.c from MalbolgeLisp

Usage: gen.py REF_MALBOLGE FAST20 [SAMPLES_DIR...]

SAMPLES_DIR is the samples/ folder of https://github.com/zb3/malbolge-tools
(MIT); the programs it contains are copied into cases/.
Writes cases/*.mb, cases/*.in, cases/*.out and cases.json next to this file.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")

OPS = {"i": 4, "<": 5, "/": 23, "*": 39, "j": 40, "p": 62, "o": 68, "v": 81}


def encode(normalized, start=0):
    """Normalized Malbolge (ji*p</vo) -> raw program text, for code that
    starts at memory position `start`. Valid for classic Malbolge and for
    the first third of fast20 memory."""
    out = []
    for k, ch in enumerate(normalized):
        i = start + k
        op = OPS[ch]
        x = (op - i) % 94
        while x < 33:
            x += 94
        out.append(x)
    return bytes(out)


def run(cmd, prog, inp, timeout, limit=None):
    """Run an oracle. Returns (status, stdout) with status one of
    'halt', 'error', 'timeout'."""
    try:
        p = subprocess.run(cmd + [prog], input=inp, capture_output=True, timeout=timeout)
        out = p.stdout
        return ("halt" if p.returncode == 0 else "error"), out
    except subprocess.TimeoutExpired as e:
        return "timeout", (e.stdout or b"")[:limit] if limit else (e.stdout or b"")


cases = []


def add(name, mode, prog, inp=b"", expect=None, note="", timeout=10, prefix=None, oracle=None):
    """Record a case. `expect` overrides the oracle's classification:
    'load_error' and 'undefined' are cases where the oracle rejects the
    program or its behaviour is undefined (hangs or reads out of bounds)."""
    os.makedirs(CASES, exist_ok=True)
    pf = os.path.join(CASES, name + ".mb")
    with open(pf, "wb") as f:
        f.write(prog)
    if inp:
        with open(os.path.join(CASES, name + ".in"), "wb") as f:
            f.write(inp)
    status, out = run(oracle[mode], pf, inp, timeout)
    case = {"name": name, "mode": mode, "program": f"cases/{name}.mb", "note": note}
    if inp:
        case["input"] = f"cases/{name}.in"
    if expect in ("load_error", "undefined"):
        case["expect"] = expect
        case["oracle"] = status
    elif status == "halt":
        case["expect"] = "halt"
    elif status == "timeout":
        # Non-terminating: compare the first `prefix` bytes of output.
        case["expect"] = "runs"
        n = prefix or min(len(out), 256)
        if len(out) < n:
            raise SystemExit(f"{name}: oracle produced only {len(out)} bytes before timeout")
        out = out[:n]
        case["prefix"] = n
    else:
        raise SystemExit(f"{name}: oracle failed unexpectedly ({status})")
    if case["expect"] in ("halt", "runs"):
        with open(os.path.join(CASES, name + ".out"), "wb") as f:
            f.write(out)
        case["output"] = f"cases/{name}.out"
    cases.append(case)
    print(f"{name:32} {mode:8} {case['expect']:11} {len(out):6} bytes  {note}")


def main():
    ref, f20 = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    oracle = {"classic": [ref], "fast20": [f20]}
    samples = sys.argv[3:]
    A = lambda *a, **k: add(*a, oracle=oracle, **k)

    # --- Real programs -------------------------------------------------
    real = {
        "crackme.mb": [b"1234\n", b"zb3\n"],
        "encrypted.mb": [b"key\n"],
        "helloworld-eu.mb": [b"\n", b"no\n"],
        "sep.mb": [b",\nhello world\n"],
        "wat.mb": [b"\n\n\n"],
        "cat.mb": [b"Hello, cat!\n"],
    }
    for d in samples:
        tag = os.path.basename(os.path.normpath(d))
        for fn in sorted(os.listdir(d)):
            if fn not in real:
                continue
            src = open(os.path.join(d, fn), "rb").read()
            for k, inp in enumerate(real[fn]):
                name = f"prog-{tag}-{fn[:-3]}" + (f"-{k}" if len(real[fn]) > 1 else "")
                A(name, "classic", src, inp, note=f"{fn} from {tag}", timeout=20)

    # --- Instruction semantics (straight-line normalized programs) -------
    A("eof-value", "classic", encode("/<v"), note="EOF reads 59048; output is a mod 256 (0xa8)")
    A("echo-two", "classic", encode("/</<v"), b"AB", note="input then output")
    A("echo-newline", "classic", encode("/<v"), b"\n", note="newline is not translated")
    A("echo-high-byte", "classic", encode("/<v"), b"\xff", note="input bytes are unsigned")
    A("rot", "classic", encode("j*<v"), note="move d off the code, rotate [d] right")
    A("rot-twice", "classic", encode("j*<*<v"), note="rotate two cells")
    A("crz", "classic", encode("jp<v"), note="crazy op with a=0")
    A("crz-chain", "classic", encode("jpp<pp<v"), note="crazy op uses the accumulator")
    A("crz-after-input", "classic", encode("j/p<v"), b"Z", note="crazy op on input")
    A("movd-into-fill", "classic", encode("j*<v"), note="d = [0] points into crz-initialised memory")
    A("movd-twice", "classic", encode("jj*<p<v"), note="follow two pointers through initialised memory")
    A("movd-thrice", "classic", encode("jjj*<v"), note="pointer chain ends far in memory")
    A("output-high", "classic", encode("j*<*<*<v"), note="outputs of values > 255 are truncated")
    A("whitespace", "classic", b" \t\n" + b"\n".join(bytes([x]) for x in encode("/<v")) + b"\r\n", b"Q",
      note="whitespace is skipped and does not advance the position")
    # Jump: [0] must point inside the program. Program: i at 0, then nops,
    # then '<v' right after the jump target.
    body = "i" + "o" * 120
    raw = bytearray(encode(body + "/<v"))
    target = raw[0]  # c = [d] = [0]
    norm = list(body + "/<v")
    # place '/<v' so that execution continues at target + 1
    norm = ["i"] + ["o"] * (target + 1 - 1) + list("/<v")
    A("jump", "classic", encode("".join(norm)), b"J", note="i jumps to [d]+1 and encrypts [d] first")
    A("nop-run", "classic", encode("o" * 500 + "/<v"), b"N", note="long run of nops")
    # Encryption: execute the same cell twice via a jump back to 0.
    A("encrypt-cycle", "classic", encode("o" * 3000 + "<v"), note="3000 nops, then output a = 0")

    # --- Wrap-around ----------------------------------------------------
    # A full-memory program of nops: c wraps from 59048 to 0 and executes
    # the encrypted cells, which soon reaches undefined behaviour.
    A("wrap-nops", "classic", encode("o" * 59049), expect="undefined",
      note="c and d wrap to 0; four steps later an encrypted cell holds a value with no encryption", timeout=5)

    # --- Load errors (reference prints an error and exits) ---------------
    A("load-invalid-char", "classic", encode("o") + b"A" + encode("ov", 2), expect="load_error",
      note="'A' at position 1 decodes to opcode 66, not an instruction")
    A("load-too-long", "classic", encode("o" * 59049) + encode("o", 59049), expect="load_error", note="59050 instructions")

    # --- Undefined behaviour in the reference ----------------------------
    A("ub-empty", "classic", b"", expect="undefined", note="initialisation reads mem[-1], mem[-2]", timeout=3)
    A("ub-one-instruction", "classic", encode("v"), expect="undefined", note="initialisation reads mem[-1]", timeout=3)
    A("ub-self-modify", "classic", encode("*<v"), expect="undefined",
      note="c = d = 0: rot overwrites the running cell, whose new value has no encryption", timeout=3)
    A("ub-exec-nonprintable", "classic", encode("oo") + b"\x80" + encode("v", 3), expect="undefined",
      note="reference hangs on a non-printable instruction", timeout=3)

    # --- fast20 dialect ---------------------------------------------------
    A("f20-eof-value", "fast20", encode("/<v"), note="EOF reads 3^19-1; output is a mod 256")
    A("f20-echo", "fast20", encode("/</<v"), b"AB", note="input then output")
    A("f20-rot", "fast20", encode("j*<v"), note="rotation of the low 18 trits")
    A("f20-rot-twice", "fast20", encode("jj*<*<v"), note="rotation keeps the top trit")
    A("f20-crz", "fast20", encode("jpp<pp<v"), note="19-trit crazy op")
    A("f20-movd-fill", "fast20", encode("j*<v"), note="explicit crz fill up to the next 4096 cells")
    A("f20-movd-chain", "fast20", encode("jj*<jj*<v"), note="pointer chain into the repeating pattern")
    A("f20-movd-far", "fast20", encode("jjjj*<p<jj*<v"), note="pointers into upper thirds of memory")
    A("f20-no-whitespace-skip", "fast20", b" " + encode("/<v", 1), b"W",
      note="fast20 loads bytes verbatim, including whitespace")
    A("f20-nop-run", "fast20", encode("o" * 5000 + "/<v"), b"N", note="long run of nops across the fill boundary")

    with open(os.path.join(HERE, "cases.json"), "w") as f:
        json.dump(cases, f, indent=1)
    print(f"{len(cases)} cases")


if __name__ == "__main__":
    main()
