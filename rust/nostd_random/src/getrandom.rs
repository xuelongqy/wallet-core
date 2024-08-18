use std::mem::MaybeUninit;

use getrandom::Error;

use crate::wasi::getrandom_inner;

#[inline(always)]
pub unsafe fn slice_assume_init_mut<T>(slice: &mut [MaybeUninit<T>]) -> &mut [T] {
    // SAFETY: `MaybeUninit<T>` is guaranteed to be layout-compatible with `T`.
    &mut *(slice as *mut [MaybeUninit<T>] as *mut [T])
}

#[inline(always)]
pub unsafe fn slice_as_uninit_mut<T>(slice: &mut [T]) -> &mut [MaybeUninit<T>] {
    // SAFETY: `MaybeUninit<T>` is guaranteed to be layout-compatible with `T`.
    &mut *(slice as *mut [T] as *mut [MaybeUninit<T>])
}

#[inline]
pub fn getrandom(dest: &mut [u8]) -> Result<(), Error> {
    // SAFETY: The `&mut MaybeUninit<_>` reference doesn't escape, and
    // `getrandom_uninit` guarantees it will never de-initialize any part of
    // `dest`.
    getrandom_uninit(unsafe { slice_as_uninit_mut(dest) })?;
    Ok(())
}

#[inline]
pub fn getrandom_uninit(dest: &mut [MaybeUninit<u8>]) -> Result<&mut [u8], Error> {
    if !dest.is_empty() {
        getrandom_inner(dest)?;
    }
    // SAFETY: `dest` has been fully initialized by `imp::getrandom_inner`
    // since it returned `Ok`.
    Ok(unsafe { slice_assume_init_mut(dest) })
}
