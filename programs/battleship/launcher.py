#!/usr/bin/env python3
"""
Launcher for Battleship-in-Malbolge.

Malbolge Unshackled has no random-number source, no command-line arguments and
no file I/O.  This launcher does the one thing the language cannot: it places
two random fleets and streams them to the program's stdin (64 cells for the
enemy board, then 64 for the player board, as '0'/'1').  Everything after that
-- turns, the computer opponent, win/lose, rendering -- runs inside Malbolge.

Usage:
    python3 launcher.py [--seed N] [--interp PATH] [program.mu]

It keeps your keyboard connected to the game: the fleet bytes are injected
ahead of your typing via a pseudo-terminal, so you just play.
"""
import argparse
import os
import pty
import random
import select
import sys
import termios
import tty

N = 8
SHIPS = [5, 4, 3, 2]


def random_fleet(rng):
    grid = [[0] * N for _ in range(N)]
    for length in SHIPS:
        while True:
            horiz = rng.random() < 0.5
            if horiz:
                r = rng.randrange(N)
                c = rng.randrange(N - length + 1)
                cells = [(r, c + i) for i in range(length)]
            else:
                r = rng.randrange(N - length + 1)
                c = rng.randrange(N)
                cells = [(r + i, c) for i in range(length)]
            if any(grid[rr][cc] for rr, cc in cells):
                continue
            # keep ships from touching (classic rule)
            touch = False
            for rr, cc in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        r2, c2 = rr + dr, cc + dc
                        if 0 <= r2 < N and 0 <= c2 < N and grid[r2][c2]:
                            touch = True
            if touch:
                continue
            for rr, cc in cells:
                grid[rr][cc] = 1
            break
    return "".join(str(grid[r][c]) for r in range(N) for c in range(N))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("program", nargs="?", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--interp", default=None, help="Malbolge interpreter (default: tools/mu next to this file)")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    program = args.program or os.path.join(here, "game", "battleship.mu")
    interp = args.interp or os.path.join(here, "tools", "mu")
    if not os.path.exists(program):
        sys.exit("program not found: %s (build it with make)" % program)
    if not os.path.exists(interp):
        sys.exit("interpreter not found: %s (build it with make)" % interp)

    rng = random.Random(args.seed)
    enemy = random_fleet(rng)
    player = random_fleet(rng)
    prelude = (enemy + player).encode()

    # Run the interpreter under a pty so the game sees a terminal, then copy
    # the fleet prelude in first and bridge the keyboard afterwards.
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(interp, [interp, program])
        os._exit(127)

    # Put the pty in raw mode: the game reads bytes one at a time, so we must
    # not let the terminal line-discipline buffer input until a newline or echo
    # typed characters back into the output.
    try:
        mode = termios.tcgetattr(master)
        tty.setraw(master)
        # keep output post-processing off so ANSI passes through untouched
        termios.tcsetattr(master, termios.TCSANOW, termios.tcgetattr(master))
        del mode
    except (termios.error, OSError):
        pass

    os.write(master, prelude)

    old = None
    if sys.stdin.isatty():
        old = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin)
    watch_stdin = True
    try:
        while True:
            watched = [master] + ([sys.stdin] if watch_stdin else [])
            r, _, _ = select.select(watched, [], [])
            if master in r:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
            if watch_stdin and sys.stdin in r:
                data = os.read(sys.stdin.fileno(), 4096)
                if not data:
                    # keyboard/pipe closed: stop forwarding input but keep
                    # draining the game's output until it exits
                    watch_stdin = False
                    continue
                os.write(master, data)
    finally:
        if old is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass


if __name__ == "__main__":
    main()
