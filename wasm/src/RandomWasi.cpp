#include <cstddef>
#include <cstdint>
#include <stdio.h>
#include <emscripten.h>

// clang-format off
static uint32_t
wasi_random(void)
{
    uint8_t buf[4] = { 0 };
    __wasi_random_get(buf, 4);
    uint32_t num = (buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3];
    return num;
}
// clang-format on

extern "C" {
    uint32_t random32(void) {
        return wasi_random();
    }

    void random_buffer(uint8_t* buf, size_t len) {
        __wasi_random_get(buf, len);
        return;
    }

} // extern "C"