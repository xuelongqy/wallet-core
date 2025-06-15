// SPDX-License-Identifier: Apache-2.0
//
// Copyright © 2017 Trust Wallet.

#![allow(clippy::missing_safety_doc)]

use std::ffi::{c_char, CString};

use nostd_random::getrandom::getrandom;

fn rng_bytes() -> [u8; 16] {
    let mut bytes = [0u8; 16];

    getrandom(&mut bytes).unwrap_or_else(|err| {
        // NB: getrandom::Error has no source; this is adequate display
        panic!("could not retrieve random bytes for uuid: {}", err)
    });

    bytes
}

/// Creates a random UUID.
/// This uses the [`getrandom`] crate to utilise the operating system's RNG
/// as the source of random numbers.
#[no_mangle]
pub unsafe extern "C" fn tw_uuid_random() -> *mut c_char {
    let res = uuid::Uuid::from_bytes(rng_bytes());
    CString::new(res.to_string()).unwrap().into_raw()
}
