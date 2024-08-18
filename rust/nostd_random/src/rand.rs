use rand_core::{impls, CryptoRng, Error, RngCore};

use crate::getrandom::getrandom;

pub struct NoStdRng;

impl CryptoRng for NoStdRng {}

impl RngCore for NoStdRng {
    fn next_u32(&mut self) -> u32 {
        impls::next_u32_via_fill(self)
    }

    fn next_u64(&mut self) -> u64 {
        impls::next_u64_via_fill(self)
    }

    fn fill_bytes(&mut self, dest: &mut [u8]) {
        if let Err(e) = self.try_fill_bytes(dest) {
            panic!("Error: {}", e);
        }
    }

    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), Error> {
        getrandom(dest)?;
        Ok(())
    }
}
