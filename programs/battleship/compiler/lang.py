"""
A small structured language on top of the flag/CFG backend.

The only mutable state is a bank of flags (bits).  Everything else -- bytes,
comparisons, loops, a pseudo-random generator, a 2-D board -- is built from
bits and the control-flow primitives in backend.py.  A `Builder` threads a
"current block" through Python control structure so the game reads like
ordinary code.

Guarantees that keep the output runnable on Malbolge Unshackled at any
rotation width:
  * flags only ever toggle (MovD/Nop); they never hold a rotation-dependent
    value;
  * the A register is only ever loaded with explicit constants right before an
    OUT, so stream cells are stable and blocks may be re-entered in loops.
"""

from backend import Program, UNKNOWN
from getc import build_getc, char_code


class Builder:
    def __init__(self):
        self.prog = Program()
        self.entry = self.prog.block("main")
        self.cur = self.entry
        self._getc = None
        self.rng = None

    # -- low level ---------------------------------------------------------
    def bit(self, name):
        return self.prog.flag(name)

    def _goto(self, b):
        self.cur.term = ("goto", b)
        self.cur = b

    def label(self, hint="L"):
        b = self.prog.block(hint)
        self._goto(b)
        return b

    def toggle(self, f):
        self.cur.ops.append(("tog", f))

    def out_char(self, cp):
        self.cur.ops.append(("out", cp))

    def out(self, s):
        for ch in s:
            self.out_char(ord(ch))

    # set/clear a bit to a known value regardless of its current value:
    # test it, and toggle only in the branch where it is set/clear.
    def set_bit(self, f, val):
        one = self.prog.block("set1")
        zero = self.prog.block("set0")
        join = self.prog.block("setj")
        self.cur.term = ("test", f, one, zero)
        # f == 1 branch
        one.ops = [] if val else [("tog", f)]
        one.term = ("goto", join)
        # f == 0 branch
        zero.ops = [("tog", f)] if val else []
        zero.term = ("goto", join)
        self.cur = join

    def if_bit(self, f, val=1):
        """context manager: body runs when f == val (f restored afterwards)."""
        return _If(self, f, val)

    def inc(self, bits):
        """Ripple-increment a little-endian binary counter (overflow ignored)."""
        def step(i):
            if i >= len(bits):
                return
            self.toggle(bits[i])
            with self.if_bit(bits[i], 0):   # carried out of bit i
                step(i + 1)
        step(0)

    def dec(self, bits):
        """Ripple-decrement (underflow ignored)."""
        def step(i):
            if i >= len(bits):
                return
            self.toggle(bits[i])
            with self.if_bit(bits[i], 1):   # borrowed into bit i
                step(i + 1)
        step(0)

    def copy_bit(self, dst, src):
        """dst := src."""
        one = self.prog.block("cp1")
        zero = self.prog.block("cp0")
        join = self.prog.block("cpj")
        self.cur.term = ("test", src, one, zero)
        self.cur = one
        self.set_bit(dst, 1)
        self.cur.term = ("goto", join)
        self.cur = zero
        self.set_bit(dst, 0)
        self.cur.term = ("goto", join)
        self.cur = join

    def copy_bits(self, dst_list, src_list):
        for d, s in zip(dst_list, src_list):
            self.copy_bit(d, s)

    def dispatch_index(self, idx_bits, leaf_fn):
        """Full binary dispatch on a little-endian index register.

        Calls leaf_fn(self, k) with self.cur at the leaf for value k; the leaf
        may terminate itself or fall through to a shared join.  idx_bits are not
        modified.
        """
        join = self.prog.block("dix_join")

        def rec(bit, base):
            if bit < 0:
                leaf_fn(self, base)
                if self.cur.term is None:
                    self.cur.term = ("goto", join)
                return
            one = self.prog.block("dix1")
            zero = self.prog.block("dix0")
            self.cur.term = ("test", idx_bits[bit], one, zero)
            self.cur = one
            rec(bit - 1, base | (1 << bit))
            self.cur = zero
            rec(bit - 1, base)
        rec(len(idx_bits) - 1, 0)
        self.cur = join

    def while_bit(self, f):
        return _While(self, f)

    # -- random numbers ----------------------------------------------------
    # The generator's state is RNG_BITS flags, i.e. RNG_BITS code cells, each
    # sitting at one of the two points of its own xlat2 encryption cycle.
    # Advancing the generator is nothing but a sequence of self-encryptions of
    # those cells: the "if x[j]: toggle x[i]" steps below are each one landing
    # (one encryption) on cell i, guarded by a test of cell j.  The update is
    # Marsaglia's xorshift32 (13, 17, 5), which visits every non-zero state.
    #
    # A Malbolge program is deterministic, so the generator has to be seeded
    # from the one thing that differs between runs: what the player types.
    # While the `seeding` flag is set, every character read by getc is folded
    # into the state; rng_seal() clears it for good.
    RNG_BITS = 32
    RNG_INIT = 0x2545F491

    def rng_init(self):
        self.rng = [self.bit("rng%d" % i) for i in range(self.RNG_BITS)]
        self.seeding = self.bit("rng_seeding")
        self.toggle(self.seeding)
        for i, f in enumerate(self.rng):     # flags start at 0
            if (self.RNG_INIT >> i) & 1:
                self.toggle(f)
        return self.rng

    def _xor_shift(self, shift):
        """state ^= state << shift (shift > 0) or >> -shift, in place."""
        x, n = self.rng, len(self.rng)
        if shift > 0:
            for i in range(n - 1, shift - 1, -1):    # read lower bits first
                with self.if_bit(x[i - shift], 1):
                    self.toggle(x[i])
        else:
            s = -shift
            for i in range(0, n - s):                # read higher bits first
                with self.if_bit(x[i + s], 1):
                    self.toggle(x[i])

    def rng_seal(self):
        """Stop folding input into the generator from here on."""
        self.set_bit(self.seeding, 0)

    def rng_step(self):
        self._xor_shift(13)
        self._xor_shift(-17)
        self._xor_shift(5)

    def rng_mix(self, bits):
        """Fold `bits` into the state, keep it non-zero, then advance."""
        for f, s in zip(bits, self.rng):
            with self.if_bit(f, 1):
                self.toggle(s)
        zero = self.prog.block("rngz")
        ok = self.prog.block("rngok")
        eq_const(self, self.rng, 0, zero, ok)
        self.cur = zero
        self.toggle(self.rng[0])
        self.cur.term = ("goto", ok)
        self.cur = ok
        self.rng_step()

    # -- getc --------------------------------------------------------------
    # getc is one shared subroutine.  A caller sets a unique return id, jumps to
    # the entry, and the subroutine's exit dispatches the id back to the caller's
    # own continuation block.  The exit dispatch is wired up in source().
    def _ensure_getc(self):
        if self._getc is not None:
            return
        self.in_flags = [self.bit("in%d" % i) for i in range(8)]
        self._ret_bits = [self.bit("ret%d" % i) for i in range(8)]
        self._ret_targets = []       # return blocks, indexed by id
        ge, ga = build_getc(self.prog, self.in_flags)
        self._getc = (ge, ga)

    def getc_bits(self):
        """8 flags holding the code of the next input character.

        The flags are reused across calls, and are 0 before each read.
        """
        self._ensure_getc()
        ge, _ = self._getc
        rid = len(self._ret_targets)
        ret = self.prog.block("getc_ret")
        self._ret_targets.append(ret)
        for i, f in enumerate(self._ret_bits):
            self.set_bit(f, (rid >> i) & 1)
        self.cur.term = ("goto", ge)
        self.cur = ret
        return self.in_flags

    def clear_in(self):
        for f in self.in_flags:
            self.set_bit(f, 0)

    def finish(self):
        self.cur.term = ("halt",)

    def source(self):
        from backend import emit_hell
        if self._getc is not None:
            _, ga = self._getc
            self.cur = ga
            if self.rng:
                # keystrokes stir the generator until it is sealed
                with self.if_bit(self.seeding, 1):
                    self.rng_mix(self.in_flags)
            ga = self.cur
            # wire the shared exit to dispatch the return id back to each caller
            targets = self._ret_targets
            self.cur = ga

            def leaf(bb, k):
                if k < len(targets):
                    bb.cur.term = ("goto", targets[k])
            self.dispatch_index(self._ret_bits, leaf)
            # unused ids (k >= len(targets)) fall through to the join, then halt
            self.cur.term = ("halt",)
        return emit_hell(self.prog, self.entry)


class _If:
    def __init__(self, b, f, val=1):
        self.b = b
        self.f = f
        self.val = val

    def __enter__(self):
        self.body = self.b.prog.block("if_body")
        self.join = self.b.prog.block("if_join")
        one = self.body if self.val else self.join
        zero = self.join if self.val else self.body
        self.b.cur.term = ("test", self.f, one, zero)
        self.b.cur = self.body
        return self

    def __exit__(self, *a):
        if self.b.cur.term is None:
            self.b.cur.term = ("goto", self.join)
        self.b.cur = self.join
        return False


class _While:
    def __init__(self, b, f):
        self.b = b
        self.f = f

    def __enter__(self):
        self.head = self.b.prog.block("wh_head")
        self.body = self.b.prog.block("wh_body")
        self.join = self.b.prog.block("wh_join")
        self.b._goto(self.head)
        self.head.term = ("test", self.f, self.body, self.join)
        self.b.cur = self.body
        return self

    def __exit__(self, *a):
        if self.b.cur.term is None:
            self.b.cur.term = ("goto", self.head)
        self.b.cur = self.join
        return False


def match_char(b, in_flags, cases, default=None):
    """Dispatch on the 8-bit input code.

    `cases` maps a character (int code point, or 'EOF'/'NL_MU') to a callback
    taking the builder.  Emits a decision tree on the 8 code bits.
    """
    def code(c):
        if isinstance(c, str) and c not in ("EOF", "NL_MU"):
            return char_code(ord(c))
        return char_code(c)
    join = b.prog.block("mj")
    for c, cb in cases.items():
        hit = b.prog.block("hit")
        miss = b.prog.block("miss")
        eq_const(b, in_flags, code(c), hit, miss)
        b.cur = hit
        cb(b)
        if b.cur.term is None:
            b.cur.term = ("goto", join)
        b.cur = miss
    if default is not None:
        default(b)
    if b.cur.term is None:
        b.cur.term = ("goto", join)
    b.cur = join


def eq_const(b, flags, code, then_block, else_block):
    """Branch to then_block if the 8 bits equal `code`, else else_block.

    Flags are left unchanged (test toggles twice).  Tests bits high-to-low;
    any mismatch jumps straight to else_block.
    """
    cur = b.cur
    for i in reversed(range(len(flags))):
        want = (code >> i) & 1
        nxt = b.prog.block("eqn")
        one = nxt if want else else_block
        zero = else_block if want else nxt
        cur.term = ("test", flags[i], one, zero)
        cur = nxt
    cur.term = ("goto", then_block)
    b.cur = then_block
