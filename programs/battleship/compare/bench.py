#!/usr/bin/env python3
"""
Measure the three Battleship implementations and draw the comparison chart.

    python3 bench.py            # measure, write results.json and chart.svg
    python3 bench.py --chart    # redraw chart.svg from results.json only

Needs the Malbolge game built (`make` in programs/battleship) and cargo for
the Rust version.  Every run plays the same recorded session, a complete game
of 64 shots (tests/sessions/shuffled_full_game.in), and the three outputs are
checked to be byte-identical before any number is reported.
"""
import json
import platform
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SESSION = ROOT / "tests" / "sessions" / "shuffled_full_game.in"
QUIT = ROOT / "tests" / "sessions" / "quit_at_first_shot.in"
RUST = HERE / "rust"
RUST_BIN = RUST / "target" / "release" / "battleship"
MU, PROG = ROOT / "tools" / "mu", ROOT / "game" / "battleship.mu"
HELL = ROOT / "game" / "battleship.hell"

LANGS = ["Python", "Rust", "Malbolge"]

MEASURE = HERE / "measure"


def run_once(cmd, stdin):
    """Wall time, peak RSS, stdout and stderr of one run (see measure.c)."""
    with tempfile.NamedTemporaryFile("r", suffix=".measure") as rep:
        p = subprocess.run([MEASURE, rep.name, stdin] + [str(c) for c in cmd],
                           capture_output=True)
        secs, rss_kb = rep.read().split()
    if p.returncode != 0:
        raise RuntimeError("%s exited %d: %s" % (cmd[0], p.returncode, p.stderr[-300:]))
    return float(secs), int(rss_kb) * 1024, p.stdout, p.stderr.decode()


def measure(cmd, stdin, runs):
    times, rss, outs, err = [], [], set(), ""
    for _ in range(runs):
        t, m, out, err = run_once(cmd, stdin)
        times.append(t)
        rss.append(m)
        outs.add(out)
    assert len(outs) == 1, "nondeterministic output"
    return {"seconds": statistics.median(times), "runs": runs,
            "peak_rss_bytes": max(rss)}, outs.pop(), err


def lines(paths):
    """Non-blank lines and bytes over some files."""
    n = b = 0
    for p in paths:
        text = Path(p).read_text()
        n += sum(1 for l in text.splitlines() if l.strip())
        b += len(text.encode())
    return n, b


def rust_source_lines():
    """main.rs without its #[cfg(test)] module."""
    text = (RUST / "src" / "main.rs").read_text().split("#[cfg(test)]")[0]
    return sum(1 for l in text.splitlines() if l.strip()), len(text.encode())


def measure_all(runs, mb_runs):
    subprocess.run(["cargo", "build", "--release", "--quiet"], cwd=RUST, check=True)
    subprocess.run(["cc", "-O2", "-o", MEASURE, HERE / "measure.c"], check=True)
    for f in (MU, PROG, HELL):
        if not f.exists():
            sys.exit("missing %s: run `make` in %s first" % (f, ROOT))
    cmds = {
        "Python": [sys.executable, HERE / "python" / "battleship.py"],
        "Rust": [RUST_BIN],
        "Malbolge": [MU, "-s", PROG],
    }
    cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo")
                if l.startswith("model name")), platform.machine()) \
        if Path("/proc/cpuinfo").exists() else platform.machine()
    res = {"machine": "%s, %s, Python %s, %s" % (cpu, platform.system(),
                                                  platform.python_version(),
                                                  subprocess.run(["rustc", "--version"],
                                                                 capture_output=True,
                                                                 text=True).stdout.strip()),
           "session": SESSION.name, "langs": {}}
    outputs = {}
    for lang, cmd in cmds.items():
        n = mb_runs if lang == "Malbolge" else runs
        print("measuring %s (%d run%s)..." % (lang, n, "s" * (n > 1)), file=sys.stderr)
        game, out, err = measure(cmd, SESSION, n)
        startup, _, err_q = measure(cmd, QUIT, n)
        outputs[lang] = out
        entry = {"full_game": game, "quit_at_first_shot": startup}
        for key, text in (("full_game", err), ("quit_at_first_shot", err_q)):
            m = re.search(r"(\d+) steps", text)
            if m:
                entry[key]["malbolge_steps"] = int(m.group(1))
        res["langs"][lang] = entry
    assert len(set(outputs.values())) == 1, "the three implementations disagree!"
    res["output_bytes"] = len(outputs["Python"])

    py_n, py_b = lines([HERE / "python" / "battleship.py"])
    rs_n, rs_b = rust_source_lines()
    comp = sorted((ROOT / "compiler").glob("*.py"))
    mb_n, mb_b = lines(comp)
    game_n, game_b = lines([ROOT / "compiler" / "battleship.py"])
    hell_n, hell_b = lines([HELL])
    L = res["langs"]
    L["Python"].update(source_lines=py_n, source_bytes=py_b, shipped_bytes=py_b,
                       shipped="battleship.py (needs a Python interpreter)")
    L["Rust"].update(source_lines=rs_n, source_bytes=rs_b,
                     shipped_bytes=RUST_BIN.stat().st_size,
                     shipped="release binary (self-contained)")
    L["Malbolge"].update(source_lines=mb_n, source_bytes=mb_b,
                         game_lines=game_n, game_bytes=game_b,
                         hell_lines=hell_n, hell_bytes=hell_b,
                         shipped_bytes=PROG.stat().st_size,
                         shipped="battleship.mu (needs a Malbolge Unshackled interpreter)")
    return res


# ---- chart --------------------------------------------------------------------

COLORS = {  # reference categorical slots 1-3, light / dark
    "Python": ("#2a78d6", "#3987e5"),
    "Rust": ("#eb6834", "#d95926"),
    "Malbolge": ("#1baf7a", "#199e70"),
}


def human_bytes(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1000 or unit == "GB":
            return ("%.0f %s" if b >= 100 or unit == "B" else "%.1f %s") % (b, unit)
        b /= 1000.0


def human_secs(s):
    if s < 1:
        return "%.0f ms" % (s * 1000)
    return "%.1f s" % s


def human_lines(n):
    return "{:,} lines".format(n)


def ratio_text(r):
    """'4.3\u00d7', '47\u00d7', '19,000\u00d7': two significant figures."""
    if r < 10:
        return "%.1f\u00d7" % r
    digits = len(str(int(r))) - 2
    return "{:,}\u00d7".format(int(round(r, -digits)))


def tick_bytes(b):
    return human_bytes(b).replace(".0 ", " ")


def tick_secs(s):
    return "%g ms" % (s * 1000) if s < 1 else "%g s" % s


def tick_lines(n):
    return "{:,}".format(int(n))


def chart(res):
    import math
    L = res["langs"]
    notes = {"Malbolge": "game + compiler"}
    panels = [
        ("Source written by hand", "non-blank lines",
         {k: L[k]["source_lines"] for k in LANGS}, human_lines, tick_lines, notes),
        ("Program you run", "file size",
         {k: L[k]["shipped_bytes"] for k in LANGS}, human_bytes, tick_bytes, {}),
        ("Time to play a full game", "wall clock, the same 64-shot session",
         {k: L[k]["full_game"]["seconds"] for k in LANGS}, human_secs, tick_secs, {}),
        ("Peak memory", "resident set size",
         {k: L[k]["full_game"]["peak_rss_bytes"] for k in LANGS}, human_bytes, tick_bytes, {}),
    ]
    W, pad, label_w, row_h, gap = 760, 24, 92, 26, 6
    plot_x, plot_w = pad + label_w, W - 2 * pad - label_w - 190
    panel_h = 72 + len(LANGS) * (row_h + gap)
    H = 74 + len(panels) * panel_h + 10
    o = []
    o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
             'viewBox="0 0 %d %d" role="img" aria-labelledby="t d">' % (W, H, W, H))
    o.append('<title id="t">Battleship in Python, Rust and Malbolge</title>')
    o.append('<desc id="d">Log-scale bars comparing source lines, program size, run time '
             'and peak memory. The table in the README has the same numbers.</desc>')
    css = [":root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;--edge:#d6d5d0}"]
    css += [".s-%s{fill:%s}" % (k, v[0]) for k, v in COLORS.items()]
    css.append("@media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#f0efec;"
               "--ink2:#c3c2b7;--grid:#353532;--edge:#44443f}%s}"
               % "".join(".s-%s{fill:%s}" % (k, v[1]) for k, v in COLORS.items()))
    css.append("text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,"
               "sans-serif;fill:var(--ink)}.t2{fill:var(--ink2)}"
               ".h{font-size:15px;font-weight:600}.sub{font-size:12px}.lab{font-size:13px}"
               ".val{font-size:12px;font-variant-numeric:tabular-nums}"
               ".tick{font-size:10px}")
    o.append("<style>%s</style>" % "".join(css))
    o.append('<rect x="0.5" y="0.5" width="%d" height="%d" rx="10" fill="var(--bg)" '
             'stroke="var(--edge)"/>' % (W - 1, H - 1))
    o.append('<text x="%d" y="32" class="h" style="font-size:17px">Battleship: same game, '
             'three languages</text>' % pad)
    o.append('<text x="%d" y="52" class="sub t2">Every bar is on a log scale: each grid '
             'line is ten times the one before. Shorter is better.</text>' % pad)
    y0 = 74
    for title, sub, vals, fmt, tick, note in panels:
        # one decade below the smallest value, so no bar is a sliver
        lo = 10 ** (math.floor(math.log10(min(vals.values()))) - 1)
        hi = 10 ** math.ceil(math.log10(max(vals.values())))
        span = math.log10(hi) - math.log10(lo)
        xs = lambda v: plot_x + plot_w * (math.log10(v) - math.log10(lo)) / span
        o.append('<text x="%d" y="%d" class="h">%s</text>' % (pad, y0 + 18, title))
        o.append('<text x="%d" y="%d" class="sub t2">%s</text>' % (pad, y0 + 34, sub))
        top = y0 + 44
        bottom = top + len(LANGS) * (row_h + gap)
        e = int(round(math.log10(lo)))
        while 10 ** e <= hi:
            x = xs(10 ** e)
            o.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="var(--grid)" '
                     'stroke-width="1"/>' % (x, x, top - 2, bottom - gap + 2))
            o.append('<text x="%.1f" y="%d" class="tick t2" text-anchor="middle">%s</text>'
                     % (x, bottom + 10, tick(10 ** e)))
            e += 1
        least = min(vals, key=vals.get)
        for i, lang in enumerate(LANGS):
            y = top + i * (row_h + gap)
            v = vals[lang]
            x1 = xs(v)
            w = max(x1 - plot_x, 4)
            o.append('<text x="%d" y="%d" class="lab">%s</text>' % (pad, y + 17, lang))
            # 4px rounded data end, square at the baseline
            o.append('<path class="s-%s" d="M%.1f %d h%.1f a4 4 0 0 1 4 4 v%d a4 4 0 0 1 -4 4 '
                     'h-%.1f z"><title>%s: %s</title></path>'
                     % (lang, plot_x, y, w - 4, row_h - 8, w - 4, lang, fmt(v)))
            extra = []
            if lang in note:
                extra.append(note[lang])
            if lang != least:
                ratio = v / vals[least]
                extra.append(ratio_text(ratio) + " " + least)
            o.append('<text x="%.1f" y="%d" class="val">%s<tspan class="t2">%s</tspan></text>'
                     % (plot_x + w + 6, y + 17, fmt(v),
                        "".join("  \u00b7  " + x for x in extra)))
        y0 += panel_h
    o.append("</svg>")
    return "\n".join(o) + "\n"


def main():
    if "--chart" in sys.argv:
        res = json.loads((HERE / "results.json").read_text())
    else:
        res = measure_all(runs=5, mb_runs=3)
        (HERE / "results.json").write_text(json.dumps(res, indent=2) + "\n")
    (HERE / "chart.svg").write_text(chart(res))
    L = res["langs"]
    for k in LANGS:
        print("%-9s %6d lines  %10s shipped  %8s game  %8s quit  %9s peak"
              % (k, L[k]["source_lines"], human_bytes(L[k]["shipped_bytes"]),
                 human_secs(L[k]["full_game"]["seconds"]),
                 human_secs(L[k]["quit_at_first_shot"]["seconds"]),
                 human_bytes(L[k]["full_game"]["peak_rss_bytes"])))


if __name__ == "__main__":
    main()
