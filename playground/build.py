#!/usr/bin/env python3
"""Build playground/index.html: one self-contained page with the WASM inlined.

    cargo build --release --target wasm32-unknown-unknown --lib   (in interpreter/)
    python3 playground/build.py

Sample programs come from conformance/cases (zb3/malbolge-tools, MIT).
"""
import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES = os.path.join(ROOT, "conformance", "cases")
WASM = os.path.join(ROOT, "interpreter", "web", "fastbolge.wasm")

OPS = {"i": 4, "<": 5, "/": 23, "*": 39, "j": 40, "p": 62, "o": 68, "v": 81}


def encode(norm):
    """Normalized Malbolge (one opcode letter per cell) to raw source."""
    out = ""
    for k, ch in enumerate(norm):
        x = (OPS[ch] - k) % 94
        while x < 33:
            x += 94
        out += chr(x)
    return out


def case(name):
    def rd(ext):
        p = os.path.join(CASES, f"prog-samples-{name}.{ext}")
        return open(p, "rb").read().decode("latin-1") if os.path.exists(p) else ""
    return rd("mb"), rd("in")


SAMPLES = []
for title, name, credit in [
    ("Hello world (EU edition)", "helloworld-eu-0", "zb3 (MIT)"),
    ("Crackme", "crackme-0", "zb3 (MIT)"),
    ("Separator", "sep", "zb3 (MIT)"),
    ("Cat", "cat", "zb3 (MIT)"),
]:
    prog, inp = case(name)
    SAMPLES.append({"name": title, "program": prog, "input": inp, "mode": "classic", "credit": credit})
SAMPLES.append({"name": "End-of-input value", "program": encode("/<v"), "input": "", "mode": "classic",
                "credit": "reads EOF, prints it, halts"})

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Run Malbolge, the programming language from the eighth circle of hell, in your browser. By East Agile.">
"""


def main():
    t = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    w = base64.b64encode(open(WASM, "rb").read()).decode()
    t = t.replace('"__WASM__"', json.dumps(w)).replace("__SAMPLES__", json.dumps(SAMPLES).replace("</", "<\\/"))
    open(os.path.join(HERE, "index.html"), "w", encoding="utf-8").write(HEAD + t + "\n</html>\n")


if __name__ == "__main__":
    main()
