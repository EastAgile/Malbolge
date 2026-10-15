# grep.mal — a streaming `grep` that runs in Malbolge

This is a working `grep` whose entire matching engine runs as a
[Malbolge](https://esolangs.org/wiki/Malbolge) program — the language designed
to be as hard to program in as possible. It reads input a line at a time with
bounded memory, so it searches streams of any length, and it has a modern,
`grep`-style command line.

```
$ echo -e "alpha\nBETA\ngamma" | ./grep.mal -i -n 'a.*a'
1:alpha
3:gamma
```

Behind that familiar interface, every comparison, every anchor, every `*` is
evaluated by Malbolge instructions.

## Why this is interesting

Malbolge has no variables, no files, and no command-line arguments; its only
channels are standard in and standard out, and every instruction encrypts
itself after it runs. Published Malbolge programs are almost all tiny, fixed
outputs (hello world, 99 bottles). A real line-oriented tool with flags and a
regex subset is a different kind of artifact.

Two design choices make it honest:

- **The matching runs in Malbolge, not in the launcher.** `grep.mal` is a thin
  shell wrapper. It parses the command line and then hands the Malbolge program
  a two-line header (the flags, then the pattern) followed by the input. It
  shuffles bytes; it does not match.
- **It streams.** The program holds one line at a time in a fixed buffer, so
  memory use is bounded and independent of input size. You can pipe a log of any
  length through it.

## Usage

```
grep.mal [OPTIONS] PATTERN [FILE ...]

  -i, --ignore-case    case-insensitive matching
  -v, --invert-match   select the lines that do NOT match
  -n, --line-number    prefix each output line with its 1-based line number
  -c, --count          print only the number of matching lines
  -e PATTERN           supply the pattern as an option
      --interp PATH    choose the Malbolge interpreter (default: auto-detect)
  -h, --help           show help
```

With no `FILE` (or `-`), it reads standard input. Multiple files are searched as
one concatenated stream; filename prefixes are not emitted.

### Pattern syntax

A documented subset of POSIX basic regular expressions:

| Syntax | Meaning |
| --- | --- |
| `c` | the literal character `c` |
| `.` | any single character |
| `X*` | zero or more of the preceding atom `X` |
| `^` `$` | start / end of line anchors |
| `[abc]` `[a-z]` | character class / range |
| `[^...]` | negated class |
| `\c` | match `c` literally |

Not supported (kept out so the behaviour is exactly specifiable): `+`, `?`,
`\|` alternation, `\(...\)` groups, back-references, and POSIX `[[:class:]]`
names. Lines longer than the buffer (4096 bytes) are matched and printed on
their first 4096 bytes.

## Building and running

```
make          # builds the interpreter and assembles the Malbolge program
./grep.mal -n foo yourfile.txt
```

`make` produces two things:

- `build/mu` — a small, spec-faithful **Malbolge Unshackled** interpreter
  (`tools/mu.c`). The launcher auto-detects it.
- `build/grep.mu` — the grep itself, assembled from the committed HeLL
  (`build/grep.hell.xz`) by [LMFAO](https://github.com/esoteric-programmer/LMFAO),
  the Malbolge Unshackled assembler. Install LMFAO and put it on your `PATH`
  (or `make LMFAO=/path/to/lmfao`).

To regenerate the program from C (only needed to change what it does) you also
need the [ELVM](https://github.com/shinh/elvm) toolchain:

```
make grep ELVM=/path/to/elvm
```

### Testing

```
make test                 # native reference vs GNU grep — fast, 21 cases
MALBOLGE=1 tests/run.sh    # drives the real Malbolge program — correct but slow
```

The native reference (`src/grep.c` compiled with `cc`) is the *same source* that
is compiled to Malbolge, so the fast test exercises the real matching logic. The
`MALBOLGE=1` path confirms the compiled `build/grep.mu` agrees with GNU grep on a
small set of inputs.

## How it is built

```
src/grep.c  ──8cc──▶  EIR  ──elc -hell──▶  HeLL  ──LMFAO──▶  grep.mu (Malbolge)
   │                                                            │
   └── the launcher feeds: "flags\npattern\n" + input ──────────┘──▶ matches on stdout
```

`src/grep.c` is an ordinary C program: a small backtracking regex matcher over a
line buffer, reading its configuration from the first two lines of stdin. It is
compiled to Malbolge with the [ELVM](https://github.com/shinh/elvm) C compiler
backend, whose HeLL output is assembled to Malbolge Unshackled by
[LMFAO](https://github.com/esoteric-programmer/LMFAO).

### Classic Malbolge vs. Unshackled

The target is **Malbolge Unshackled**, the Turing-complete variant, not
Ben Olmstead's original 1998 Malbolge. The original caps memory at 59,049 cells
— LMAO's bundled "add two numbers" example already uses 55,725 of them — so a
general line-oriented tool does not fit. Unshackled lifts that ceiling, at the
cost of size and speed (see below).

## Performance, honestly

This is a Malbolge program, so it is slow. The compiled `grep.mu` is ~245 MB and
each input character costs on the order of a billion Malbolge instructions,
because the C runtime is emulated on top of Malbolge's self-modifying machine.
On the bundled reference interpreter (`tools/mu.c`), expect well under a kilobyte
per minute. A fast interpreter (for example a JIT or the project's optimized
Rust interpreter) is what makes it practical to watch run. The point is that the
work genuinely happens in Malbolge — not that it happens quickly.

## Files

```
grep.mal            the CLI launcher (the program you run)
src/grep.c          the matcher, in C — compiled to Malbolge
tools/mu.c          a Malbolge Unshackled interpreter (reference)
build/grep.hell.xz  the compiled HeLL assembly (committed; LMFAO assembles it)
tests/run.sh        differential test against GNU grep
Makefile            build / assemble / test
```

## Credits and licensing

The grep, launcher, interpreter, and tests here are original. The build pipeline
uses two external tools, which are not vendored here and keep their own licenses:
the [ELVM](https://github.com/shinh/elvm) C-to-HeLL compiler and
[LMFAO](https://github.com/esoteric-programmer/LMFAO), the Malbolge Unshackled
assembler (GPLv3). Malbolge Unshackled is Ørjan Johansen's variant of
Ben Olmstead's Malbolge.
