//! Lazily initialised memory for the fast20 dialect.
//!
//! The address space is 3^19 cells. Each cell is a u64 holding the value in
//! the low 32 bits, its current opcode in bits 32..40 and the instruction
//! kind in bits 40..48 (see `fast20`). An all-zero cell means "not yet
//! initialised": memory starts zeroed and is filled with the initialisation
//! pattern a chunk at a time the first time the interpreter reads a zero
//! cell, so the hot loop needs no separate readiness or bounds checks.
//!
//! Two backends: [`Flat`] reserves the whole space with `mmap` (64-bit Unix),
//! [`Paged`] allocates chunks on demand (WebAssembly and everything else).

/// log2 of cells per chunk: 2^18 cells = 2 MiB, one huge page.
pub const CHUNK_BITS: u32 = 18;
pub const CHUNK: u32 = 1 << CHUNK_BITS;

pub trait Space {
    /// Reserve room for `cells` cells, all reading as zero.
    fn new(cells: u32) -> Self
    where
        Self: Sized;
    /// Make a chunk writable. The caller fills it.
    fn make_ready(&mut self, chunk: u32);
    /// # Safety
    /// `x` must be below the `cells` given to `new`.
    unsafe fn get(&self, x: u32) -> u64;
    /// # Safety
    /// `x` must be below the `cells` given to `new` and its chunk ready.
    unsafe fn set(&mut self, x: u32, v: u64);
    /// Hint that cell `x` will be read soon. `x` may be any value.
    #[inline(always)]
    fn prefetch(&self, _x: u32) {}
    /// The first `n` cells as one writable slice, if the backend stores
    /// them contiguously. Their chunks must be ready.
    fn contiguous(&mut self, _n: u32) -> Option<&mut [u64]> {
        None
    }
}

/// On-demand chunks behind a page table. Chunks that are not ready point at
/// one shared all-zero chunk.
pub struct Paged {
    table: Vec<*mut u64>,
    owned: Vec<Option<Box<[u64]>>>,
    zero: Box<[u64]>,
}

impl Space for Paged {
    fn new(cells: u32) -> Self {
        let n = (cells as usize).div_ceil(CHUNK as usize);
        let mut zero = vec![0u64; CHUNK as usize].into_boxed_slice();
        let zp = zero.as_mut_ptr();
        Paged {
            table: vec![zp; n],
            owned: (0..n).map(|_| None).collect(),
            zero,
        }
    }
    fn make_ready(&mut self, chunk: u32) {
        let mut b = vec![0u64; CHUNK as usize].into_boxed_slice();
        self.table[chunk as usize] = b.as_mut_ptr();
        self.owned[chunk as usize] = Some(b);
    }
    #[inline(always)]
    unsafe fn get(&self, x: u32) -> u64 {
        *self
            .table
            .get_unchecked((x >> CHUNK_BITS) as usize)
            .add((x & (CHUNK - 1)) as usize)
    }
    #[inline(always)]
    unsafe fn set(&mut self, x: u32, v: u64) {
        debug_assert!(self.table[(x >> CHUNK_BITS) as usize] != self.zero.as_mut_ptr());
        *self
            .table
            .get_unchecked((x >> CHUNK_BITS) as usize)
            .add((x & (CHUNK - 1)) as usize) = v;
    }
}

#[cfg(all(unix, target_pointer_width = "64"))]
pub use flat::Flat;

#[cfg(all(unix, target_pointer_width = "64"))]
mod flat {
    use super::{Space, CHUNK};
    use std::ffi::c_void;

    extern "C" {
        fn mmap(
            addr: *mut c_void,
            len: usize,
            prot: i32,
            flags: i32,
            fd: i32,
            off: i64,
        ) -> *mut c_void;
        fn munmap(addr: *mut c_void, len: usize) -> i32;
        #[cfg(target_os = "linux")]
        fn madvise(addr: *mut c_void, len: usize, advice: i32) -> i32;
    }
    const PROT_RW: i32 = 1 | 2;
    const MAP_PRIVATE: i32 = 2;
    #[cfg(target_os = "linux")]
    const MAP_ANONYMOUS: i32 = 0x20;
    #[cfg(not(target_os = "linux"))]
    const MAP_ANONYMOUS: i32 = 0x1000;
    #[cfg(target_os = "linux")]
    const MAP_NORESERVE: i32 = 0x4000;
    #[cfg(not(target_os = "linux"))]
    const MAP_NORESERVE: i32 = 0x40;
    #[cfg(target_os = "linux")]
    const MADV_HUGEPAGE: i32 = 14;

    /// The whole address space reserved up front; the OS backs pages as they
    /// are touched.
    pub struct Flat {
        base: *mut u64,
        bytes: usize,
    }

    impl Space for Flat {
        fn new(cells: u32) -> Self {
            let n = (cells as usize).div_ceil(CHUNK as usize);
            let bytes = n * CHUNK as usize * 8;
            unsafe {
                let p = mmap(
                    std::ptr::null_mut(),
                    bytes,
                    PROT_RW,
                    MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE,
                    -1,
                    0,
                );
                if p as isize == -1 {
                    panic!("cannot reserve {bytes} bytes of address space");
                }
                #[cfg(target_os = "linux")]
                if std::env::var_os("FASTBOLGE_NO_THP").is_none() {
                    madvise(p, bytes, MADV_HUGEPAGE);
                }
                Flat {
                    base: p as *mut u64,
                    bytes,
                }
            }
        }
        fn make_ready(&mut self, _chunk: u32) {}
        fn contiguous(&mut self, n: u32) -> Option<&mut [u64]> {
            assert!(n as usize * 8 <= self.bytes);
            Some(unsafe { std::slice::from_raw_parts_mut(self.base, n as usize) })
        }
        #[inline(always)]
        unsafe fn get(&self, x: u32) -> u64 {
            *self.base.add(x as usize)
        }
        #[inline(always)]
        unsafe fn set(&mut self, x: u32, v: u64) {
            *self.base.add(x as usize) = v;
        }
        #[inline(always)]
        fn prefetch(&self, x: u32) {
            #[cfg(target_arch = "x86_64")]
            unsafe {
                use std::arch::x86_64::{_mm_prefetch, _MM_HINT_T0};
                // Prefetching never faults, so any address is fine.
                _mm_prefetch::<_MM_HINT_T0>(self.base.wrapping_add(x as usize) as *const i8);
            }
            #[cfg(not(target_arch = "x86_64"))]
            let _ = x;
        }
    }

    impl Drop for Flat {
        fn drop(&mut self) {
            unsafe {
                munmap(self.base as *mut c_void, self.bytes);
            }
        }
    }
}

/// The best backend for this platform.
#[cfg(all(unix, target_pointer_width = "64"))]
pub type NativeSpace = Flat;
#[cfg(not(all(unix, target_pointer_width = "64")))]
pub type NativeSpace = Paged;
