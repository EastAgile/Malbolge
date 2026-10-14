#!/usr/bin/env python3
"""
Battleship in Python, written to behave exactly like the Malbolge version.

Same rules, same computer opponent, same xorshift32 generator seeded the same
way (the admiral's name places your fleet, the name plus your first shot place
the enemy's, then the generator stops reading the keyboard), and the same
output, byte for byte, for the same keystrokes.  The input quirks are copied
too: characters are compared through the same 8-bit code the Malbolge input
decoder produces, so characters 243 apart are indistinguishable, just as they
are in the Malbolge program.

Usage:  python3 battleship.py        (play in your terminal)
"""
import sys

N = 8
SHIPS = (5, 4, 3, 2)
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

RNG_INIT = 0x2545F491
MASK = 0xFFFFFFFF


# -- input codes -------------------------------------------------------------
# The Malbolge program reads a character as the low five trits of its value
# and turns them into an 8-bit code.  Newline and EOF have their own values.

def _gray(x):
    return x ^ (x >> 1)


def _code_of_trits(trits):
    j = sum({0: 1, 1: 0, 2: 2}[t] * 3 ** i for i, t in enumerate(trits))
    return _gray(j) ^ _gray(243)


def code(ch):
    """8-bit input code of a character (str of length 1), or None for EOF."""
    if ch is None:
        return _code_of_trits([2] * 5)
    if ch == "\n":
        return _code_of_trits([1, 2, 2, 2, 2])
    v = ord(ch)
    return _code_of_trits([(v // 3 ** i) % 3 for i in range(5)])


EOF, NL = code(None), code("\n")


# -- the generator -----------------------------------------------------------

class Rng:
    def __init__(self):
        self.x = RNG_INIT
        self.seeding = True

    def step(self):
        x = self.x
        x ^= (x << 13) & MASK
        x ^= x >> 17
        x ^= (x << 5) & MASK
        self.x = x

    def mix(self, c):
        self.x ^= c
        if self.x == 0:
            self.x = 1
        self.step()


# -- the game ----------------------------------------------------------------

class Quit(Exception):
    pass


class Game:
    def __init__(self, read, write):
        self._read = read          # () -> str of length 1, or None at EOF
        self.write = write
        self.rng = Rng()
        self.eship = [0] * 64
        self.eshot = [0] * 64
        self.pship = [0] * 64
        self.pshot = [0] * 64
        self.ehits = 0
        self.phits = 0
        self.tgt = False
        self.anchor = 0

    def getc(self):
        c = code(self._read())
        if self.rng.seeding:
            self.rng.mix(c)
        return c

    def drain(self):
        """Read to the end of the line; EOF quits."""
        while True:
            c = self.getc()
            if c == NL:
                return
            if c == EOF:
                raise Quit

    # -- fleets ----------------------------------------------------------------
    def place_fleet(self):
        while True:                        # restart the whole board
            ships = [0] * 64
            blocked = [0] * 64
            for length in SHIPS:
                tries = 0
                while True:
                    self.rng.step()
                    k = self.rng.x & 63
                    horiz = (self.rng.x >> 6) & 1
                    r, c = divmod(k, N)
                    cells = None
                    if (c if horiz else r) + length <= N:
                        cells = [r * N + c + i if horiz else (r + i) * N + c
                                 for i in range(length)]
                        if any(blocked[x] for x in cells):
                            cells = None
                    if cells is not None:
                        break
                    tries = (tries + 1) & 255
                    if tries == 0:
                        break
                if cells is None:
                    break                  # 256 misses: start the board over
                for x in cells:
                    ships[x] = 1
                    cr, cc = divmod(x, N)
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if 0 <= cr + dr < N and 0 <= cc + dc < N:
                                blocked[(cr + dr) * N + cc + dc] = 1
            else:
                return ships

    # -- rendering -------------------------------------------------------------
    def render(self):
        w = self.write
        w(CLEAR)
        w(BOLD + "   Enemy waters\n" + R)
        w(GREY + "    A B C D E F G H\n" + R)
        for r in range(N):
            w("  %d " % (r + 1))
            for c in range(N):
                k = r * N + c
                if self.eshot[k]:
                    w(RED + "X " + R if self.eship[k] else BLUE + "o " + R)
                else:
                    w(GREY + ". " + R)
            w("\n")
        w(BOLD + "\n   Your fleet\n" + R)
        w(GREY + "    A B C D E F G H\n" + R)
        for r in range(N):
            w("  %d " % (r + 1))
            for c in range(N):
                k = r * N + c
                if self.pship[k]:
                    w(RED + "X " + R if self.pshot[k] else GREEN + "# " + R)
                else:
                    w(BLUE + "o " + R if self.pshot[k] else CYAN + "~ " + R)
            w("\n")
        w("\n")

    # -- turns -----------------------------------------------------------------
    def read_shot(self):
        """Return the target cell, or None to redraw and ask again."""
        c = self.getc()
        if c in (code("Q"), code("q"), EOF):
            raise Quit
        col = next((d for d in range(N)
                    if c in (code(chr(65 + d)), code(chr(97 + d)))), None)
        if col is not None:
            c = self.getc()
            row = next((d for d in range(N) if c == code(chr(49 + d))), None)
            if row is not None:
                self.drain()
                return row * N + col
        self.write(YELLOW + "  ? type like C5\n" + R)
        self.drain()
        return None

    def computer_turn(self):
        w = self.write
        w(BOLD + "Computer is thinking...\n" + R)
        target = None
        if self.tgt:
            ar, ac = divmod(self.anchor, N)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):   # U D L R
                r, c = ar + dr, ac + dc
                if 0 <= r < N and 0 <= c < N and not self.pshot[r * N + c]:
                    target = r * N + c
                    break
            if target is None:
                self.tgt = False                                # back to hunting
        while target is None:
            self.rng.step()
            k = self.rng.x & 63
            if not self.pshot[k]:
                target = k
        self.pshot[target] = 1
        hit = self.pship[target]
        w(BOLD + "Computer fires at " + R)
        w(chr(65 + target % N) + chr(49 + target // N))
        if hit:
            w(RED + BOLD + " - HIT!\n" + R)
            self.phits += 1
            if not self.tgt:
                self.tgt = True
                self.anchor = target
            if self.phits == FLEET_CELLS:
                return "lose"
        else:
            w(BLUE + " - miss.\n" + R)
        return None

    def play(self):
        w = self.write
        try:
            w(CLEAR + BOLD + CYAN + "BATTLESHIP" + R + "  (in Malbolge Unshackled)\n\n")
            w("Malbolge has no clock and no random source, so the sea is stirred by\n")
            w("what you type.  Each key is folded into a generator built from\n")
            w("self-encrypting Malbolge code cells.  Your name places your fleet.\n")
            w("The enemy fleet does not exist until you fire your first shot: your\n")
            w("name and that shot place it, then the shot is scored against it.\n")
            w("After that the generator stops listening to the keyboard.\n\n")
            w(BOLD + "Name your admiral" + R + " (any text, then Enter): ")
            while self.getc() not in (NL, EOF):
                pass
            for _ in range(8):
                self.rng.step()
            w("\nPlacing your fleet...\n")
            self.pship = self.place_fleet()
            while True:
                self.render()
                w(BOLD + "Your shot" + R + " (column A-H, row 1-8, e.g. C5; Q quits): ")
                k = self.read_shot()
                if k is None:
                    continue
                if self.rng.seeding:
                    self.eship = self.place_fleet()
                    self.rng.seeding = False
                    w(GREY + "  (the enemy fleet is now at sea)\n" + R)
                if self.eshot[k]:
                    w(YELLOW + "  Already fired there.\n" + R)
                    continue
                self.eshot[k] = 1
                if self.eship[k]:
                    w(RED + BOLD + "  HIT!\n" + R)
                    self.ehits += 1
                    if self.ehits == FLEET_CELLS:
                        self.render()
                        w(BOLD + GREEN + "You sank the enemy fleet. Victory!\n" + R)
                        return
                else:
                    w(BLUE + "  Miss.\n" + R)
                if self.computer_turn() == "lose":
                    self.render()
                    w(BOLD + RED + "Your fleet is destroyed. Defeat.\n" + R)
                    return
                w(GREY + "(press Enter)\n" + R)
                self.drain()
        except Quit:
            w("\nAbandoning ship. Bye.\n")


def run(text):
    """Play a whole game on `text` as the keyboard; return everything printed."""
    chars = iter(text)
    out = []
    Game(lambda: next(chars, None), out.append).play()
    return "".join(out)


def main():
    out = sys.stdout

    def read():
        out.flush()
        ch = sys.stdin.read(1)
        return ch or None

    Game(read, out.write).play()
    out.flush()


if __name__ == "__main__":
    main()
