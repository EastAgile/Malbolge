# Battleship, in Malbolge

A complete, playable game of Battleship whose entire rule set, random fleet
placement, computer opponent, and board rendering run inside [Malbolge](https://en.wikipedia.org/wiki/Malbolge)
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
is also no random number generator, no clock, no command-line arguments, and no
file access. Most published Malbolge programs are a few lines long; a few large
ones (a Lisp, a lambda-calculus evaluator) exist but are tens of megabytes and
run for minutes.

This project builds a real, interactive game on that substrate. At play time
nothing runs but the Malbolge interpreter.

## How it works

Everything that *is* the game runs in Malbolge Unshackled:

- **State** is held in self-restoring two-state code cells ("flags"). Bytes,
  an 8&times;8 board for each side, hit counters, and the AI's memory are all
  built from flags.
- **Input** is decoded width-independently: each keypress is turned into an
  8-bit code by a 243-way jump table, so it works whatever rotation width the
  interpreter happens to choose.
- **Randomness** comes from Malbolge's own self-encryption (see below).
- **Fleet placement** for both sides happens in the program: it draws a start
  cell and an orientation, rejects any ship that would leave the board or touch
  another, and starts the board over if a ship fails 256 draws in a row. Your
  fleet is placed when you give your name. The enemy fleet is placed only after
  your first shot (see below).
- **The computer opponent** plays *hunt and target*: it fires at random unshot
  cells until it hits a ship, then tries that hit's neighbours, then resumes
  hunting. This logic is compiled to Malbolge, not done on the host.
- **Rendering** is ANSI colour text, drawn by Malbolge `OUT` instructions.

## Where the randomness comes from

Every time a Malbolge instruction runs, the interpreter overwrites it with its
image under a fixed permutation, `xlat2`. The game's random number generator is
built from that self-encryption and nothing else.

The generator is 32 code cells. Each one sits on a two-point cycle of `xlat2`,
so which point it is at is one bit, and making it encrypt itself once flips that
bit. To advance the generator, the program makes cells encrypt themselves, each
one only if a test of some other cell says so. The pattern of those
encryptions is Marsaglia's xorshift32 (shifts 13, 17, 5), which passes through
every non-zero 32-bit state before it repeats.

Encryption can scramble a value, but it cannot make one unpredictable. The
interpreter is deterministic, so a program that reads nothing makes the same
"random" choices on every run. The only thing that differs between runs is what the player
types, so that is the seed, and the game takes it in two parts:

1. **Your admiral's name.** Each key is folded into the generator, which then
   places your fleet so you can see it before you fire.
2. **Your first shot.** The enemy fleet does not exist yet when you fire it.
   Each key of the shot is folded into the generator, which then places the
   enemy fleet and scores your shot against it.

After that the generator stops reading the keyboard. Nothing typed during play
can move a ship or influence where the computer fires. The enemy fleet is the
same only for the same name and the same first shot, typed the same way: `C5`
and `c5` are different keys, so they give different fleets.

Why not use the time the player takes to type? A Malbolge program cannot see
time. Its only contact with the outside world is reading and writing
characters, and a read simply waits: no instruction runs until the key
arrives, so the machine is in exactly the same state whether you answer in one
second or one minute. Timing could only get in if the interpreter put it
there.

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
(`game/battleship.mu`), and runs `tools/mu game/battleship.mu`. Type a name
to seed the sea, then fire by typing a column letter and row number, e.g.
`C5`; type `Q` to quit.

Assembling needs **LMFAO** on your path (or `make LMFAO=/path/to/lmfao`). The
assembled program is large (~190&nbsp;MB) because every value is spelled out in
Malbolge's self-modifying encoding; it is a build artifact and is not checked
in. Loading it into the reference `mu` interpreter takes about 40 seconds and
4 GB of memory. After that, fleet placement and each move are near-instant.

## Layout

```
compiler/   the little-language -> HeLL compiler
  backend.py  control-flow graph and flag machine -> HeLL
  getc.py     width-independent character input
  lang.py     bits, if/while, counters, indexed board access, the generator
  battleship.py  the game itself
tools/mu.c   a Malbolge Unshackled interpreter (for standalone play)
Makefile
```

## Credits

Built by East Agile as part of our Malbolge toolchain. MIT licensed.

HeLL and the LMFAO assembler are by Matthias Lutter. `tools/mu` is a vendored copy of the shared interpreter for standalone play; once the
Rust interpreter lands at the repo root (`interpreter/`), the Makefile's `MU`
variable should point at it and `tools/mu.c` can be dropped.
