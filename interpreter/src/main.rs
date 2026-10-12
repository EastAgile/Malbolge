use std::io::{IsTerminal, Read, Write};
use std::process::ExitCode;
use std::time::Instant;

use fastbolge::{classic, fast20, Exit, Io, Options};

/// Buffered stdio. Output is flushed per character on a terminal, otherwise
/// in blocks, and always before reading input.
struct StdIo {
    out: std::io::BufWriter<std::io::Stdout>,
    inp: std::io::StdinLock<'static>,
    tty: bool,
}

impl Io for StdIo {
    #[inline]
    fn put(&mut self, a: u32) {
        let _ = self.out.write_all(&[a as u8]);
        if self.tty {
            let _ = self.out.flush();
        }
    }
    fn get(&mut self) -> Option<u8> {
        let _ = self.out.flush();
        let mut b = [0u8];
        match self.inp.read(&mut b) {
            Ok(1) => Some(b[0]),
            _ => None,
        }
    }
}

const USAGE: &str = "usage: fastbolge [options] program.mb

Options:
  -m, --mode classic|fast20  dialect (default: classic)
        classic  Ben Olmstead's 1998 Malbolge, as in the reference interpreter
        fast20   fixed-width Malbolge Unshackled, as in fast20.c
                 (MalbolgeLisp, blc-mb)
  --strict                   classic: reject non-printable bytes in the source
  --max-steps N              stop after about N steps (exit code 4)
  --stats                    print steps and speed to stderr

Exit codes: 0 halted, 1 usage or I/O error, 2 load error,
            3 undefined behaviour in the reference, 4 step limit reached";

fn main() -> ExitCode {
    let mut mode = "classic".to_string();
    let mut path: Option<String> = None;
    let mut opts = Options::default();
    let mut stats = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "-m" | "--mode" => mode = args.next().unwrap_or_default(),
            "--strict" => opts.strict = true,
            "--stats" => stats = true,
            "--max-steps" => match args.next().and_then(|n| n.parse().ok()) {
                Some(n) => opts.max_steps = n,
                None => {
                    eprintln!("{USAGE}");
                    return ExitCode::from(1);
                }
            },
            "-h" | "--help" => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            _ if path.is_none() => path = Some(a),
            _ => {
                eprintln!("{USAGE}");
                return ExitCode::from(1);
            }
        }
    }
    let Some(path) = path else {
        eprintln!("{USAGE}");
        return ExitCode::from(1);
    };
    let src = if path == "-" {
        let mut v = Vec::new();
        std::io::stdin().read_to_end(&mut v).map(|_| v)
    } else {
        std::fs::read(&path)
    };
    let src = match src {
        Ok(s) => s,
        Err(e) => {
            eprintln!("fastbolge: cannot read {path}: {e}");
            return ExitCode::from(1);
        }
    };
    let stdout = std::io::stdout();
    let tty = stdout.is_terminal();
    let mut io = StdIo {
        out: std::io::BufWriter::with_capacity(1 << 16, stdout),
        inp: std::io::stdin().lock(),
        tty,
    };

    let t0 = Instant::now();
    let outcome = match mode.as_str() {
        "classic" => classic::run(&src, &mut io, &opts),
        "fast20" => match fast20::load::<fastbolge::mem::NativeSpace>(&src) {
            Ok(mut m) => {
                let t1 = Instant::now();
                let o = m.run(&mut io, &opts);
                if stats {
                    eprintln!("fastbolge: load {:.2}s", (t1 - t0).as_secs_f64());
                }
                o
            }
            Err(e) => fastbolge::Outcome { exit: e, steps: 0 },
        },
        _ => {
            eprintln!("{USAGE}");
            return ExitCode::from(1);
        }
    };
    let _ = io.out.flush();
    let dt = t0.elapsed().as_secs_f64();
    if stats {
        eprintln!(
            "fastbolge: {} steps in {:.2}s ({:.0} M steps/s)",
            outcome.steps,
            dt,
            outcome.steps as f64 / dt / 1e6
        );
    }
    match outcome.exit {
        Exit::Halted => ExitCode::SUCCESS,
        Exit::OutOfSteps => {
            eprintln!(
                "fastbolge: step limit reached after {} steps",
                outcome.steps
            );
            ExitCode::from(4)
        }
        Exit::LoadError(m) => {
            eprintln!("fastbolge: {m}");
            ExitCode::from(2)
        }
        Exit::Error(m) => {
            eprintln!("fastbolge: {m}");
            ExitCode::from(3)
        }
    }
}
