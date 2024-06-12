// SPDX-License-Identifier: Apache-2.0
//
// Copyright © 2017 Trust Wallet.

#![allow(clippy::missing_safety_doc)]

use std::{
    ffi::{c_char, CString},
    time::SystemTime,
};

use rand::{rngs::SmallRng, RngCore, SeedableRng};

static mut RANDOM_COUNT: u64 = 0;

fn get_random_bytes() -> [u8; 16] {
    let timestamp = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(n) => n.as_secs(),
        Err(_) => panic!("System Time is before 1970"),
    };
    let mut bytes = [0u8; 16];
    let mut last_random = timestamp;
    for i in 0..16 {
        last_random = SmallRng::seed_from_u64(last_random + unsafe { RANDOM_COUNT }).next_u64();
        bytes[i] = last_random as u8;
        unsafe { RANDOM_COUNT = RANDOM_COUNT + 1 };
    }
    bytes
}

/// Creates a random UUID.
/// This uses the [`getrandom`] crate to utilise the operating system's RNG
/// as the source of random numbers.
#[no_mangle]
pub unsafe extern "C" fn tw_uuid_random() -> *const c_char {
    let res = uuid::Uuid::from_bytes(get_random_bytes());
    CString::new(res.to_string()).unwrap().into_raw()
}
