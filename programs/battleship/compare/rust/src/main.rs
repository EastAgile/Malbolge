//! Battleship in Rust, written to behave exactly like the Malbolge version.
//!
//! Same rules, same computer opponent, same xorshift32 generator seeded the
//! same way (the admiral's name places your fleet, the name plus your first
//! shot place the enemy's, then the generator stops reading the keyboard), and
//! the same output, byte for byte, for the same keystrokes. Characters are
//! compared through the same 8-bit code the Malbolge input decoder produces.

use std::io::{self, Read, Write};

const N: usize = 8;
const SHIPS: [usize; 4] = [5, 4, 3, 2];
const FLEET_CELLS: u32 = 14;

const CLEAR: &str = "\x1b[2J\x1b[H";
const R: &str = "\x1b[0m";
const BOLD: &str = "\x1b[1m";
const RED: &str = "\x1b[91m";
const GREEN: &str = "\x1b[92m";
const BLUE: &str = "\x1b[94m";
const CYAN: &str = "\x1b[96m";
const GREY: &str = "\x1b[90m";
const YELLOW: &str = "\x1b[93m";

const RNG_INIT: u32 = 0x2545_F491;

// ---- input codes ----------------------------------------------------------
// The Malbolge program reads a character as the low five trits of its value
// and turns them into an 8-bit code. Newline and EOF have their own values.

fn gray(x: u32) -> u32 {
    x ^ (x >> 1)
}

fn code_of_trits(trits: [u32; 5]) -> u32 {
    let mut j = 0;
    let mut p = 1;
    for t in trits {
        j += [1, 0, 2][t as usize] * p;
        p *= 3;
    }
    gray(j) ^ gray(243)
}

/// 8-bit input code of a character, or of EOF (`None`).
fn code(ch: Option<char>) -> u32 {
    match ch {
        None => code_of_trits([2; 5]),
        Some('\n') => code_of_trits([1, 2, 2, 2, 2]),
        Some(c) => {
            let mut v = c as u32;
            let mut t = [0; 5];
            for x in t.iter_mut() {
                *x = v % 3;
                v /= 3;
            }
            code_of_trits(t)
        }
    }
}

fn code_of(c: char) -> u32 {
    code(Some(c))
}

// ---- the generator ----------------------------------------------------------

struct Rng {
    x: u32,
    seeding: bool,
}

impl Rng {
    fn step(&mut self) {
        let mut x = self.x;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.x = x;
    }

    fn mix(&mut self, c: u32) {
        self.x ^= c;
        if self.x == 0 {
            self.x = 1;
        }
        self.step();
    }
}

// ---- the game -------------------------------------------------------------

struct Quit;

struct Game<I: Iterator<Item = char>, W: Write> {
    input: I,
    out: W,
    rng: Rng,
    eship: [bool; 64],
    eshot: [bool; 64],
    pship: [bool; 64],
    pshot: [bool; 64],
    ehits: u32,
    phits: u32,
    tgt: bool,
    anchor: usize,
}

impl<I: Iterator<Item = char>, W: Write> Game<I, W> {
    fn new(input: I, out: W) -> Self {
        Game {
            input,
            out,
            rng: Rng {
                x: RNG_INIT,
                seeding: true,
            },
            eship: [false; 64],
            eshot: [false; 64],
            pship: [false; 64],
            pshot: [false; 64],
            ehits: 0,
            phits: 0,
            tgt: false,
            anchor: 0,
        }
    }

    fn w(&mut self, s: &str) {
        self.out.write_all(s.as_bytes()).expect("write failed");
    }

    fn getc(&mut self) -> u32 {
        self.out.flush().expect("flush failed");
        let c = code(self.input.next());
        if self.rng.seeding {
            self.rng.mix(c);
        }
        c
    }

    /// Read to the end of the line; EOF quits.
    fn drain(&mut self) -> Result<(), Quit> {
        loop {
            let c = self.getc();
            if c == code(Some('\n')) {
                return Ok(());
            }
            if c == code(None) {
                return Err(Quit);
            }
        }
    }

    fn place_fleet(&mut self) -> [bool; 64] {
        'board: loop {
            let mut ships = [false; 64];
            let mut blocked = [false; 64];
            for &len in &SHIPS {
                let mut tries: u8 = 0;
                let cells = loop {
                    self.rng.step();
                    let k = (self.rng.x & 63) as usize;
                    let horiz = (self.rng.x >> 6) & 1 == 1;
                    let (r, c) = (k / N, k % N);
                    if (if horiz { c } else { r }) + len <= N {
                        let cells: Vec<usize> = (0..len)
                            .map(|i| {
                                if horiz {
                                    r * N + c + i
                                } else {
                                    (r + i) * N + c
                                }
                            })
                            .collect();
                        if !cells.iter().any(|&x| blocked[x]) {
                            break cells;
                        }
                    }
                    tries = tries.wrapping_add(1);
                    if tries == 0 {
                        continue 'board; // 256 misses: start the board over
                    }
                };
                for x in cells {
                    ships[x] = true;
                    let (cr, cc) = ((x / N) as isize, (x % N) as isize);
                    for dr in -1..=1 {
                        for dc in -1..=1 {
                            let (r, c) = (cr + dr, cc + dc);
                            if (0..N as isize).contains(&r) && (0..N as isize).contains(&c) {
                                blocked[r as usize * N + c as usize] = true;
                            }
                        }
                    }
                }
            }
            return ships;
        }
    }

    fn render(&mut self) {
        let mut s = String::new();
        s += CLEAR;
        s += &format!("{BOLD}   Enemy waters\n{R}{GREY}    A B C D E F G H\n{R}");
        for r in 0..N {
            s += &format!("  {} ", r + 1);
            for c in 0..N {
                let k = r * N + c;
                s += &match (self.eshot[k], self.eship[k]) {
                    (true, true) => format!("{RED}X {R}"),
                    (true, false) => format!("{BLUE}o {R}"),
                    _ => format!("{GREY}. {R}"),
                };
            }
            s += "\n";
        }
        s += &format!("{BOLD}\n   Your fleet\n{R}{GREY}    A B C D E F G H\n{R}");
        for r in 0..N {
            s += &format!("  {} ", r + 1);
            for c in 0..N {
                let k = r * N + c;
                s += &match (self.pship[k], self.pshot[k]) {
                    (true, true) => format!("{RED}X {R}"),
                    (true, false) => format!("{GREEN}# {R}"),
                    (false, true) => format!("{BLUE}o {R}"),
                    (false, false) => format!("{CYAN}~ {R}"),
                };
            }
            s += "\n";
        }
        s += "\n";
        self.w(&s);
    }

    /// The target cell, or `None` to redraw and ask again.
    fn read_shot(&mut self) -> Result<Option<usize>, Quit> {
        let c = self.getc();
        if c == code_of('Q') || c == code_of('q') || c == code(None) {
            return Err(Quit);
        }
        let col = (0..N).find(|&d| {
            c == code_of((b'A' + d as u8) as char) || c == code_of((b'a' + d as u8) as char)
        });
        if let Some(col) = col {
            let c = self.getc();
            if let Some(row) = (0..N).find(|&d| c == code_of((b'1' + d as u8) as char)) {
                self.drain()?;
                return Ok(Some(row * N + col));
            }
        }
        self.w(&format!("{YELLOW}  ? type like C5\n{R}"));
        self.drain()?;
        Ok(None)
    }

    /// Returns true when the computer has sunk the whole fleet.
    fn computer_turn(&mut self) -> bool {
        self.w(&format!("{BOLD}Computer is thinking...\n{R}"));
        let mut target = None;
        if self.tgt {
            let (ar, ac) = ((self.anchor / N) as isize, (self.anchor % N) as isize);
            for (dr, dc) in [(-1, 0), (1, 0), (0, -1), (0, 1)] {
                let (r, c) = (ar + dr, ac + dc);
                if (0..N as isize).contains(&r) && (0..N as isize).contains(&c) {
                    let k = r as usize * N + c as usize;
                    if !self.pshot[k] {
                        target = Some(k);
                        break;
                    }
                }
            }
            if target.is_none() {
                self.tgt = false; // back to hunting
            }
        }
        let target = loop {
            if let Some(t) = target {
                break t;
            }
            self.rng.step();
            let k = (self.rng.x & 63) as usize;
            if !self.pshot[k] {
                target = Some(k);
            }
        };
        self.pshot[target] = true;
        let col = (b'A' + (target % N) as u8) as char;
        let row = (b'1' + (target / N) as u8) as char;
        self.w(&format!("{BOLD}Computer fires at {R}{col}{row}"));
        if self.pship[target] {
            self.w(&format!("{RED}{BOLD} - HIT!\n{R}"));
            self.phits += 1;
            if !self.tgt {
                self.tgt = true;
                self.anchor = target;
            }
            return self.phits == FLEET_CELLS;
        }
        self.w(&format!("{BLUE} - miss.\n{R}"));
        false
    }

    fn play(&mut self) {
        if self.play_inner().is_err() {
            self.w("\nAbandoning ship. Bye.\n");
        }
        self.out.flush().expect("flush failed");
    }

    fn play_inner(&mut self) -> Result<(), Quit> {
        self.w(&format!(
            "{CLEAR}{BOLD}{CYAN}BATTLESHIP{R}  (in Malbolge Unshackled)\n\n\
             Malbolge has no clock and no random source, so the sea is stirred by\n\
             what you type.  Each key is folded into a generator built from\n\
             self-encrypting Malbolge code cells.  Your name places your fleet.\n\
             The enemy fleet does not exist until you fire your first shot: your\n\
             name and that shot place it, then the shot is scored against it.\n\
             After that the generator stops listening to the keyboard.\n\n\
             {BOLD}Name your admiral{R} (any text, then Enter): "
        ));
        loop {
            let c = self.getc();
            if c == code(Some('\n')) || c == code(None) {
                break;
            }
        }
        for _ in 0..8 {
            self.rng.step();
        }
        self.w("\nPlacing your fleet...\n");
        self.pship = self.place_fleet();
        loop {
            self.render();
            self.w(&format!(
                "{BOLD}Your shot{R} (column A-H, row 1-8, e.g. C5; Q quits): "
            ));
            let Some(k) = self.read_shot()? else { continue };
            if self.rng.seeding {
                self.eship = self.place_fleet();
                self.rng.seeding = false;
                self.w(&format!("{GREY}  (the enemy fleet is now at sea)\n{R}"));
            }
            if self.eshot[k] {
                self.w(&format!("{YELLOW}  Already fired there.\n{R}"));
                continue;
            }
            self.eshot[k] = true;
            if self.eship[k] {
                self.w(&format!("{RED}{BOLD}  HIT!\n{R}"));
                self.ehits += 1;
                if self.ehits == FLEET_CELLS {
                    self.render();
                    self.w(&format!(
                        "{BOLD}{GREEN}You sank the enemy fleet. Victory!\n{R}"
                    ));
                    return Ok(());
                }
            } else {
                self.w(&format!("{BLUE}  Miss.\n{R}"));
            }
            if self.computer_turn() {
                self.render();
                self.w(&format!("{BOLD}{RED}Your fleet is destroyed. Defeat.\n{R}"));
                return Ok(());
            }
            self.w(&format!("{GREY}(press Enter)\n{R}"));
            self.drain()?;
        }
    }
}

/// Characters from stdin, one at a time, decoding UTF-8 as it arrives.
struct Stdin {
    inner: io::Stdin,
}

impl Iterator for Stdin {
    type Item = char;

    fn next(&mut self) -> Option<char> {
        let mut buf = [0u8; 4];
        let mut lock = self.inner.lock();
        lock.read_exact(&mut buf[..1]).ok()?;
        let n = match buf[0] {
            0xF0.. => 4,
            0xE0.. => 3,
            0xC0.. => 2,
            _ => 1,
        };
        if n > 1 {
            lock.read_exact(&mut buf[1..n]).ok()?;
        }
        std::str::from_utf8(&buf[..n]).ok()?.chars().next()
    }
}

fn main() {
    let stdout = io::stdout();
    let mut game = Game::new(Stdin { inner: io::stdin() }, stdout.lock());
    game.play();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(input: &str) -> String {
        let mut out = Vec::new();
        Game::new(input.chars(), &mut out).play();
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn same_seed_same_game_and_quit_on_eof() {
        let a = run("Larry\nC5\n\n");
        assert_eq!(a, run("Larry\nC5\n\n"));
        assert!(a.ends_with("\nAbandoning ship. Bye.\n"));
    }

    #[test]
    fn first_shot_changes_only_the_enemy_fleet() {
        let mut g1 = Game::new("Larry\nC5\n".chars(), Vec::new());
        let mut g2 = Game::new("Larry\nD4\n".chars(), Vec::new());
        g1.play();
        g2.play();
        assert_eq!(g1.pship, g2.pship);
        assert_ne!(g1.eship, g2.eship);
    }

    #[test]
    fn fleets_are_legal() {
        for i in 0..500 {
            let mut g = Game::new(
                format!("admiral {i}\nA1\n")
                    .chars()
                    .collect::<Vec<_>>()
                    .into_iter(),
                Vec::new(),
            );
            g.play();
            for fleet in [g.pship, g.eship] {
                assert_eq!(fleet.iter().filter(|&&b| b).count(), 14);
            }
        }
    }

    #[test]
    fn input_codes_match_the_malbolge_decoder() {
        // characters 243 apart share a code, exactly as in the Malbolge program
        assert_eq!(
            code_of('A'),
            code_of(char::from_u32('A' as u32 + 243).unwrap())
        );
        assert_ne!(code_of('A'), code_of('B'));
        assert_ne!(code(None), code(Some('\n')));
    }
}
