<div align="center">

# Malbolge

**Serious engineering for the least usable programming language ever designed.**

[![CI](https://github.com/EastAgile/Malbolge/actions/workflows/ci.yml/badge.svg)](https://github.com/EastAgile/Malbolge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-0f6e63.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-stable-0f6e63.svg)](interpreter/)

[Interpreter](interpreter/) · [Conformance suite](conformance/) · [Playground](playground/) · [Roadmap](#roadmap) · [Learn more](#learn-more)

</div>

---

Malbolge was designed in 1998 to be as hard to program in as possible. It runs
on a base-3 machine with an operation that matches no arithmetic you know.
Every instruction encrypts itself after it runs. The first working program
took two years to find, and it was found by a search algorithm, not written by
a person.

This repository is East Agile's toolkit for it. We wrote a fast, spec-precise
interpreter and a conformance suite that checks any interpreter against the
1998 reference. Everything runs natively and in the browser.

## Highlights

| | |
|---|---|
| **1.75x faster than the previous record** | `fastbolge` runs [MalbolgeLisp](https://github.com/iczelia/malbolge-lisp), a 371 MB Lisp interpreter written in Malbolge, about 1.75x faster than `fast20.c`, the fastest interpreter we could find. Output is byte-identical. |
| **A conformance suite for the whole ecosystem** | 42 cases pin down Malbolge's semantics, including the dark corners where the reference implementation itself is undefined. We ran it against five other open-source interpreters, and three of them fail. |
| **Runs in the browser** | The same Rust engine compiles to a 209 KB WebAssembly module. The [playground](playground/) is a single HTML file. |
| **No dependencies** | It uses only the Rust standard library. The core does no allocation in its hot loop. |

## Quick start

```sh
git clone https://github.com/EastAgile/Malbolge && cd Malbolge/interpreter
RUSTFLAGS="-C target-cpu=native" cargo build --release
./target/release/fastbolge ../conformance/cases/prog-samples-helloworld-eu-0.mb
```

Run the conformance suite against fastbolge, or against any interpreter you
like:

```sh
python3 ../conformance/run.py -- ./target/release/fastbolge -m {mode}
python3 ../conformance/run.py --mode classic -- /path/to/your-malbolge
```

Open the playground in a browser:

```sh
cargo build --release --target wasm32-unknown-unknown --lib
cp target/wasm32-unknown-unknown/release/fastbolge.wasm web/
python3 ../playground/build.py && open ../playground/index.html
```

## Benchmark

MalbolgeLisp v1.2 under both interpreters. These are wall-clock seconds,
median of 3 runs, on a 4-core Intel Xeon at 2.1 GHz. Both were compiled for
the native CPU.

| Workload | Malbolge steps | `fast20.c` | `fastbolge` | Speedup |
|---|---:|---:|---:|---:|
| Start up and evaluate `(+ 1 2)` | 2.4 billion | 9.25 s | 4.99 s | **1.85x** |
| Iterative Fibonacci, `(fib4 6)` | 18.9 billion | 55.30 s | 31.79 s | **1.74x** |
| Recursive Fibonacci, `(fib1 6)` | 35.5 billion | 98.64 s | 55.51 s | **1.78x** |

Here is how it gets there. Each memory cell carries its own decoded
instruction and encryption state, so a step needs no division and no table
chase. Encryption is a single lookup. Memory is one lazily filled `mmap`
region on huge pages. The 371 MB program loads in parallel in about 0.3 s,
where `fast20.c` takes 5 to 8 s. The [interpreter README](interpreter/README.md#how-it-is-fast)
has the details and the trade-offs.

## Conformance

The expected results come from Ben Olmstead's original `malbolge.c` and from
`fast20.c`. They do not come from our own interpreter.

| Interpreter | Language | Pass | Fail |
|---|---|---:|---:|
| **fastbolge** (native and WebAssembly) | Rust | **37** | **0** |
| reference `malbolge.c` (classic cases) | C | 27 | 0 |
| `fast20.c` (fast20 cases) | C | 10 | 0 |
| [return/malbolge](https://github.com/return/malbolge) | Rust | 24 | 3 |
| [kmyk/malbolge-interpreter](https://github.com/kmyk/malbolge-interpreter) | Python | 13 | 14 |
| [thimc/malbolge](https://github.com/thimc/malbolge) | Go | 3 | 24 |

Five more cases cover behaviour the reference leaves undefined. They are
reported for each interpreter but not scored. See [conformance/](conformance/).

## Repository layout

```
interpreter/    fastbolge: the Rust interpreter, its WebAssembly build and benchmarks
conformance/    language-neutral test cases, generator and runner, plus results
playground/     a single-page browser playground built on the WebAssembly module
```

## Roadmap

The Malbolge world has a few interpreters and generators, and almost nothing
in between. Here is what we plan to build next:

- **A compiler to classic Malbolge.** A small structured language that
  compiles to programs Olmstead's 1998 interpreter can run.
- **A standard library and showcase programs.** These include tested routines
  for arithmetic, number printing and strings, and real tools built on them.
- **Better tooling.** That means a step debugger with a trit-level memory view
  and editor support.

## Learn more

- [malbolge.org](https://malbolge.org/) covers the language, its history and the people still pushing it forward.
- The [Esolang wiki](https://esolangs.org/wiki/Main_Page) is the community wiki for esoteric programming languages. See its [Malbolge](https://esolangs.org/wiki/Malbolge) and [Malbolge Unshackled](https://esolangs.org/wiki/Malbolge_Unshackled) pages.

## Credits

Malbolge was created by Ben Olmstead in 1998. `fast20.c` and MalbolgeLisp are
by Kamila Szewczyk. The sample programs in `conformance/cases/prog-samples-*`
are from [zb3/malbolge-tools](https://github.com/zb3/malbolge-tools) (MIT).

## License

[MIT](LICENSE) © East Agile.

---

<div align="center">

Built by [East Agile](https://www.eastagile.com). We like hard problems.

</div>
