#include <TrustWalletCore/TrustWalletCore.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "public-api-names.h"

static void require(int ok, const char *message) {
    if (!ok) { fprintf(stderr, "%s\n", message); exit(1); }
}

int main(int argc, char **argv) {
    require(argc == 2, "Pass the final framework binary path");
    void *handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    for (size_t i = 0; i < sizeof(public_api) / sizeof(public_api[0]); ++i)
        require(dlsym(handle, public_api[i]) != NULL, public_api[i]);
    Dl_info info;
    require(dladdr((const void *)TWDataCreateWithBytes, &info) != 0, "dladdr failed");
    char actual[4096], expected[4096];
    require(realpath(info.dli_fname, actual) && realpath(argv[1], expected), "realpath failed");
    require(strcmp(actual, expected) == 0, "Consumer linked another WalletCore binary");

    const uint8_t abc[] = {'a', 'b', 'c'};
    const uint8_t sha256[] = {0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,
                              0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad};
    TWData *message = TWDataCreateWithBytes(abc, sizeof abc);
    TWData *digest = TWHashSHA256(message);
    require(TWDataSize(digest) == sizeof sha256 && memcmp(TWDataBytes(digest), sha256, sizeof sha256) == 0,
            "SHA256 known vector failed");
    uint8_t secret[32] = {0}; secret[31] = 1;
    TWData *key_data = TWDataCreateWithBytes(secret, sizeof secret);
    struct TWPrivateKey *key = TWPrivateKeyCreateWithData(key_data);
    require(key != NULL, "Private key construction failed");
    struct TWPublicKey *pubkey = TWPrivateKeyGetPublicKeySecp256k1(key, false);
    TWData *signature = TWPrivateKeySign(key, digest, TWCurveSECP256k1);
    require(signature && TWPublicKeyVerify(pubkey, signature, digest), "ECDSA sign/verify failed");
    struct TWAnyAddress *address = TWAnyAddressCreateWithPublicKey(pubkey, TWCoinTypeEthereum);
    TWString *description = TWAnyAddressDescription(address);
    require(strcmp(TWStringUTF8Bytes(description), "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf") == 0,
            "Ethereum known address failed");
    TWStringDelete(description); TWAnyAddressDelete(address);
    TWDataDelete(signature); TWPublicKeyDelete(pubkey);

    pubkey = TWPrivateKeyGetPublicKeyEd25519(key);
    signature = TWPrivateKeySign(key, message, TWCurveED25519);
    require(signature && TWPublicKeyVerify(pubkey, signature, message), "Ed25519 sign/verify failed");
    address = TWAnyAddressCreateWithPublicKey(pubkey, TWCoinTypeSolana);
    description = TWAnyAddressDescription(address);
    require(TWAnyAddressIsValid(description, TWCoinTypeSolana), "Solana address validation failed");
    TWStringDelete(description); TWAnyAddressDelete(address);
    TWDataDelete(signature); TWPublicKeyDelete(pubkey);
    TWPrivateKeyDelete(key); TWDataDelete(key_data); TWDataDelete(digest); TWDataDelete(message);

    TWString *empty = TWStringCreateWithUTF8Bytes("");
    struct TWHDWallet *wallet = TWHDWalletCreate(128, empty);
    require(wallet != NULL, "Secure RNG wallet construction failed");
    TWHDWalletDelete(wallet); TWStringDelete(empty);
    require(dlclose(handle) == 0, "dlclose failed");
    printf("Native C ABI passed: %zu lookups, SHA256, ECDSA, Ed25519, Ethereum/Solana addresses, RNG; loaded %s\n",
           sizeof(public_api) / sizeof(public_api[0]), actual);
    return 0;
}
