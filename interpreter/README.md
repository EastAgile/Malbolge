# fastbolge

A fast Malbolge interpreter in Rust, with a WebAssembly build for browsers.
It is part of [EastAgile/Malbolge](../README.md); the conformance suite lives
in [`../conformance`](../conformance/).

- **Two dialects.** `classic` is Malbolge as `malbolge.c` runs it. `fast20` is
  the 19-trit Malbolge Unshackled variant that MalbolgeLisp ships as `fast20.c`.
- **Fast.** On MalbolgeLisp it runs 1.74 to 1.85x faster than `fast20.c`,
  the fastest interpreter we know of, and loads the 371 MB program over 10x
  faster.
  See [Benchmark](#benchmark).
- **Runs in the browser.** The same engine compiles to a 209 KB `.wasm` with
  no JavaScript glue beyond `web/fastbolge.mjs`.
- **Says when a program leaves the spec.** Where the reference hangs, reads
  out of bounds, or does something else undefined, fastbolge stops with exit
  code 3 and a message.
- **No dependencies.** It uses only the Rust standard library.

## Usage

```sh
RUSTFLAGS="-C target-cpu=native" cargo build --release
./target/release/fastbolge hello.mb
./target/release/fastbolge -m fast20 lisp.mb < program.lisp
```

```
fastbolge [-m classic|fast20] [--strict] [--max-steps N] [--stats] program.mb
```

| Exit code | Meaning |
|---|---|
| 0 | the program halted |
| 1 | usage error |
| 2 | the program could not be loaded |
| 3 | undefined behaviour (see the message on stderr) |
| 4 | `--max-steps` reached |

`--stats` prints load time, step count and speed to stderr. `--strict`
(classic only) rejects source bytes that are not printable or whitespace; by
default they are accepted, as the reference does, and only fail if executed.

Output is buffered, and is flushed after each character when stdout is a
terminal. Set `FASTBOLGE_NO_THP=1` to turn off transparent huge pages for
fast20 memory.

### Browser and Node

```sh
cargo build --release --target wasm32-unknown-unknown --lib
cp target/wasm32-unknown-unknown/release/fastbolge.wasm web/
node web/cli.mjs -m classic hello.mb < /dev/null
```

`web/fastbolge.mjs` wraps the module:

```js
import { Fastbolge, HALTED, PAUSED } from "./fastbolge.mjs";
const fb = await Fastbolge.instantiate(await (await fetch("fastbolge.wasm")).arrayBuffer());
fb.load("classic", programBytes);   // returns an error string, or null
fb.setInput(new TextEncoder().encode("input"));
let status, limit = 0;
do { status = fb.run(limit += 5e6); show(fb.takeOutput()); } while (status === PAUSED);
```

`run` takes a cumulative step limit, so a UI can run in slices and stay
responsive. The fast20 dialect uses lazily allocated 2 MiB chunks in WASM, so
MalbolgeLisp needs about 3 GB of WebAssembly memory and will not fit in a
32-bit WASM build; small fast20 programs run fine.

[`../playground`](../playground/) builds a single HTML page that embeds the
`.wasm` and runs it in a Web Worker.

## Dialects

| | classic | fast20 |
|---|---|---|
| word size | 10 trits | 19 trits |
| memory | 59,049 cells | 3^19 = 1,162,261,467 cells |
| loading | skips whitespace; rejects instructions that are not valid at their position; at least 2 instructions | raw bytes, no whitespace skipping, no validation |
| unused memory | `crz` of the two previous cells | `crz` sequence up to the next 4096-cell boundary, then a repeating 6-value pattern |
| `rot` | whole word | low 18 trits; the top trit is kept |
| opcode decoding | `(c + [c]) mod 94` | the same, plus a fixed offset in the second and third thirds of memory |
| end of input | reads 59048 | reads 3^19 - 1 |
| output | `a mod 256` | `a mod 256` |

fast20 is a fixed-width cousin of Malbolge Unshackled. Full Unshackled, with
words that grow as needed, is not implemented.

## Testing

```sh
cargo test
python3 ../conformance/run.py -- ./target/release/fastbolge -m {mode}
python3 ../conformance/run.py -- node web/cli.mjs -m {mode}
```

`cargo test` runs unit tests for the crazy-op tables, the encryption table,
rotation and agreement between the two memory backends, plus every defined
conformance case through the library. fastbolge passes all 37 defined cases
natively and as WebAssembly; see [`../conformance`](../conformance/) for the
cases and how other interpreters do.

## Benchmark

`bench/bench.sh` runs MalbolgeLisp v1.2 under both interpreters and checks the
outputs are byte-identical:

```sh
bench/bench.sh ./target/release/fastbolge /path/to/fast20 /path/to/malbolge-lisp 3
```

Wall-clock seconds, median of 3, on a 4-core Intel Xeon at 2.1 GHz (Rust 1.97, clang 18). Both interpreters were
built for the native CPU (`fast20.c` with `clang -O3 -march=native`).

| Workload | Malbolge steps | `fast20.c` | `fastbolge` | Speedup |
|---|---:|---:|---:|---:|
| startup, `(+ 1 2)` | 2.4 billion | 9.25 s | 4.99 s | 1.85x |
| `(fib4 6)` | 18.9 billion | 55.30 s | 31.79 s | 1.74x |
| `(fib1 6)` | 35.5 billion | 98.64 s | 55.51 s | 1.78x |

Raw runs are in [`bench/results.tsv`](bench/results.tsv).

The startup row is loading the 371 MB `lisp.mb` and evaluating `(+ 1 2)`,
which is mostly MalbolgeLisp initialising itself. `fib4` evaluates an
iterative Fibonacci; `fib1` is the recursive one. MalbolgeLisp is slow
enough that computing the sixth Fibonacci number takes a minute.

The price is memory: fastbolge stores each cell in 8 bytes, so MalbolgeLisp
needs about 3 GB resident against 1.5 GB for `fast20.c`.

## How it is fast

Profiling MalbolgeLisp shows about 60% of steps are jumps and a third are
no-ops, with `movd`, `rot` and `crz` together a few percent.

1. **Cells describe themselves.** Each `u64` cell holds its value, its
   encryption state (`value * 94 + opcode`), and its instruction kind. Decoding
   is a shift, and encrypting after a step is one lookup in a 13,254-entry
   table. There is no `% 94` and no XLAT lookup in the loop.
2. **One check for two rare cases.** Kind 0 means either "this value is above
   140 and cannot run" or "this cell has not been initialised yet" (an all-zero
   cell). The loop tests one byte and leaves both cases to a slow path.
3. **Lazy memory.** The 3^19 cells are one `mmap` reservation with
   `MADV_HUGEPAGE`. Untouched memory is zero and is filled with the
   initialisation pattern 2^18 cells at a time when first read.
4. **A tight loop.** Jumps, no-ops, `movd`, `rot` and `crz` run in the fast
   loop. Only I/O, halt and uninitialised cells leave it. The step limit is
   checked only on jumps, and there is a separate loop with no limit check at
   all for the common case.
5. **Parallel, table-driven load.** Converting the 371 MB source to cells uses
   a 94 x 256 table and all cores.

Crazy-op on 19-trit words uses a 243 x 243 table over 5-trit chunks.

## Layout

```
src/lib.rs        shared tables, crazy op, I/O traits
src/classic.rs    classic dialect
src/fast20.rs     fast20 dialect
src/mem.rs        memory backends (mmap and paged)
src/main.rs       command line
src/wasm.rs       WebAssembly exports
web/              fastbolge.wasm, JS wrapper, Node CLI
tests/            conformance cases run through the library
bench/            benchmark script, workloads and raw results
```

## Caveats

- fast20 checks `--max-steps` only on jumps, so it can overshoot by a run of
  no-ops. Classic stops exactly.
- fast20 is fixed-width. Programs that need true Malbolge Unshackled
  (growing word size) will not run.
- Large fast20 programs need a 64-bit Unix host for the fast backend; other
  platforms use the slower paged backend.

## Credits

Malbolge is by Ben Olmstead (1998). `fast20.c` and MalbolgeLisp are by
Kamila Szewczyk.
