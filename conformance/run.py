#!/usr/bin/env python3
"""Run the conformance cases against any Malbolge interpreter.

    run.py [--mode classic|fast20] [--json out.json] [--timeout S] -- CMD...

CMD is the interpreter command line; the program path is appended and the
case input is fed on stdin. Use {mode} in CMD to substitute the dialect,
e.g.  run.py -- fastbolge -m {mode}

Verdicts:
  PASS  output matches the reference (halting cases: whole output;
        non-terminating cases: the first N bytes)
  FAIL  wrong output, wrong termination, or accepted an invalid program
  INFO  the reference's behaviour is undefined here; what happened is shown
"""
import argparse
import json
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run_case(cmd, case, timeout):
    prog = os.path.join(HERE, case["program"])
    inp = b""
    if "input" in case:
        inp = open(os.path.join(HERE, case["input"]), "rb").read()
    want = b""
    if "output" in case:
        want = open(os.path.join(HERE, case["output"]), "rb").read()
    full = [a.replace("{mode}", case["mode"]) for a in cmd] + [prog]
    t0 = time.time()
    p = subprocess.Popen(full, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.stdin.write(inp)
        p.stdin.close()
    except BrokenPipeError:
        pass
    out = b""
    limit = case.get("prefix")
    timed_out = False
    # Read until exit, timeout, or (for non-terminating cases) enough output.
    while True:
        left = timeout - (time.time() - t0)
        if left <= 0:
            timed_out = True
            break
        r, _, _ = select.select([p.stdout], [], [], min(left, 0.5))
        if r:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            out += chunk
            if limit and len(out) >= limit:
                break
            if len(out) > 1 << 20:
                break
    if p.poll() is None:
        p.kill()
    p.wait()
    err = p.stderr.read().decode(errors="replace").strip()
    rc = p.returncode
    dt = time.time() - t0
    exp = case["expect"]

    def show(b):
        return repr(b[:40])[2:-1] + ("..." if len(b) > 40 else "")

    if exp == "halt":
        if timed_out:
            return "FAIL", f"did not halt within {timeout}s (got {len(out)} bytes)", dt
        if rc < 0:
            return "FAIL", f"crashed with signal {-rc}", dt
        if out != want:
            i = next((k for k in range(min(len(out), len(want))) if out[k] != want[k]), min(len(out), len(want)))
            return "FAIL", f"output differs at byte {i}: got {show(out[i:])} want {show(want[i:])}", dt
        return "PASS", "", dt
    if exp == "runs":
        if out[:limit] != want:
            return "FAIL", f"first {limit} bytes differ: got {show(out)} want {show(want)}", dt
        return "PASS", "", dt
    if exp == "load_error":
        if timed_out or rc == 0:
            return "FAIL", "accepted an invalid program" + (" (then hung)" if timed_out else ""), dt
        return "PASS", "", dt
    # undefined
    if timed_out:
        what = "hangs"
    elif rc < 0:
        what = f"crashes (signal {-rc})"
    elif rc == 0:
        what = f"exits 0 with output {show(out)}"
    else:
        what = f"exits {rc}: {err.splitlines()[-1] if err else ''}"
    return "INFO", what, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["classic", "fast20"])
    ap.add_argument("--json")
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("no interpreter command given")
    cases = json.load(open(os.path.join(HERE, "cases.json")))
    results = []
    counts = {"PASS": 0, "FAIL": 0, "INFO": 0}
    for case in cases:
        if a.mode and case["mode"] != a.mode:
            continue
        t = a.timeout if case["expect"] != "undefined" else min(a.timeout, 3)
        verdict, detail, dt = run_case(cmd, case, t)
        counts[verdict] += 1
        results.append({"name": case["name"], "mode": case["mode"], "verdict": verdict, "detail": detail, "seconds": round(dt, 3)})
        if not a.quiet or verdict == "FAIL":
            print(f"{verdict}  {case['name']:30} {detail}")
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['INFO']} informational")
    if a.json:
        json.dump({"command": cmd, "counts": counts, "results": results}, open(a.json, "w"), indent=1)
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
