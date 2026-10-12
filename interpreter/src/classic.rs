//! Classic Malbolge, as defined by Ben Olmstead's reference interpreter.

use crate::{crz10, op, Exit, Io, Options, Outcome, XLAT};

/// Number of memory cells (3^10).
pub const END: u32 = 59049;

/// A loaded classic Malbolge program and its machine state.
pub struct Program {
    mem: Box<[u32]>,
    a: u32,
    c: u32,
    d: u32,
    steps: u64,
    done: Option<Exit>,
}

fn is_space(x: u8) -> bool {
    matches!(x, b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r')
}

/// Load a program the way the reference interpreter does: whitespace is
/// skipped, every printable character must decode to an instruction, and the
/// rest of memory is filled with `crz([i-1], [i-2])`.
pub fn load(src: &[u8], opts: &Options) -> Result<Program, Exit> {
    let mut mem = vec![0u32; END as usize].into_boxed_slice();
    let mut i: u32 = 0;
    for &x in src {
        if is_space(x) {
            continue;
        }
        if (33..=126).contains(&x) {
            let o = ((x as u32 + i) % 94) as u8;
            if !op::is_instruction(o) {
                return Err(Exit::LoadError(format!(
                    "invalid character '{}' at program position {}",
                    x as char, i
                )));
            }
        } else if opts.strict {
            return Err(Exit::LoadError(format!(
                "byte 0x{:02x} at program position {} is not a printable instruction",
                x, i
            )));
        }
        if i == END {
            return Err(Exit::LoadError("input file too long".into()));
        }
        mem[i as usize] = x as u32;
        i += 1;
    }
    if i < 2 {
        return Err(Exit::LoadError(format!(
            "program has {} instruction(s); the reference initialisation reads before the start of memory",
            i
        )));
    }
    for k in i as usize..END as usize {
        mem[k] = crz10(mem[k - 1], mem[k - 2]);
    }
    Ok(Program {
        mem,
        a: 0,
        c: 0,
        d: 0,
        steps: 0,
        done: None,
    })
}

impl Program {
    /// Run until the program halts, fails, or `opts.max_steps` total steps
    /// have been executed. After [`Exit::OutOfSteps`] the run can be resumed
    /// by calling `run` again with a higher limit.
    pub fn run(&mut self, io: &mut impl Io, opts: &Options) -> Outcome {
        if let Some(e) = &self.done {
            return Outcome {
                exit: e.clone(),
                steps: self.steps,
            };
        }
        let exit = self.exec(io, opts.max_steps);
        if exit != Exit::OutOfSteps {
            self.done = Some(exit.clone());
        }
        Outcome {
            exit,
            steps: self.steps,
        }
    }

    fn exec(&mut self, io: &mut impl Io, limit: u64) -> Exit {
        let m = &mut self.mem[..];
        let (mut a, mut c, mut d, mut steps) = (self.a, self.c, self.d, self.steps);
        if steps >= limit {
            return Exit::OutOfSteps;
        }
        let exit = loop {
            let v = m[c as usize];
            if !(33..=126).contains(&v) {
                break Exit::Error(format!(
                    "cell [{}] = {} is not an instruction (the reference interpreter hangs here)",
                    c, v
                ));
            }
            steps += 1;
            match ((v + c) % 94) as u8 {
                op::MOVD => d = m[d as usize],
                op::JMP => c = m[d as usize],
                op::ROT => {
                    let x = m[d as usize];
                    a = x / 3 + x % 3 * 19683;
                    m[d as usize] = a;
                }
                op::CRZ => {
                    a = crz10(a, m[d as usize]);
                    m[d as usize] = a;
                }
                op::OUT => io.put(a),
                op::IN => a = io.get().map_or(END - 1, |b| b as u32),
                op::HALT => break Exit::Halted,
                _ => {}
            }
            let v = m[c as usize];
            if !(33..=126).contains(&v) {
                break Exit::Error(format!(
                    "cell [{}] = {} cannot be encrypted (the reference interpreter indexes out of bounds here)",
                    c, v
                ));
            }
            m[c as usize] = XLAT[v as usize] as u32;
            c = if c == END - 1 { 0 } else { c + 1 };
            d = if d == END - 1 { 0 } else { d + 1 };
            if steps >= limit {
                break Exit::OutOfSteps;
            }
        };
        self.a = a;
        self.c = c;
        self.d = d;
        self.steps = steps;
        exit
    }

    /// Read a memory cell (for tests and tools).
    pub fn cell(&self, addr: u32) -> u32 {
        self.mem[addr as usize]
    }
}

/// Load and run in one call.
pub fn run(src: &[u8], io: &mut impl Io, opts: &Options) -> Outcome {
    match load(src, opts) {
        Ok(mut p) => p.run(io, opts),
        Err(e) => Outcome { exit: e, steps: 0 },
    }
}
