//! The fixed-width Malbolge Unshackled dialect implemented by `fast20.c`.
//!
//! This is the dialect MalbolgeLisp and blc-mb are distributed for:
//!
//! * words are 19 trits; addresses run over 3^19 cells;
//! * the source is loaded byte for byte, with no validation or whitespace
//!   skipping;
//! * memory after the program holds `crz([i-1], [i-2])` up to the next
//!   multiple of 4096 cells, then repeats the following six values, indexed
//!   by `(address mod 3^18) mod 6`;
//! * the opcode of a cell is `(c + [c] + k) mod 94`, where `k` depends on
//!   which third of memory `c` lies in;
//! * `*` rotates the low 18 trits right and keeps the top trit;
//! * output truncates the accumulator to a byte; end of input reads 3^19 - 1.
//!
//! Cell values 0..=140 have a defined encryption (fast20's padded table);
//! executing or encrypting anything larger is undefined in fast20 and stops
//! fastbolge with an error.

use crate::mem::{Space, CHUNK, CHUNK_BITS};
use crate::{crz19, op, Exit, Io, Options, Outcome, XLAT, XLAT_N};

/// Number of memory cells (3^19).
pub const END: u32 = 1_162_261_467;
/// One third of memory (3^18).
pub const THIRD: u32 = END / 3;

/// Decode offsets for the three thirds of memory, as computed in fast20.c.
const OFFS: [u32; 3] = {
    let e = END as i64;
    let a1 = 94 - ((e - 1) / 6 - 29524) % 94;
    let a2 = 94 - ((e - 1) / 3 - 59048) % 94;
    [
        0,
        ((a1 - e / 3) % 94 + 94) as u32,
        ((a2 - 2 * (e / 3)) % 94 + 94) as u32,
    ]
};

// Cell layout:
//   bits  0..32  value
//   bits 32..48  encryption state `v * 94 + opcode` (values <= 140 only)
//   bits 56..64  instruction kind
// where opcode = (phase + value) mod 94. Encrypting a cell is a single table
// lookup on its state, and decoding is a shift.
//
// Kind 0 means the cell cannot be executed or encrypted: either it has not
// been initialised yet (the whole cell is 0; memory starts zeroed, and every
// initialised cell is non-zero) or its value is above 140.
const K_BAD: u64 = 0;
const K_NOP: u64 = 1;
const K_JMP: u64 = 2;
const K_MOVD: u64 = 3;
const K_ROT: u64 = 4;
const K_CRZ: u64 = 5;
const K_OUT: u64 = 6;
const K_IN: u64 = 7;
const K_HALT: u64 = 8;

const STATE_SHIFT: u32 = 32;
const KIND_SHIFT: u32 = 56;
const STATES: usize = XLAT_N as usize * 94;

const fn kind_of(op: u32) -> u64 {
    match op as u8 {
        op::JMP => K_JMP,
        op::MOVD => K_MOVD,
        op::ROT => K_ROT,
        op::CRZ => K_CRZ,
        op::OUT => K_OUT,
        op::IN => K_IN,
        op::HALT => K_HALT,
        _ => K_NOP,
    }
}

/// The cell for value `v` with opcode `o`.
const fn make(v: u32, o: u32) -> u64 {
    if v >= XLAT_N {
        v as u64 | K_BAD << KIND_SHIFT
    } else {
        v as u64 | ((v * 94 + o) as u64) << STATE_SHIFT | kind_of(o) << KIND_SHIFT
    }
}

/// The encrypted cell for each encryption state.
static NEXT: [u64; STATES] = {
    let mut t = [0u64; STATES];
    let mut v = 0;
    while v < XLAT_N as usize {
        let e = XLAT[v] as u32;
        let mut o = 0;
        while o < 94 {
            let o2 = ((o as i64 + e as i64 - v as i64).rem_euclid(94)) as u32;
            t[v * 94 + o] = make(e, o2);
            o += 1;
        }
        v += 1;
    }
    t
};

/// Position term of the opcode: `(x + k) mod 94`.
#[inline(always)]
fn phase(x: u32) -> u32 {
    let k = if x >= 2 * THIRD {
        OFFS[2]
    } else if x >= THIRD {
        OFFS[1]
    } else {
        0
    };
    (x % 94 + k) % 94
}

/// A cell holding value `v` at an address with phase `ph`.
#[inline(always)]
fn pack_ph(ph: u32, v: u32) -> u64 {
    make(v, (ph + v % 94) % 94)
}

#[inline(always)]
fn pack(x: u32, v: u32) -> u64 {
    pack_ph(phase(x), v)
}

#[inline(always)]
fn kind(cell: u64) -> u64 {
    cell >> KIND_SHIFT
}

/// Encrypt a cell. Its kind must not be BAD.
#[inline(always)]
fn encrypt(cell: u64) -> u64 {
    // SAFETY: valid kinds imply a state below STATES.
    unsafe { *NEXT.get_unchecked(((cell >> STATE_SHIFT) & 0xffff) as usize) }
}

#[inline(always)]
fn rot18(x: u32) -> u32 {
    let b = x % THIRD;
    (x - b) + b / 3 + (b % 3) * (THIRD / 3)
}

/// A loaded fast20 program and its machine state.
pub struct Machine<S: Space> {
    mem: S,
    pat: [u32; 6],
    a: u32,
    c: u32,
    d: u32,
    steps: u64,
    done: Option<Exit>,
}

/// Machine on the best memory backend for this platform.
pub type Native = Machine<crate::mem::NativeSpace>;

/// Machine with on-demand chunk allocation.
pub type Paged = Machine<crate::mem::Paged>;

/// Cells in the address space plus a guard chunk past the end, which stays
/// zero so running off the end lands in the slow path.
const SPACE: u32 = END + CHUNK;

/// Load a program.
pub fn load<S: Space>(src: &[u8]) -> Result<Machine<S>, Exit> {
    if src.len() > END as usize {
        return Err(Exit::LoadError("input file too long".into()));
    }
    if src.len() < 2 {
        return Err(Exit::LoadError(
            "program must be at least two cells long".into(),
        ));
    }
    let len = src.len() as u32;
    let sz_r = ((len - 1) & !4095) + 4096;
    let mut m = Machine {
        mem: S::new(SPACE),
        pat: [0; 6],
        a: 0,
        c: 0,
        d: 0,
        steps: 0,
        done: None,
    };

    // fast20 computes the crz sequence explicitly up to sz_r, then repeats
    // the next six values indexed by (address mod 3^18) mod 6.
    let eager_end = (sz_r + 6).div_ceil(CHUNK).saturating_mul(CHUNK).min(END);
    for ch in 0..eager_end.div_ceil(CHUNK) {
        m.mem.make_ready(ch);
    }
    let (mut n2, mut n1) = (0u32, 0u32);
    for x in len..sz_r + 6 {
        let (v1, v2) = if x == len {
            (src[len as usize - 1] as u32, src[len as usize - 2] as u32)
        } else if x == len + 1 {
            (n1, src[len as usize - 1] as u32)
        } else {
            (n1, n2)
        };
        let v = crz19(v1, v2);
        if x >= sz_r {
            m.pat[(x % 6) as usize] = v;
        }
        n2 = v1;
        n1 = v;
    }
    // Program bytes: in the first third the phase of address x is x mod 94,
    // so a cell is a lookup on (x mod 94, byte). Large programs are
    // converted on several threads when memory is contiguous.
    let prog_end = len.min(THIRD) as usize;
    let tab: Vec<u64> = (0..94u32)
        .flat_map(|ph| (0..256u32).map(move |v| pack_ph(ph, v)))
        .collect();
    let convert = |base: usize, out: &mut [u64]| {
        for (i, cell) in out.iter_mut().enumerate() {
            let x = base + i;
            *cell = tab[(x % 94) * 256 + src[x] as usize];
        }
    };
    if let Some(cells) = m.mem.contiguous(prog_end as u32) {
        let threads = std::thread::available_parallelism()
            .map_or(1, |n| n.get())
            .min(8);
        if threads > 1 && prog_end >= 1 << 22 {
            let per = prog_end.div_ceil(threads);
            std::thread::scope(|sc| {
                for (k, part) in cells.chunks_mut(per).enumerate() {
                    let convert = &convert;
                    sc.spawn(move || convert(k * per, part));
                }
            });
        } else {
            convert(0, cells);
        }
    } else {
        for x in 0..prog_end {
            unsafe { m.mem.set(x as u32, tab[(x % 94) * 256 + src[x] as usize]) };
        }
    }
    // The rest: program bytes beyond the first third (only for programs
    // over 3^18 bytes), the explicit crz sequence, then the pattern.
    unsafe {
        let mut n2 = src[len as usize - 2] as u32;
        let mut n1 = src[len as usize - 1] as u32;
        for x in prog_end as u32..eager_end {
            let v = if x < len {
                src[x as usize] as u32
            } else if x < sz_r {
                let v = crz19(n1, n2);
                n2 = n1;
                n1 = v;
                v
            } else {
                m.pat[((x % THIRD) % 6) as usize]
            };
            m.mem.set(x, pack(x, v));
        }
    }
    Ok(m)
}

impl<S: Space> Machine<S> {
    /// Initialise the chunk containing `x`. Fails if `x` is past the end.
    #[cold]
    #[inline(never)]
    fn fill(&mut self, x: u32) -> Result<(), Exit> {
        if x >= END {
            return Err(Exit::Error(
                "c or d ran past the end of memory (undefined in fast20)".into(),
            ));
        }
        let ch = x >> CHUNK_BITS;
        self.mem.make_ready(ch);
        let base = ch << CHUNK_BITS;
        let end = base.saturating_add(CHUNK).min(END);
        unsafe {
            for x in base..end {
                if self.mem.get(x) == 0 {
                    self.mem
                        .set(x, pack(x, self.pat[((x % THIRD) % 6) as usize]));
                }
            }
        }
        Ok(())
    }

    /// Read a cell, initialising its chunk first if needed.
    #[inline(always)]
    fn load_cell(&mut self, x: u32) -> Result<u64, Exit> {
        let v = unsafe { self.mem.get(x) };
        if v != 0 {
            return Ok(v);
        }
        self.fill(x)?;
        Ok(unsafe { self.mem.get(x) })
    }

    /// Instructions executed so far.
    pub fn steps(&self) -> u64 {
        self.steps
    }

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
        let mut r = Regs {
            a: self.a,
            c: self.c,
            d: self.d,
            steps: self.steps,
        };
        let exit = loop {
            if r.steps >= limit {
                break Exit::OutOfSteps;
            }
            // Fast path: everything except I/O, halting, uninitialised
            // memory and undefined behaviour. Returns with nothing executed
            // for the step it stopped at.
            r = unsafe {
                if limit == u64::MAX {
                    fast_loop::<S, false>(&mut self.mem, r, limit)
                } else {
                    fast_loop::<S, true>(&mut self.mem, r, limit)
                }
            };
            if r.steps >= limit {
                continue;
            }
            self.a = r.a;
            match self.slow_step(io, &mut r.c, &mut r.d) {
                Ok(true) => r.steps += 1,
                Ok(false) => {}
                Err(e) => {
                    if e == Exit::Halted {
                        r.steps += 1;
                    }
                    break e;
                }
            }
            r.a = self.a;
        };
        self.a = r.a;
        self.c = r.c;
        self.d = r.d;
        self.steps = r.steps;
        exit
    }

    /// Execute one step the fast loop declined. Ok(true) if a step ran,
    /// Ok(false) if memory was initialised and the step should be retried.
    #[inline(never)]
    fn slow_step(&mut self, io: &mut impl Io, c: &mut u32, d: &mut u32) -> Result<bool, Exit> {
        let cell = self.load_cell(*c)?;
        match kind(cell) {
            K_JMP => {
                // The fast loop stops at jumps whose pointer or target is
                // uninitialised or bad.
                let t = self.load_cell(*d)?;
                *c = t as u32;
                let t = self.load_cell(*c)?;
                if kind(t) == K_BAD {
                    return Err(self.bad(*c));
                }
                unsafe { self.mem.set(*c, encrypt(t)) };
                *c += 1;
                *d += 1;
                return Ok(true);
            }
            K_NOP => {}
            K_MOVD => *d = self.load_cell(*d)? as u32,
            K_ROT => {
                let x = self.load_cell(*d)? as u32;
                self.a = rot18(x);
                unsafe { self.mem.set(*d, pack(*d, self.a)) };
            }
            K_CRZ => {
                let x = self.load_cell(*d)? as u32;
                self.a = crz19(self.a, x);
                unsafe { self.mem.set(*d, pack(*d, self.a)) };
            }
            K_OUT => io.put(self.a),
            K_IN => self.a = io.get().map_or(END - 1, |b| b as u32),
            K_HALT => return Err(Exit::Halted),
            _ => return Err(self.bad(*c)),
        }
        // [c] may have been overwritten if d == c.
        let t = self.load_cell(*c)?;
        if kind(t) == K_BAD {
            return Err(self.bad(*c));
        }
        unsafe { self.mem.set(*c, encrypt(t)) };
        *c += 1;
        *d += 1;
        Ok(true)
    }

    #[cold]
    fn bad(&self, c: u32) -> Exit {
        Exit::Error(format!(
            "cell [{}] = {} is outside the range fast20 defines (0..=140)",
            c,
            unsafe { self.mem.get(c) as u32 }
        ))
    }

    /// Read a memory cell (for tests and tools).
    pub fn cell(&mut self, addr: u32) -> Option<u32> {
        self.load_cell(addr).ok().map(|v| v as u32)
    }
}

/// Machine registers and step count, passed by value through the hot loop.
#[derive(Clone, Copy)]
struct Regs {
    a: u32,
    c: u32,
    d: u32,
    steps: u64,
}

/// The hot loop. Executes everything except I/O and halt; stops before a
/// step that meets uninitialised memory, a bad cell, or (on jumps, when
/// LIMITED) the step limit, leaving that step to the slow path.
///
/// # Safety
/// `c` and `d` must be below `SPACE`.
#[inline(never)]
unsafe fn fast_loop<S: Space, const LIMITED: bool>(mem: &mut S, r: Regs, limit: u64) -> Regs {
    let Regs {
        mut a,
        mut c,
        mut d,
        mut steps,
    } = r;
    macro_rules! stop {
        () => {
            return Regs { a, c, d, steps }
        };
    }
    loop {
        let cell = mem.get(c);
        let k = kind(cell);
        if k == K_JMP {
            let p = mem.get(d);
            let t = mem.get(p as u32);
            // An uninitialised pointer cell reads as 0, so check it as well
            // as the target (uninitialised or not encryptable: kind 0).
            if p == 0 || t < 1 << KIND_SHIFT || (LIMITED && steps + 1 >= limit) {
                stop!();
            }
            c = p as u32;
            mem.set(c, encrypt(t));
        } else if k == K_NOP {
            mem.set(c, encrypt(cell));
        } else {
            let x = mem.get(d);
            // d == c means the instruction overwrites itself; the slow path
            // handles that (and its possibly undefined encryption).
            if x == 0 || d == c {
                stop!();
            }
            match k {
                K_MOVD => d = x as u32,
                K_ROT => {
                    a = rot18(x as u32);
                    mem.set(d, pack(d, a));
                }
                K_CRZ => {
                    a = crz19(a, x as u32);
                    mem.set(d, pack(d, a));
                }
                _ => stop!(),
            }
            mem.set(c, encrypt(cell));
        }
        steps += 1;
        c += 1;
        d += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn next_encrypts_and_keeps_the_phase() {
        for v in 0..XLAT_N {
            for o in 0..94 {
                let cell = make(v, o);
                let n = encrypt(cell);
                let e = XLAT[v as usize] as u32;
                assert_eq!(n as u32, e);
                let o2 = ((n >> STATE_SHIFT) & 0xffff) as u32 % 94;
                // Same address, so (opcode - value) mod 94 is unchanged.
                assert_eq!((o + 94 * 2 - v % 94) % 94, (o2 + 94 * 2 - e % 94) % 94);
                assert_eq!(kind(n), kind_of(o2));
            }
        }
    }

    #[test]
    fn bad_values_are_not_executable() {
        assert_eq!(kind(make(XLAT_N, 0)), K_BAD);
        assert_eq!(kind(make(END - 1, 5)), K_BAD);
    }

    #[test]
    fn rot18_rotates_the_low_trits_only() {
        let mut x: u32 = 12345;
        for _ in 0..100_000 {
            x = x.wrapping_mul(1_103_515_245).wrapping_add(12345) % END;
            let (top, low) = (x / THIRD, x % THIRD);
            let want = top * THIRD + low / 3 + (low % 3) * 3u32.pow(17);
            assert_eq!(rot18(x), want);
        }
    }

    #[test]
    fn paged_and_native_backends_agree() {
        for name in [
            "f20-movd-far",
            "f20-movd-fill",
            "f20-movd-chain",
            "f20-crz",
            "f20-nop-run",
        ] {
            let path = format!(
                "{}/../conformance/cases/{name}.mb",
                env!("CARGO_MANIFEST_DIR")
            );
            let src = std::fs::read(path).unwrap();
            let opts = Options {
                max_steps: 50_000_000,
                strict: false,
            };
            let mut a = crate::BufIo::new(b"");
            let mut b = crate::BufIo::new(b"");
            let ra = load::<crate::mem::Paged>(&src).map(|mut m| m.run(&mut a, &opts));
            let rb = load::<crate::mem::NativeSpace>(&src).map(|mut m| m.run(&mut b, &opts));
            assert_eq!(ra, rb, "{name}");
            assert_eq!(a.output, b.output, "{name}");
        }
    }
}
