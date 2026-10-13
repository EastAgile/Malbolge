"""
Backend: a bit-level control-flow graph lowered to HeLL for Malbolge Unshackled.

Execution model (HeLL / LMFAO conventions)
------------------------------------------
The D register walks a *data stream*; the C register bounces between a few
primitive code cells.  Every stream cell that is read by a Jmp names the next
primitive to run.

State lives almost entirely in *flags*: two-state code cells whose xlat2 cycle
is MovD/Nop.  A flag costs nothing to keep and is width independent:

  toggle f        R_f              land on the cell -> it is encrypted once
  test f -> L     R_f f L          toggle, execute, toggle back.  The cell runs
                                   MovD (jump to L) iff the flag was 1.

Bit value 1 means "resting in the Nop state".  Every flag starts at 0.

Nothing in the generated program ever rotates a value whose rotation depends on
the (unknown, growing) rotation width of Malbolge Unshackled: the only Rot
operands are C0/C1/C2, which are rotation invariant.  Characters are printed by
loading constants into A with crazy operations whose operands are fixed points,
so every stream cell is unchanged after it runs and code can loop freely.
"""

import itertools

# ---------------------------------------------------------------- trits

NTRITS = 14  # enough for any Unicode code point (3^13 > 0x10FFFF)

# crz[a][d]: result of the crazy operation on one trit
CRZ = [[1, 1, 2], [0, 0, 2], [0, 2, 1]]
# for a given A trit, operand trits k with crz(a, k) == k (fixed points)
FIXED = {a: [k for k in range(3) if CRZ[a][k] == k] for a in range(3)}


def to_trits(v, n=NTRITS):
    """Non-negative integer -> (lead, little-endian low trits)."""
    t = []
    for _ in range(n):
        t.append(v % 3)
        v //= 3
    assert v == 0, "value too wide"
    return (0, t)


def fmt_trits(lead, low):
    """HeLL notation: <lead>t<digits, most significant first>."""
    digits = "".join(str(x) for x in reversed(low)).lstrip(str(lead)) or str(lead)
    return "%dt%s" % (lead, digits)


def const_load_plan(start, target):
    """Shortest instruction sequence that turns A into `target`.

    start/target are (lead, low-trits) tuples; start may be None (unknown A).
    Returns a list of ('rot', c) / ('opr', (lead, low)) steps.  Every Opr
    operand is a fixed point of crz(A, operand), so the stream is unchanged
    after it runs.
    """
    positions = [target[0]] + list(target[1])
    best = None
    starts = []
    if start is not None:
        starts.append(([], [start[0]] + list(start[1])))
    for c in (0, 1):   # LMFAO cannot build lead-2 constants such as C2
        starts.append(([("rot", c)], [c] * len(positions)))
    for prefix, cur in starts:
        for n in range(0, 7):
            if best is not None and len(prefix) + n >= len(best):
                break
            paths = []
            ok = True
            for idx, (a0, goal) in enumerate(zip(cur, positions)):
                p = _trit_path(a0, goal, n, (0, 1) if idx == 0 else (0, 1, 2))
                if p is None:
                    ok = False
                    break
                paths.append(p)
            if not ok:
                continue
            steps = list(prefix)
            for i in range(n):
                lead = paths[0][i]
                low = [p[i] for p in paths[1:]]
                steps.append(("opr", (lead, low)))
            best = steps
            break
    assert best is not None
    return best


def _trit_path(a, goal, n, allowed=(0, 1, 2)):
    """Trits k1..kn with k1 in FIXED[a], k(i+1) in FIXED[k(i)], kn == goal."""
    # reachable sets backwards
    if n == 0:
        return [] if a == goal else None
    if goal not in allowed:
        return None
    reach = [set() for _ in range(n + 1)]
    reach[n] = {goal}
    for i in range(n - 1, 0, -1):
        reach[i] = {k for k in allowed if any(x in reach[i + 1] for x in FIXED[k])}
    path = []
    cur = a
    for i in range(1, n + 1):
        choice = [k for k in FIXED[cur] if k in reach[i] and k in allowed]
        if not choice:
            return None
        cur = choice[0]
        path.append(cur)
    return path


# ---------------------------------------------------------------- graph

class Block:
    __slots__ = ("name", "ops", "term", "preds", "a_in")

    def __init__(self, name):
        self.name = name
        self.ops = []       # ('tog', flag) | ('out', codepoint) | ('raw', [lines], a_after)
        self.term = None    # ('goto', B) | ('test', flag, B1, B0) | ('halt',) | ('rawterm', [lines], [succ])
        self.preds = 0
        self.a_in = None

    def succs(self):
        t = self.term
        if t[0] == "goto":
            return [t[1]]
        if t[0] == "test":
            return [t[2], t[3]]
        if t[0] == "rawterm":
            return list(t[2])
        return []

    def __repr__(self):
        return "<%s>" % self.name


class Program:
    def __init__(self):
        self.blocks = []
        self.flags = []
        self.names = set()
        self.extra_code = []   # raw .CODE blocks
        self.extra_data = []   # raw .DATA blocks
        self.counter = itertools.count()

    def uniq(self, base):
        base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in base)
        while True:
            n = "%s_%d" % (base, next(self.counter))
            if n not in self.names:
                self.names.add(n)
                return n

    def block(self, hint="b"):
        b = Block(self.uniq("L_" + hint))
        self.blocks.append(b)
        return b

    def flag(self, hint="f"):
        f = self.uniq("F_" + hint)
        self.flags.append(f)
        return f


UNKNOWN = "unknown"


def _meet(x, y):
    if x is None:
        return y
    if y is None:
        return x
    return x if x == y else UNKNOWN


def emit_hell(prog, entry, primitives_used=None):
    """Lay out the graph and return HeLL source text."""
    # reachability from entry
    seen = set()
    order = []
    stack = [entry]
    while stack:
        b = stack.pop()
        if id(b) in seen:
            continue
        seen.add(id(b))
        order.append(b)
        assert b.term is not None, "unterminated block %s" % b.name
        for s in reversed(b.succs()):
            stack.append(s)
    blocks = order

    # forward through empty goto-blocks
    def resolve(b):
        hops = 0
        while not b.ops and b.term[0] == "goto" and hops < 1000:
            b = b.term[1]
            hops += 1
        return b

    for b in blocks:
        t = b.term
        if t[0] == "goto":
            b.term = ("goto", resolve(t[1]))
        elif t[0] == "test":
            b.term = ("test", t[1], resolve(t[2]), resolve(t[3]))
        elif t[0] == "rawterm":
            b.term = ("rawterm", t[1], [resolve(s) for s in t[2]])
    entry = resolve(entry)
    seen = set()
    order = []
    stack = [entry]
    while stack:
        b = stack.pop()
        if id(b) in seen:
            continue
        seen.add(id(b))
        order.append(b)
        for s in reversed(b.succs()):
            stack.append(s)
    blocks = order

    # A-register dataflow (value of A on block entry)
    for b in blocks:
        b.a_in = None
    entry.a_in = UNKNOWN
    changed = True
    while changed:
        changed = False
        for b in blocks:
            if b.a_in is None:
                continue
            a = b.a_in
            for op in b.ops:
                if op[0] == "out":
                    a = op[1]
                elif op[0] == "raw":
                    a = op[2]
            if b.term[0] == "rawterm":
                a = UNKNOWN
            for s in b.succs():
                m = _meet(s.a_in, a)
                if m != s.a_in:
                    s.a_in = m
                    changed = True

    # chain blocks by fallthrough: the "else" edge of a test, or a goto
    placed = set()
    chains = []
    incoming_ft = {}
    for b in blocks:
        t = b.term
        nxt = None
        if t[0] == "goto":
            nxt = t[1]
        elif t[0] == "test":
            nxt = t[3]
        if nxt is not None:
            incoming_ft.setdefault(id(nxt), []).append(b)

    for b in blocks:
        if id(b) in placed:
            continue
        chain = []
        cur = b
        while cur is not None and id(cur) not in placed:
            chain.append(cur)
            placed.add(id(cur))
            t = cur.term
            nxt = None
            if t[0] == "goto":
                nxt = t[1]
            elif t[0] == "test":
                nxt = t[3]
            cur = nxt
        chains.append(chain)

    out = []
    for chain in chains:
        lines = []
        for i, b in enumerate(chain):
            lines.append("%s:" % b.name)
            a = b.a_in
            for op in b.ops:
                if op[0] == "tog":
                    lines.append("\tR_%s" % op[1])
                elif op[0] == "out":
                    lines.extend(_out_lines(a, op[1]))
                    a = op[1]
                elif op[0] == "raw":
                    lines.extend("\t" + x for x in op[1])
                    a = op[2]
                else:
                    raise ValueError(op)
            t = b.term
            fall = chain[i + 1] if i + 1 < len(chain) else None
            if t[0] == "goto":
                if t[1] is not fall:
                    lines.append("\tR_MOVD MOVD %s" % t[1].name)
            elif t[0] == "test":
                lines.append("\tR_%s %s %s" % (t[1], t[1], t[2].name))
                if t[3] is not fall:
                    lines.append("\tR_MOVD MOVD %s" % t[3].name)
            elif t[0] == "halt":
                lines.append("\tHALT")
            elif t[0] == "rawterm":
                lines.extend("\t" + x for x in t[1])
            else:
                raise ValueError(t)
        out.append("\n".join(lines))

    code = [CODE_PRIMITIVES]
    for f in prog.flags:
        code.append("%s:\n\tMovD/Nop Jmp" % f)
    code.extend(prog.extra_code)
    text = ".CODE\n" + "\n\n".join(code) + "\n\n.DATA\n"
    text += "ENTRY:\n\tR_MOVD MOVD %s\n\n" % entry.name
    text += "\n\n".join(out)
    if prog.extra_data:
        text += "\n\n" + "\n\n".join(prog.extra_data)
    return text + "\n"


def _out_lines(a, cp):
    start = None if a in (None, UNKNOWN) else to_trits(a)
    plan = const_load_plan(start, to_trits(cp))
    lines = []
    for kind, arg in plan:
        if kind == "rot":
            lines.append("\tROT C%d R_ROT" % arg)
        else:
            lines.append("\tOPR %s R_OPR" % fmt_trits(*arg))
    lines.append("\tOUT ?- R_OUT")
    return lines


CODE_PRIMITIVES = """OUT:
\tOut/Nop Jmp

OPR:
\tOpr/Nop Jmp

ROT:
\tRot/Nop Jmp

IN:
\tIn/Nop Jmp

MOVD:
\tNop/MovD Jmp

HALT:
\tHlt

DMOVD:
\tMovD/Nop/Nop/Nop
DM2:
\tMovD/Nop/Nop/Nop/Nop Jmp"""
