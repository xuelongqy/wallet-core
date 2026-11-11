# macOS C ABI release

`V-macos` and `V-macos-rN` build the reviewed native source for the existing plain
`V` **draft** release. For example, `4.9.3-macos-r1` targets `4.9.3`; retries use
new immutable tags. See [the shared branch/source policy](platform-releases.md).
The workflow checks out the triggering commit, requires it to be reachable from
`origin/master-SHARED`, checks the official upstream ancestry of native and WASI
sources, and requires the plain release tag to equal the exact reviewed WASI pin.

All native release workflows pin the validated 4.9.3 WASI integration commit
`6b5741e52d0b61ff0254abf8301f0c0ea77f7083`. The plain fork version tag must
match it, and both source histories must contain official 4.9.3. Local source
validation does not establish hosted build, runtime or upload acceptance.

## Build and artifact contract

1. `macos-15` builds and runs arm64; `macos-15-intel` builds and runs x86_64. Both
   use Release, minimum macOS 12.0, pinned Rust `nightly-2025-12-11` and cbindgen
   `0.29.2`, source-pinned Protobuf `3.20.3`, JSON from `tools/dependencies-version`,
   and Boost headers `1.83.0`. CMake/Ninja come from the runner/Homebrew; actual
   Xcode, Clang, SDK, Swift, Rust and CMake versions are recorded in each manifest.
2. `tools/macos-release-build` bootstraps protobuf and the repository's two native
   plugins, then runs `tools/generate-files native` serially. A fresh checkout needs
   no generated headers or previous Core/Rust libraries. No Swift wrapper,
   SwiftProtobuf, xcodegen, or full iOS SDK build is required. Cache entries contain
   dependency sources, dependency host tools and Cargo downloads, never final Core
   libraries; each runner architecture has a separate key.
3. Each native build creates a versioned dynamic `TrustWalletCore.framework`, with
   headers, an umbrella header and Clang module map. Native C runtime checks resolve
   every public C declaration (466 in 4.9.3), exercise SHA256, ECDSA, Ed25519,
   Ethereum/Solana addresses and secure RNG, and verify the linked library path.
   A SwiftPM `binaryTarget` consumer imports, links and executes the C module.
4. The package job verifies matching source/version/API/headers/licenses, combines
   both slices, signs locally ad hoc, and verifies signatures, both architectures,
   minimum OS, the `@rpath/TrustWalletCore.framework/Versions/A/TrustWalletCore` ID,
   system-only dylib dependencies and the complete public C export subset. It then
   ZIPs and safely restores the package, compares all file bytes and symlink targets,
   and reruns C and SwiftPM consumers on arm64. Required x86_64 execution already
   occurred on Intel; packaging does not rely on Rosetta.
5. The stable asset is **`TrustWalletCore-macos.xcframework.zip`**. Its root contains
   `TrustWalletCore.xcframework`, `manifest.json`, and `licenses/`. The manifest
   retains both slice build/runtime records. License payloads preserve WalletCore,
   third-party, TrezorCrypto, Protobuf, Boost, locked Rust dependency notices and
   standard-library notices. The SHA256 is checked against `swift package
   compute-checksum` and reported in the job summary.

The XCFramework contains one `macos-arm64_x86_64` framework slice. It exposes the C
module; generated Swift WalletCore wrappers are not included. Ad hoc signing is a
local integrity check, not Developer ID signing or notarization. Metadata enforces
macOS 12.0; CI runs on macOS 15, so execution on macOS 12 itself is not covered.

## Local commands

Run on a matching native Mac host with Xcode command-line tools, Homebrew CMake and
Ninja, Python 3.9+, Ruby and rustup available. Allow approximately 30–90 minutes for
a cold native build; actual hosted duration and disk use need the first authorized
CI run. The driver rejects a host/architecture mismatch and an existing output.
Run only one source generator per checkout.

```sh
export RELEASE_VERSION=4.9.3
export WASM_SOURCE_COMMIT=<exact-reviewed-4.9.3-WASI-commit>
bash tools/macos-release-build arm64 /absolute/new/arm64-slice
# Run the equivalent x86_64 command on the Intel host, then transfer its slice.
python3 tools/package-macos-release.py package /absolute/new/arm64-slice /absolute/new/x86_64-slice /absolute/new/universal
PYTHONDONTWRITEBYTECODE=1 python3 tools/tests-macos-release.py
```

The lower-level `slice` command can verify an existing dylib for local packaging
experiments. An explicit x86_64 slice on an arm64 Mac may execute through Rosetta;
its manifest records both executed architecture and actual host architecture. Such
a local experiment does not establish the workflow's required native Intel PASS.
A package assembled from uncommitted source is an experiment, not a releasable
artifact identified by the baseline commit.

SwiftPM CLI executables need the dynamic framework embedded alongside the binary,
with an `@executable_path/Frameworks` rpath. The checked-in consumer demonstrates
this during validation; a successful bare link alone is insufficient.

## Publication boundary

Build/package jobs have read-only repository permissions. Privileged destination
lookup and upload jobs never check out or execute repository scripts. Lookup
requires exactly one existing mutable draft and an absent macOS asset. Upload uses
the retained release ID, checks ID/tag/draft/immutability/absence again, uploads
without overwrite to that exact ID, then verifies uploaded size and SHA256. It does
not create or publish releases or replace assets. A rejected post-upload check is
reported as failure; it does not silently delete or overwrite the uploaded asset.

Temporary slice/package artifacts use this run ID and attempt, one-day retention,
and an always-run cleanup job restricted to those three exact names. Cleanup
requires Actions write permission but executes no checkout or repository scripts.
The permanent release asset remains after temporary artifact cleanup.
