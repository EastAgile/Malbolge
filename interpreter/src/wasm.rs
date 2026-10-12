//! WebAssembly interface: plain exported functions, no bindings generator.
//!
//! A single interpreter session lives in a global. The host:
//!   1. writes the program into memory from `fb_alloc`, calls `fb_load`;
//!   2. writes stdin into memory from `fb_alloc`, calls `fb_set_input`;
//!   3. calls `fb_run(max_steps)` repeatedly (it is resumable) and drains
//!      output with `fb_output_ptr` / `fb_output_len` / `fb_clear_output`.

use crate::{classic, fast20, BufIo, Exit, Options};
use std::cell::RefCell;

enum Engine {
    Classic(classic::Program),
    Fast20(Box<fast20::Paged>),
}

struct Session {
    engine: Option<Engine>,
    io: BufIo,
    message: String,
    steps: u64,
}

thread_local! {
    static S: RefCell<Session> = RefCell::new(Session { engine: None, io: BufIo::default(), message: String::new(), steps: 0 });
}

/// Allocate `len` bytes for the host to write into.
#[no_mangle]
pub extern "C" fn fb_alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len.max(1));
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

/// Free memory from `fb_alloc`.
#[no_mangle]
pub unsafe extern "C" fn fb_free(ptr: *mut u8, len: usize) {
    drop(Vec::from_raw_parts(ptr, 0, len.max(1)));
}

/// Load a program. mode 0 = classic, 1 = fast20. Returns 0 on success, 2 on
/// a load error (see `fb_message_*`).
#[no_mangle]
pub unsafe extern "C" fn fb_load(mode: u32, ptr: *const u8, len: usize) -> u32 {
    let src = std::slice::from_raw_parts(ptr, len);
    let opts = Options::default();
    S.with(|s| {
        let mut s = s.borrow_mut();
        s.engine = None;
        s.io = BufIo::default();
        s.steps = 0;
        s.message.clear();
        let r = if mode == 0 {
            classic::load(src, &opts).map(Engine::Classic)
        } else {
            fast20::load(src).map(|m| Engine::Fast20(Box::new(m)))
        };
        match r {
            Ok(e) => {
                s.engine = Some(e);
                0
            }
            Err(Exit::LoadError(m)) | Err(Exit::Error(m)) => {
                s.message = m;
                2
            }
            Err(_) => 2,
        }
    })
}

/// Set the program's entire standard input. Reading past it gives EOF.
#[no_mangle]
pub unsafe extern "C" fn fb_set_input(ptr: *const u8, len: usize) {
    let inp = std::slice::from_raw_parts(ptr, len).to_vec();
    S.with(|s| {
        let mut s = s.borrow_mut();
        s.io.input = inp;
        s.io.pos = 0;
    });
}

/// Run until `max_steps` total steps. Returns 0 halted, 1 step limit
/// reached (call again to continue), 2 no program loaded, 3 undefined
/// behaviour (see `fb_message_*`).
#[no_mangle]
pub extern "C" fn fb_run(max_steps: f64) -> u32 {
    let opts = Options {
        max_steps: max_steps as u64,
        ..Options::default()
    };
    S.with(|s| {
        let s = &mut *s.borrow_mut();
        let out = match s.engine.as_mut() {
            Some(Engine::Classic(p)) => p.run(&mut s.io, &opts),
            Some(Engine::Fast20(m)) => m.run(&mut s.io, &opts),
            None => return 2,
        };
        s.steps = out.steps;
        match out.exit {
            Exit::Halted => 0,
            Exit::OutOfSteps => 1,
            Exit::LoadError(m) | Exit::Error(m) => {
                s.message = m;
                3
            }
        }
    })
}

#[no_mangle]
pub extern "C" fn fb_steps() -> f64 {
    S.with(|s| s.borrow().steps as f64)
}

#[no_mangle]
pub extern "C" fn fb_output_ptr() -> *const u8 {
    S.with(|s| s.borrow().io.output.as_ptr())
}

#[no_mangle]
pub extern "C" fn fb_output_len() -> usize {
    S.with(|s| s.borrow().io.output.len())
}

#[no_mangle]
pub extern "C" fn fb_clear_output() {
    S.with(|s| s.borrow_mut().io.output.clear())
}

#[no_mangle]
pub extern "C" fn fb_message_ptr() -> *const u8 {
    S.with(|s| s.borrow().message.as_ptr())
}

#[no_mangle]
pub extern "C" fn fb_message_len() -> usize {
    S.with(|s| s.borrow().message.len())
}
