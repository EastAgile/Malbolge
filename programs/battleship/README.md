# Battleship, in Malbolge

A complete, playable game of Battleship whose entire rule set, computer
opponent, and board rendering run inside [Malbolge](https://en.wikipedia.org/wiki/Malbolge)
&mdash; a language designed to be almost impossible to program. You play in your
terminal against a computer that hunts your fleet; every decision it makes is
computed by a Malbolge program.

```
   Enemy waters            Your fleet
    A B C D E F G H         A B C D E F G H
  1 . . X o . . . .       1 ~ ~ ~ # # # # #
  2 . . X . . . . .       2 ~ ~ ~ ~ ~ ~ ~ ~
  3 . . X . . . . .       3 ~ ~ ~ # ~ ~ ~ ~
  ...                      ...
```

## Why this is hard

Malbolge has no variables, no functions, and no arithmetic you can just write
down: every instruction encrypts itself after it runs, the three-valued "crazy"
operator is its only logic gate, and in the Turing-complete *Unshackled*
variant the machine's word size is unknown and grows as the program runs. There
is also **no random number generator, no command-line arguments, and no file
access**. Most published Malbolge programs are a few lines long; a few large
ones (a Lisp, a lambda-calculus evaluator) exist but are tens of megabytes and
run for minutes.

This project builds a real, interactive game on that substrate.

## How it works

Everything that *is* the game runs in Malbolge Unshackled:

- **State** is held in self-restoring two-state code cells ("flags"). Bytes,
  an 8&times;8 board for each side, hit counters, and the AI's memory are all
  built from flags.
- **Input** is decoded width-independently: each keypress is turned into an
  8-bit code by a 243-way jump table, so it works whatever rotation width the
  interpreter happens to choose.
- **The computer opponent** plays *hunt and target*: it searches until it hits a
  ship, then works along that ship's neighbours until it sinks, then resumes
  searching. This logic is compiled to Malbolge, not done on the host.
- **Rendering** is ANSI colour text, drawn by Malbolge `OUT` instructions.

The only thing the host does is the one thing Malbolge cannot: a thin Python
**launcher** places two random fleets (Malbolge has no RNG) and streams them to
the program's standard input before play begins. After that, the launcher just
forwards your keystrokes.

The game is written in a tiny structured language (bits, `if`/`while`, counters,
indexed board access) that a small compiler in `compiler/` lowers to **HeLL**,
Matthias Lutter's Malbolge assembly, which
[LMFAO](https://github.com/esoteric-programmer/LMFAO) assembles into a Malbolge
Unshackled program.

## Build and play

```sh
make play
```

This builds the interpreter (`tools/mu`), compiles and assembles the game
(`game/battleship.mu`), and starts a match. Fire by typing a column letter and
row number, e.g. `C5`; press `Q` to quit.

Assembling needs **LMFAO** on your path (or `make LMFAO=/path/to/lmfao`). The
assembled program is large (~180&nbsp;MB) because every value is spelled out in
Malbolge's self-modifying encoding; it is a build artifact and is not checked
in. On the reference `mu` interpreter the fleet load takes a few seconds and
each move is near-instant; on an optimising interpreter it is immediate.

## Layout

```
compiler/   the little-language -> HeLL compiler
  backend.py  control-flow graph and flag machine -> HeLL
  getc.py     width-independent character input
  lang.py     bits, if/while, counters, indexed board access
  battleship.py  the game itself
launcher.py  places random fleets, streams them in, bridges your keyboard
tools/mu.c   a Malbolge Unshackled interpreter (for standalone play)
Makefile
```

## Credits

Built by East Agile as part of our Malbolge toolchain. MIT licensed.

HeLL and the LMFAO assembler are by Matthias Lutter. `tools/mu` is a vendored copy of the shared interpreter for standalone play; once the
Rust interpreter lands at the repo root (`interpreter/`), the Makefile's `MU`
variable should point at it and `tools/mu.c` can be dropped.
