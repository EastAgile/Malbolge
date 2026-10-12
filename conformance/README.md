# Malbolge conformance suite

42 test cases that pin down how a Malbolge interpreter must behave, with a
runner that works with any interpreter. Expected results come from Ben
Olmstead's 1998 reference `malbolge.c` (classic) and from `fast20.c`, the
interpreter MalbolgeLisp ships with (fast20). They do not come from fastbolge.

## Running it

The runner adds the program path to the end of the command and feeds the
case's input on stdin. `{mode}` is replaced with `classic` or `fast20`.

```sh
python3 run.py -- ../interpreter/target/release/fastbolge -m {mode}
python3 run.py --mode classic --json my-results.json -- /path/to/malbolge
```

It needs Python 3 and nothing else. The exit status is non-zero when any case fails.

| Verdict | Meaning |
|---|---|
| `PASS` | The output matches the reference. Halting cases compare the whole output; endless programs compare the first N bytes. |
| `FAIL` | The output is wrong, the program halted or hung when it should not, or an invalid program was accepted. |
| `INFO` | The reference's behaviour is undefined here. The runner reports what happened but does not score it. |

## The cases

| Group | Cases | What they cover |
|---|---:|---|
| Real programs (`prog-samples-*`) | 8 | Hello world, cat, a crackme, an encryptor, a separator and an endless printer, from [zb3/malbolge-tools](https://github.com/zb3/malbolge-tools) (MIT) |
| Instruction semantics | 17 | Each instruction alone: rotate, crazy op, `movd` through initialised memory, jumps, long no-op runs, the encryption cycle, output above 255, the end-of-input value, input bytes above 127, and whitespace on load |
| Load errors | 2 | An invalid instruction, and a program longer than memory |
| Undefined behaviour | 5 | Empty and one-instruction programs, overwriting the running instruction, executing a non-printable value, and running off the end of memory |
| fast20 dialect | 10 | 19-trit rotate and crazy op, the explicit fill and repeating pattern, the end-of-input value, and raw loading with no whitespace skipping |

`cases.json` lists every case with a note explaining what it checks. Most
instruction tests are written in normalized Malbolge (`ji*p</vo`) and encoded
by `gen.py`, so they are easy to read and change.

## Regenerating

```sh
python3 gen.py /path/to/reference-malbolge /path/to/fast20 /path/to/malbolge-tools/samples
```

Build the reference from Olmstead's `malbolge.c`. Build `fast20` from
MalbolgeLisp's `fast20.c`.

## Results

`results/` holds the full output for each interpreter we tested:

| Interpreter | Pass | Fail | Notes |
|---|---:|---:|---|
| fastbolge (native and WebAssembly) | 37 | 0 | |
| reference `malbolge.c` | 27 | 0 | classic cases only |
| `fast20.c` | 10 | 0 | fast20 cases only |
| [return/malbolge](https://github.com/return/malbolge) (Rust) | 24 | 3 | reads end of input as 0; diverges on `encrypted.mb` |
| [kmyk/malbolge-interpreter](https://github.com/kmyk/malbolge-interpreter) (Python) | 13 | 14 | wrong crazy op and rotate |
| [thimc/malbolge](https://github.com/thimc/malbolge) (Go) | 3 | 24 | encodes output bytes as UTF-8 and adds a trailing newline |

Want your interpreter in this table? Open a pull request with its results file.
