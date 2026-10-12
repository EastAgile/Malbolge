//! fastbolge: a fast, spec-precise Malbolge interpreter.
//!
//! Two dialects are supported:
//!
//! * [`classic`]: Ben Olmstead's 1998 Malbolge. 10-trit words, 59049 cells.
//!   Matches the reference interpreter on every defined behaviour.
//! * [`fast20`]: the fixed-width Malbolge Unshackled dialect run by `fast20.c`,
//!   the interpreter MalbolgeLisp and blc-mb ship with. 19-trit words,
//!   rotation of the low 18 trits, 3^19 lazily initialised cells.
//!
//! Where the reference implementations hang or read out of bounds, fastbolge stops
//! with an [`Exit::Error`] instead.

pub mod classic;
pub mod fast20;
pub mod mem;
#[cfg(target_arch = "wasm32")]
mod wasm;

/// Opcodes, numbered as `(c + [c]) mod 94`.
pub mod op {
    pub const JMP: u8 = 4;
    pub const OUT: u8 = 5;
    pub const IN: u8 = 23;
    pub const ROT: u8 = 39;
    pub const MOVD: u8 = 40;
    pub const CRZ: u8 = 62;
    pub const NOP: u8 = 68;
    pub const HALT: u8 = 81;

    pub fn is_instruction(op: u8) -> bool {
        matches!(op, JMP | OUT | IN | ROT | MOVD | CRZ | NOP | HALT)
    }
}

/// Encryption table indexed by the raw cell value. Entries 33..=126 are the
/// standard xlat2. Entries 0..=32 and 127..=140 reproduce fast20.c's padding,
/// so fast20 programs that execute those values behave identically.
pub const XLAT: &[u8; 141] = b"SOMEBODY MAKE ME FEEL ALIVE[hj9>,\
5z]&gqtyfr$(we4{WP)H-Zn,[%\\3dL+Q;>U!pJS72FhOA1CB6v^=I_0/8|jsb9m<.TVac`uY*MK'X~xDl}REokN:#?G\"i@\
AND SHATTER ME";

/// Number of cell values with a defined encryption in fast20.
pub const XLAT_N: u32 = 141;

/// crz on one trit, indexed `[d][a]`.
const CRZ1: [[u8; 3]; 3] = [[1, 0, 0], [1, 0, 2], [2, 2, 1]];

/// crz on 5-trit chunks, indexed `a * 243 + d`.
static CRZ5: [u8; 243 * 243] = build_crz5();

const fn build_crz5() -> [u8; 243 * 243] {
    let mut t = [0u8; 243 * 243];
    let mut a = 0;
    while a < 243 {
        let mut d = 0;
        while d < 243 {
            let (mut r, mut k, mut aa, mut dd, mut i) = (0usize, 1usize, a, d, 0);
            while i < 5 {
                r += k * CRZ1[dd % 3][aa % 3] as usize;
                aa /= 3;
                dd /= 3;
                k *= 3;
                i += 1;
            }
            t[a * 243 + d] = r as u8;
            d += 1;
        }
        a += 1;
    }
    t
}

#[inline(always)]
fn crz5(a: u32, d: u32) -> u32 {
    // SAFETY: callers pass a, d < 243.
    unsafe { *CRZ5.get_unchecked((a * 243 + d) as usize) as u32 }
}

/// The crazy operation on 10-trit words.
#[inline(always)]
pub fn crz10(a: u32, d: u32) -> u32 {
    crz5(a % 243, d % 243) + 243 * crz5(a / 243, d / 243)
}

/// The crazy operation on 19-trit words.
#[inline(always)]
pub fn crz19(mut a: u32, mut d: u32) -> u32 {
    let (mut r, mut k) = (0, 1);
    for _ in 0..3 {
        r += k * crz5(a % 243, d % 243);
        a /= 243;
        d /= 243;
        k *= 243;
    }
    // The top chunk has 4 trits; crz(0, 0) = 1 in the unused fifth trit.
    r + k * (crz5(a, d) - 81)
}

/// Reference (trit-by-trit) crazy operation on `width`-trit words.
pub fn crz_slow(mut a: u64, mut d: u64, width: u32) -> u64 {
    let (mut r, mut k) = (0, 1);
    for _ in 0..width {
        r += k * CRZ1[(d % 3) as usize][(a % 3) as usize] as u64;
        a /= 3;
        d /= 3;
        k *= 3;
    }
    r
}

/// Program input and output.
pub trait Io {
    /// Write the accumulator. Both dialects truncate to a byte, like the
    /// reference interpreter's `putc`.
    fn put(&mut self, a: u32);
    /// Read one byte, `None` at end of input.
    fn get(&mut self) -> Option<u8>;
}

/// In-memory I/O: a fixed input and a growing output buffer.
#[derive(Default)]
pub struct BufIo {
    pub input: Vec<u8>,
    pub pos: usize,
    pub output: Vec<u8>,
}

impl BufIo {
    pub fn new(input: &[u8]) -> Self {
        BufIo {
            input: input.to_vec(),
            pos: 0,
            output: Vec::new(),
        }
    }
}

impl Io for BufIo {
    fn put(&mut self, a: u32) {
        self.output.push(a as u8);
    }
    fn get(&mut self) -> Option<u8> {
        let b = self.input.get(self.pos).copied();
        self.pos += b.is_some() as usize;
        b
    }
}

/// Why execution stopped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Exit {
    /// The program executed a halt instruction.
    Halted,
    /// The step limit was reached.
    OutOfSteps,
    /// The program could not be loaded.
    LoadError(String),
    /// The program did something the reference interpreter does not define.
    Error(String),
}

/// Result of a run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    pub exit: Exit,
    /// Instructions executed (including the halt).
    pub steps: u64,
}

/// Interpreter options.
#[derive(Debug, Clone, Copy)]
pub struct Options {
    /// Stop once this many steps have run. Classic stops exactly; fast20
    /// checks the limit on jumps, so it can overshoot by a run of no-ops.
    pub max_steps: u64,
    /// Classic only: reject bytes outside 33..=126 that are not whitespace.
    /// The reference stores them and hangs if they are ever executed.
    pub strict: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            max_steps: u64::MAX,
            strict: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// xorshift, so the tests need no dependencies.
    fn rng(s: &mut u64) -> u64 {
        *s ^= *s << 13;
        *s ^= *s >> 7;
        *s ^= *s << 17;
        *s
    }

    #[test]
    fn crz10_matches_tritwise() {
        for a in (0..59049).step_by(97) {
            for d in (0..59049).step_by(89) {
                assert_eq!(
                    crz10(a, d) as u64,
                    crz_slow(a as u64, d as u64, 10),
                    "a={a} d={d}"
                );
            }
        }
        assert_eq!(crz10(59048, 59048), crz_slow(59048, 59048, 10) as u32);
    }

    #[test]
    fn crz19_matches_tritwise() {
        let end = 3u64.pow(19);
        let mut s = 0x9e3779b97f4a7c15;
        for _ in 0..200_000 {
            let (a, d) = (rng(&mut s) % end, rng(&mut s) % end);
            assert_eq!(
                crz19(a as u32, d as u32) as u64,
                crz_slow(a, d, 19),
                "a={a} d={d}"
            );
        }
        for (a, d) in [(0, 0), (end - 1, end - 1), (0, end - 1), (end - 1, 0)] {
            assert_eq!(crz19(a as u32, d as u32) as u64, crz_slow(a, d, 19));
        }
    }

    #[test]
    fn xlat_is_a_permutation_of_the_printables() {
        let mut seen = [false; 127];
        for &b in &XLAT[33..127] {
            assert!((33..127).contains(&b));
            assert!(!seen[b as usize]);
            seen[b as usize] = true;
        }
    }
}
