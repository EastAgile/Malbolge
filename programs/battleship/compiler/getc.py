"""
Reading a character, width independently.

    1. reset the cell X: low five trits -> 1, the rest -> 0  (4 crazy ops)
    2. IN; crazy X                     -> low trits = swap01(ch)
    3. two masking crazy ops: low five trits unchanged, every other trit
       (including the infinite lead) forced to 1, except trit 5 -> 0
    4. DMOVD X: D = X + 1, which is one of the 243 cells of a jump table
       placed at 1t000001 (a little below C1 in 3-adic terms)
    5. the table is a "toggle slide": every cell lands on a flag (toggling it)
       and falls through to the next cell.  Cell j toggles the bit in which
       gray(j) and gray(j+1) differ, so after the slide the eight IN flags hold
       gray(j) ^ gray(243): an exact 8-bit code of the character.

Characters 0..242 get distinct codes; EOF and Malbolge Unshackled's newline
value get their own codes; any wider code point folds onto some code (never
crashes).  `char_code(ch)` gives the code for a character at compile time.
"""

from backend import const_load_plan, fmt_trits, to_trits

SWAP01 = {0: 1, 1: 0, 2: 2}
NBITS = 8


def gray(x):
    return x ^ (x >> 1)


def _j_of_trits(trits5):
    return sum(SWAP01[t] * 3 ** i for i, t in enumerate(trits5))


def char_code(ch):
    """Compile-time code of a character (int code point), or 'EOF' / 'NL_MU'."""
    if ch == "EOF":
        j = _j_of_trits([2] * 5)
    elif ch == "NL_MU":     # Unshackled reads '\n' as ...2221
        j = _j_of_trits([1, 2, 2, 2, 2])
    else:
        assert 0 <= ch < 243, "only code points below 243 have exact codes"
        t = []
        v = ch
        for _ in range(5):
            t.append(v % 3)
            v //= 3
        j = _j_of_trits(t)
    return gray(j) ^ gray(243)


def _load(c):
    """Lines that load constant c (lead, low) into A from an unknown A."""
    lines = []
    for kind, arg in const_load_plan(None, c):
        if kind == "rot":
            lines.append("ROT C%d R_ROT" % arg)
        else:
            lines.append("OPR %s R_OPR" % fmt_trits(*arg))
    return lines


def build_getc(prog, in_flags):
    """Add the X cell, its accessor and the decode table to prog.

    Returns (entry_block, exit_block).  On entry the IN flags must be 0.
    """
    xf = ["%s_xf%d" % ("GETC", i) for i in range(7)]
    for f in xf:
        prog.flags.append(f)
    acc = ["crazy_X:", "\tOPR", "X:", "\tC1", "\tR_OPR"]
    for f in xf:
        acc.append("\tR_%s %s X_ret_%s" % (f, f, f))
    prog.extra_data.append("\n".join(acc))

    calls = iter(xf)

    def opr_x():
        f = next(calls)
        return ["%s crazy_X" % f, "X_ret_%s:" % f, "R_%s" % f]

    # Constants are (lead, five low trits).  LMFAO cannot build lead-2
    # constants, so the infinite upper part only ever sees crz with a=0/1.
    lines = []
    # reset: low trits -> 1 (f1 f2 f1 f0), upper trits -> 0 (f1 f1 f1 f1)
    for c in ((1, [1] * 5), (1, [2] * 5), (1, [1] * 5), (1, [0] * 5)):
        lines += _load(c)
        lines += opr_x()
    lines.append("IN ?- R_IN")
    lines += opr_x()              # low: swap01(ch); upper: 0 or 1
    # masks: low trits swap12 twice (identity); trit 5 f1 f1 -> 0; the rest
    # f1 then f0 -> 1.  So X = 1t0jjjjj, clear of the cells LMFAO reserves
    # around C1.
    for c in ((1, [2] * 5), (0, [2] * 5 + [1])):
        lines += _load(c)
        lines += opr_x()

    entry = prog.block("getc")
    entry.ops.append(("raw", lines, "unknown"))
    after = prog.block("getc_after")
    after.ops.append(("raw", ["R_DMOVD ?- R_DMOVD ?- R_DMOVD ?- R_DM2"], "unknown"))
    entry.term = ("rawterm", ["DMOVD X"], [after])

    table = ["@1t000001", "GETC_TABLE:"]
    for j in range(243):
        diff = gray(j) ^ gray(j + 1)
        k = diff.bit_length() - 1
        table.append("\tR_%s" % in_flags[k])
    table.append("\tR_MOVD MOVD %s" % after.name)
    prog.extra_data.append("\n".join(table))
    return entry, after
