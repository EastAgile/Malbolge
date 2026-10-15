"""
Battleship, compiled to Malbolge Unshackled.

Everything -- the random fleets, all game state, the computer opponent's
hunt/target logic and the ANSI board rendering -- is generated as HeLL and
assembled by LMFAO.  Nothing runs on the host but the interpreter.  The fleets
come from a xorshift generator whose state bits are self-encrypting code cells,
seeded by what the player types (a Malbolge program has no other entropy):
the admiral's name places the player's fleet, the name plus the first shot
places the enemy's, and after that no keystroke reaches the generator.

Board: 8x8.  Cell k = row*8 + col (row,col in 0..7); the shared index register
holds col in bits 0..2 and row in bits 3..5, so no multiplication is needed.
Fleet: ships of length 5,4,3,2 -> 14 cells; a side loses when all 14 are hit.
"""

import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lang import Builder, eq_const
from getc import char_code

N = 8
NCELLS = N * N
SHIPS = [5, 4, 3, 2]
FLEET_CELLS = sum(SHIPS)

CLEAR = "\x1b[2J\x1b[H"
R = "\x1b[0m"
BOLD = "\x1b[1m"
RED = "\x1b[91m"
GREEN = "\x1b[92m"
BLUE = "\x1b[94m"
CYAN = "\x1b[96m"
GREY = "\x1b[90m"
YELLOW = "\x1b[93m"


def build():
    b = Builder()
    P = b.prog

    # ---- state -----------------------------------------------------------
    eship = [b.bit("eship%d" % k) for k in range(NCELLS)]
    eshot = [b.bit("eshot%d" % k) for k in range(NCELLS)]
    pship = [b.bit("pship%d" % k) for k in range(NCELLS)]
    pshot = [b.bit("pshot%d" % k) for k in range(NCELLS)]
    ehits = [b.bit("ehit%d" % i) for i in range(4)]
    phits = [b.bit("phit%d" % i) for i in range(4)]
    idx = [b.bit("idx%d" % i) for i in range(6)]
    cand = [b.bit("cand%d" % i) for i in range(6)]
    was_hit = b.bit("was_hit")
    already = b.bit("already")
    tmp = b.bit("tmp")
    found = b.bit("found")
    # AI memory
    tgt = b.bit("tgt_active")
    anchor = [b.bit("anchor%d" % i) for i in range(6)]

    acol, arow = anchor[0:3], anchor[3:6]
    ccol, crow = cand[0:3], cand[3:6]
    icol, irow = idx[0:3], idx[3:6]

    def read_char():
        """Leave the 8 input flags holding the next char; caller clears."""
        return b.getc_bits()

    # ---- helpers ---------------------------------------------------------
    def set_reg(dst_bits, value):
        for i, f in enumerate(dst_bits):
            b.set_bit(f, (value >> i) & 1)

    def read_table(table, idx_bits, dst):
        """dst := table[idx]."""
        b.set_bit(dst, 0)
        def leaf(bb, k):
            with bb.if_bit(table[k], 1):
                bb.set_bit(dst, 1)
        b.dispatch_index(idx_bits, leaf)

    def resolve(ship, shot):
        """Fire at cell `idx` on (ship,shot).  Sets was_hit and already."""
        b.set_bit(was_hit, 0)
        b.set_bit(already, 0)
        def leaf(bb, k):
            with bb.if_bit(shot[k], 1):
                bb.set_bit(already, 1)
            with bb.if_bit(shot[k], 0):
                bb.set_bit(shot[k], 1)
                with bb.if_bit(ship[k], 1):
                    bb.set_bit(was_hit, 1)
        b.dispatch_index(idx, leaf)

    # ---- intro / seeding ---------------------------------------------------
    rng = b.rng_init()
    b.out(CLEAR + BOLD + CYAN + "BATTLESHIP" + R + "  (in Malbolge Unshackled)\n\n")
    b.out("Malbolge has no clock and no random source, so the sea is stirred by\n")
    b.out("what you type.  Each key is folded into a generator built from\n")
    b.out("self-encrypting Malbolge code cells.  Your name places your fleet.\n")
    b.out("The enemy fleet does not exist until you fire your first shot: your\n")
    b.out("name and that shot place it, then the shot is scored against it.\n")
    b.out("After that the generator stops listening to the keyboard.\n\n")
    b.out(BOLD + "Name your admiral" + R + " (any text, then Enter): ")
    # read to end of line; getc mixes each character into the generator
    nm = b.label("name")
    ni = read_char()
    nn = P.block("nn"); nc = P.block("nc")
    eq_const(b, ni, char_code("NL_MU"), nn, nc)
    b.cur = nc
    ne = P.block("ne"); nk = P.block("nk")
    eq_const(b, ni, char_code("EOF"), ne, nk)
    b.cur = ne; b.clear_in(); b.cur.term = ("goto", nn)
    b.cur = nk; b.clear_in(); b.cur.term = ("goto", nm)
    b.cur = nn
    b.clear_in()
    # a few extra rounds so that one-letter names still differ in every bit
    spin = [b.bit("spin%d" % i) for i in range(3)]
    sp = b.label("spin")
    b.rng_step()
    b.inc(spin)
    sd = P.block("spin_done")
    eq_const(b, spin, 0, sd, sp)
    b.cur = sd

    # ---- fleet placement -------------------------------------------------
    # One routine places a fleet, one ship at a time: draw a start cell and an
    # orientation from the generator, reject the draw if the ship would leave
    # the board or touch a ship already placed, else commit it.  `blocked`
    # marks every placed cell and its 8 neighbours.  If a ship fails 256 draws
    # in a row the board is cleared and started over, so no arrangement can
    # wedge the loop.
    #
    # It runs twice.  First, straight after the name, for the player's fleet.
    # Second, after the player's first shot has been read (every key of it
    # folded into the generator), for the enemy's fleet; the routine then
    # seals the generator and jumps to `fire_b`, which scores that shot.
    b.out("\nPlacing your fleet...\n")
    setup_done = P.block("setup_done")
    fire_b = P.block("fire")
    sship = [b.bit("sship%d" % k) for k in range(NCELLS)]
    blocked = [b.bit("blk%d" % k) for k in range(NCELLS)]
    tries = [b.bit("try%d" % i) for i in range(8)]
    second = b.bit("second_board")
    pos, horiz = rng[0:6], rng[6]

    restart = b.label("place_restart")
    for k in range(NCELLS):
        b.set_bit(sship[k], 0)
        b.set_bit(blocked[k], 0)

    for length in SHIPS:
        set_reg(tries, 0)
        attempt = b.label("place%d" % length)
        b.rng_step()
        placed = P.block("placed%d" % length)
        fail = P.block("fail%d" % length)
        hb = P.block("horiz"); vb = P.block("vert")
        b.cur.term = ("test", horiz, hb, vb)
        for is_h, blk in ((True, hb), (False, vb)):
            b.cur = blk

            def leaf(bb, k, is_h=is_h, length=length, placed=placed, fail=fail):
                r, c = divmod(k, N)
                if (c if is_h else r) + length > N:
                    bb.cur.term = ("goto", fail)
                    return
                cells = [r * N + c + i if is_h else (r + i) * N + c
                         for i in range(length)]
                for cell in cells:
                    nxt = P.block("free")
                    bb.cur.term = ("test", blocked[cell], fail, nxt)
                    bb.cur = nxt
                halo = set()
                for cell in cells:
                    bb.toggle(sship[cell])          # known 0: cell is unblocked
                    cr, cc = divmod(cell, N)
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if 0 <= cr + dr < N and 0 <= cc + dc < N:
                                halo.add((cr + dr) * N + cc + dc)
                for cell in sorted(halo):
                    bb.set_bit(blocked[cell], 1)
                bb.cur.term = ("goto", placed)
            b.dispatch_index(pos, leaf)
        b.cur = fail
        b.inc(tries)
        eq_const(b, tries, 0, restart, attempt)   # 256 misses: start over
        b.cur = placed

    # hand the finished board to its owner
    with b.if_bit(second, 0):
        for k in range(NCELLS):
            with b.if_bit(sship[k], 1):
                b.toggle(pship[k])
        b.toggle(second)
        b.cur.term = ("goto", setup_done)
    for k in range(NCELLS):
        with b.if_bit(sship[k], 1):
            b.toggle(eship[k])
    # Both fleets are now fixed.  Stop listening to the keyboard: from here on
    # the generator only feeds the computer's hunt, and play cannot steer it.
    b.rng_seal()
    b.out(GREY + "  (the enemy fleet is now at sea)\n" + R)
    b.cur.term = ("goto", fire_b)
    b.cur = setup_done

    # ---- rendering -------------------------------------------------------
    def render():
        b.out(CLEAR)
        b.out(BOLD + "   Enemy waters\n" + R)
        b.out(GREY + "    A B C D E F G H\n" + R)
        for r in range(N):
            b.out("  %d " % (r + 1))
            for c in range(N):
                k = r * N + c
                one = P.block("e_s1"); zero = P.block("e_s0"); j = P.block("e_j")
                b.cur.term = ("test", eshot[k], one, zero)
                # shot here
                b.cur = one
                h1 = P.block("e_h1"); h0 = P.block("e_h0"); hj = P.block("e_hj")
                b.cur.term = ("test", eship[k], h1, h0)
                b.cur = h1; b.out(RED + "X " + R); b.cur.term = ("goto", hj)
                b.cur = h0; b.out(BLUE + "o " + R); b.cur.term = ("goto", hj)
                b.cur = hj; b.cur.term = ("goto", j)
                # no shot
                b.cur = zero; b.out(GREY + ". " + R); b.cur.term = ("goto", j)
                b.cur = j
            b.out("\n")
        b.out(BOLD + "\n   Your fleet\n" + R)
        b.out(GREY + "    A B C D E F G H\n" + R)
        for r in range(N):
            b.out("  %d " % (r + 1))
            for c in range(N):
                k = r * N + c
                # priority: ship+shot -> X red; ship -> # green; shot -> o blue; else ~ cyan
                s1 = P.block("p_s1"); s0 = P.block("p_s0"); j = P.block("p_j")
                b.cur.term = ("test", pship[k], s1, s0)
                # has ship
                b.cur = s1
                a1 = P.block("p_a1"); a0 = P.block("p_a0"); aj = P.block("p_aj")
                b.cur.term = ("test", pshot[k], a1, a0)
                b.cur = a1; b.out(RED + "X " + R); b.cur.term = ("goto", aj)
                b.cur = a0; b.out(GREEN + "# " + R); b.cur.term = ("goto", aj)
                b.cur = aj; b.cur.term = ("goto", j)
                # no ship
                b.cur = s0
                n1 = P.block("p_n1"); n0 = P.block("p_n0"); nj = P.block("p_nj")
                b.cur.term = ("test", pshot[k], n1, n0)
                b.cur = n1; b.out(BLUE + "o " + R); b.cur.term = ("goto", nj)
                b.cur = n0; b.out(CYAN + "~ " + R); b.cur.term = ("goto", nj)
                b.cur = nj; b.cur.term = ("goto", j)
                b.cur = j
            b.out("\n")
        b.out("\n")

    def print_cell_from(idx_bits):
        """Print the human cell name (letter+digit) for an index register."""
        # column letter
        def lcol(bb, k):
            bb.out_char(ord("A") + k)
        b.dispatch_index(icol if idx_bits is idx else idx_bits[0:3], lcol)
        def lrow(bb, k):
            bb.out_char(ord("1") + k)
        b.dispatch_index(idx_bits[3:6], lrow)

    # ---- main loop -------------------------------------------------------
    top = b.label("turn")
    render()
    win = P.block("win")
    lose = P.block("lose")
    quit_b = P.block("quit")

    # player input: column
    b.out(BOLD + "Your shot" + R + " (column A-H, row 1-8, e.g. C5; Q quits): ")
    inf = read_char()
    reprompt = P.block("reprompt")
    # if Q/q/EOF -> quit; elif A-H -> set col; else reprompt
    chain_after = P.block("after_col")
    # quit tests
    for ch in ("Q", "q", "EOF"):
        hit = P.block("qh"); miss = P.block("qm")
        eq_const(b, inf, char_code(ch) if ch == "EOF" else char_code(ord(ch)), hit, miss)
        b.cur = hit; b.cur.term = ("goto", quit_b)
        b.cur = miss
    # columns
    for d in range(N):
        for ch in (chr(ord("A") + d), chr(ord("a") + d)):
            hit = P.block("ch"); miss = P.block("cm")
            eq_const(b, inf, char_code(ord(ch)), hit, miss)
            b.cur = hit
            set_reg(icol, d)
            b.cur.term = ("goto", chain_after)
            b.cur = miss
    # unknown column
    b.cur.term = ("goto", reprompt)

    # reprompt: consume rest of line then loop to render
    b.cur = reprompt
    b.clear_in()
    b.out(YELLOW + "  ? type like C5\n" + R)
    # drain to newline
    drain = b.label("drain")
    di = read_char()
    dn = P.block("dn"); dc = P.block("dc")
    eq_const(b, di, char_code("NL_MU"), dn, dc)
    b.cur = dc
    de = P.block("de"); dk = P.block("dk")
    eq_const(b, di, char_code("EOF"), de, dk)
    b.cur = de; b.cur.term = ("goto", quit_b)
    b.cur = dk; b.clear_in(); b.cur.term = ("goto", drain)
    b.cur = dn; b.clear_in(); b.cur.term = ("goto", top)

    # after column: read row digit
    b.cur = chain_after
    b.clear_in()
    inf = read_char()
    row_after = P.block("after_row")
    for d in range(N):
        hit = P.block("rh"); miss = P.block("rm")
        eq_const(b, inf, char_code(ord("1") + d), hit, miss)
        b.cur = hit
        set_reg(irow, d)
        b.cur.term = ("goto", row_after)
        b.cur = miss
    b.cur.term = ("goto", reprompt)

    # after row: drain to newline, then fire
    b.cur = row_after
    b.clear_in()
    dr = b.label("drow")
    dri = read_char()
    drn = P.block("drn"); drc = P.block("drc")
    eq_const(b, dri, char_code("NL_MU"), drn, drc)
    b.cur = drc
    dre = P.block("dre"); drk = P.block("drk")
    eq_const(b, dri, char_code("EOF"), dre, drk)
    b.cur = dre; b.cur.term = ("goto", quit_b)
    b.cur = drk; b.clear_in(); b.cur.term = ("goto", dr)
    b.cur = drn; b.clear_in()

    # first shot: the enemy fleet does not exist yet, so place it now (from
    # the name and every key of this shot), then score the shot against it
    b.cur.term = ("test", b.seeding, restart, fire_b)
    b.cur = fire_b

    # resolve player's shot on the enemy board
    resolve(eship, eshot)
    with b.if_bit(already, 1):
        b.out(YELLOW + "  Already fired there.\n" + R)
        b.cur.term = ("goto", top)
    with b.if_bit(was_hit, 1):
        b.out(RED + BOLD + "  HIT!\n" + R)
        b.inc(ehits)
        w1 = P.block("w1"); w0 = P.block("w0")
        eq_const(b, ehits, FLEET_CELLS, w1, w0)
        b.cur = w1; b.cur.term = ("goto", win)
        b.cur = w0
    with b.if_bit(was_hit, 0):
        b.out(BLUE + "  Miss.\n" + R)

    # ---- computer turn ---------------------------------------------------
    b.out(BOLD + "Computer is thinking...\n" + R)
    b.set_bit(found, 0)

    def try_dir(kind):
        # kind: 'U','D','L','R'.  If in bounds and target unshot, set idx & found.
        skip = P.block("tdskip")
        with b.if_bit(found, 0):
            b.copy_bits(cand, anchor)
            # bounds check on the anchor sub-register
            sub = arow if kind in "UD" else acol
            csub = crow if kind in "UD" else ccol
            inb = P.block("inb"); oob = P.block("oob"); j = P.block("tdj")
            if kind in "UL":
                # need sub > 0  <=> not (sub == 0)
                z1 = P.block("z1"); z0 = P.block("z0")
                eq_const(b, sub, 0, z1, z0)
                b.cur = z1; b.cur.term = ("goto", oob)   # == 0 -> out of bounds
                b.cur = z0; b.cur.term = ("goto", inb)
            else:
                # need sub < 7 <=> not (sub == 7)
                z1 = P.block("s1"); z0 = P.block("s0")
                eq_const(b, sub, N - 1, z1, z0)
                b.cur = z1; b.cur.term = ("goto", oob)
                b.cur = z0; b.cur.term = ("goto", inb)
            b.cur = inb
            if kind in "UL":
                b.dec(csub)
            else:
                b.inc(csub)
            read_table(pshot, cand, tmp)
            with b.if_bit(tmp, 0):     # not yet shot -> take it
                b.copy_bits(idx, cand)
                b.set_bit(found, 1)
            b.cur.term = ("goto", j)
            b.cur = oob
            b.cur.term = ("goto", j)
            b.cur = j
        b.cur.term = ("goto", skip) if b.cur.term is None else b.cur.term
        b.cur = skip

    with b.if_bit(tgt, 1):
        for kind in ("U", "D", "L", "R"):
            try_dir(kind)
        with b.if_bit(found, 0):
            b.set_bit(tgt, 0)   # exhausted: back to hunt

    # hunt: fire at a random cell not yet shot
    with b.if_bit(found, 0):
        scan = b.label("scan")
        b.rng_step()
        read_table(pshot, pos, tmp)
        with b.if_bit(tmp, 0):
            b.copy_bits(idx, pos)
            b.set_bit(found, 1)
        with b.if_bit(found, 0):
            b.cur.term = ("goto", scan)

    # fire on the player's board
    resolve(pship, pshot)
    b.out(BOLD + "Computer fires at " + R)
    print_cell_from(idx)
    with b.if_bit(was_hit, 1):
        b.out(RED + BOLD + " - HIT!\n" + R)
        b.inc(phits)
        # update target memory
        with b.if_bit(tgt, 0):
            b.set_bit(tgt, 1)
            b.copy_bits(anchor, idx)
        l1 = P.block("l1"); l0 = P.block("l0")
        eq_const(b, phits, FLEET_CELLS, l1, l0)
        b.cur = l1; b.cur.term = ("goto", lose)
        b.cur = l0
    with b.if_bit(was_hit, 0):
        b.out(BLUE + " - miss.\n" + R)

    # pause for a keypress so the player sees the result, then next turn
    b.out(GREY + "(press Enter)\n" + R)
    pz = b.label("pz")
    pzi = read_char()
    pzn = P.block("pzn"); pzc = P.block("pzc")
    eq_const(b, pzi, char_code("NL_MU"), pzn, pzc)
    b.cur = pzc
    pze = P.block("pze"); pzk = P.block("pzk")
    eq_const(b, pzi, char_code("EOF"), pze, pzk)
    b.cur = pze; b.cur.term = ("goto", quit_b)
    b.cur = pzk; b.clear_in(); b.cur.term = ("goto", pz)
    b.cur = pzn; b.clear_in(); b.cur.term = ("goto", top)

    # ---- endings ---------------------------------------------------------
    b.cur = win
    render()
    b.out(BOLD + GREEN + "You sank the enemy fleet. Victory!\n" + R)
    b.finish()

    b.cur = lose
    render()
    b.out(BOLD + RED + "Your fleet is destroyed. Defeat.\n" + R)
    b.finish()

    b.cur = quit_b
    b.out("\nAbandoning ship. Bye.\n")
    b.finish()

    return b.source()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "battleship.hell"
    open(out, "w").write(build())
    sys.stderr.write("wrote %s\n" % out)
