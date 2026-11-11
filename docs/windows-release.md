# Windows shared-library releases

This workflow builds the exact reviewed shared-source commit identified by an
immutable `<version>-windows` tag, or `<version>-windows-r<N>` retry tag. It
uploads only `Windows.tar.gz` to an existing, mutable **draft** version Release.
It never creates a Release, publishes the draft, or replaces an existing asset.
The workflow belongs on the common `master-SHARED` native branch; see the
[branch, tag and source policy](platform-releases.md).

## Source and publication prerequisites

1. Integrate the official version into both shared and WASI source histories.
   Preserve the real upstream ancestry; a squash alone does not establish it.
   Review and validate the complete source trees before committing and pushing.
2. Create the fork version tag at the exact reviewed WASI source commit used for
   the WASM asset. Set `WASM_SOURCE_COMMIT` in the Linux, Windows and macOS
   workflows to that same full SHA. The 4.9.3 workflows pin the validated WASI
   integration commit `6b5741e52d0b61ff0254abf8301f0c0ea77f7083`.
   Missing or mismatched tags, pins and required ancestry fail closed.
3. Prepare one mutable draft Release for the version tag, without a
   `Windows.tar.gz` asset. After publication authorization, create and push
   `4.9.3-windows` at the reviewed native commit already integrated into remote
   `master-SHARED`. The build tag
   starts CI; the moving branch head is never used as the build source.
4. Inspect the build, runtime and upload checks before publishing the draft.
   For transient failures, rerun all jobs because cleanup removes intermediate
   artifacts. For source/CI fixes use a new immutable `4.9.3-windows-r1` tag.
   Never move an old tag or delete/replace an asset as an automatic retry.

`tools/shared-release-source` is shared with Linux and macOS. It checks that the
fork version tag equals the pinned WASI commit, fetches remote `master-SHARED`
and requires the build commit to be an ancestor of that branch. An advanced
native branch still permits rerunning an older build tag. It then fetches the official version tag
without importing it into the fork tag namespace, and requires the official
commit to be an ancestor of both the checked-out shared source and the WASI
release source. The two customized branches need not contain each other.

The paginated Release lookup includes drafts, requires exactly one matching
tag, and passes its numeric ID to the upload job. Draft status, mutability and
asset absence are checked again immediately before upload. The verified asset
size and SHA-256 must match GitHub's uploaded-asset metadata.

## Build and runtime asset

The `windows-2022` build reuses `tools/windows-build.ps1`: x64 Release ClangCL,
MSVC ABI, `/MD`, Rust `x86_64-pc-windows-msvc` with the locked dependency graph,
and the existing fixed tool/dependency versions. Its full GTest suite, RNG
boundary/failure checks, five relocated MSVC C/C++ and dynamic consumers, PE
architecture, public C export list and runtime dependency checks must pass.
ARM64 and alternative toolchain/runtime configurations are not built.

The existing SDK archive remains unchanged apart from complete license notices.
The release-only archive contains:

```text
windows-x64/libTrustWalletCore.dll
windows-x64/README.md
windows-x64/licenses/WalletCore.txt
windows-x64/licenses/WalletCore-3rd-party.txt
windows-x64/licenses/Protobuf.txt
windows-x64/licenses/TrezorCrypto.txt
windows-x64/licenses/Boost.txt
```

`libTrustWalletCore.dll` is byte-identical to the verified SDK's
`shared/bin/TrustWalletCore.dll`. Its name preserves the current bindings
default loader. The archive packager verifies an x64 PE32+ DLL, rejects missing
inputs and symlinks, includes fixed license/runtime documentation, sets stable
archive metadata and refuses to overwrite a destination. A relocated extracted
runtime is hash-compared with the SDK and run through the existing dynamic
consumer with build tools removed from `PATH`. The SDK's other consumers cover
static/import-library use; the runtime archive is intended for dynamic loaders.

Install the Microsoft Visual C++ Redistributable x64 on deployment machines;
the CRT is not bundled. See [runtime requirements](windows-runtime.md).

The build job has read-only repository access. Release lookup and upload have
`contents: write`; neither executes checked-out repository code. Only cleanup
has `actions: write`. A run/attempt-specific intermediate archive expires after
one day and is deleted by an always-run cleanup job. Service outages or forced
cancellation may defer cleanup until expiry. Uploads for one version serialize,
and GitHub's no-overwrite upload is used without `--clobber`.

## Offline checks

```sh
actionlint .github/workflows/linux-release.yml .github/workflows/windows-ci.yml .github/workflows/windows-release.yml
shellcheck tools/shared-release-tag tools/shared-release-source
bash -n tools/shared-release-tag
bash -n tools/shared-release-source
PYTHONDONTWRITEBYTECODE=1 python3 tools/tests-linux-release.py -v
PYTHONDONTWRITEBYTECODE=1 python3 tools/tests-windows-release.py -v
```

These tests execute the shared source gate using real fetches against separate
temporary native/upstream Git remotes, the actual privileged lookup script against API fixtures, and the
packager against synthetic PE inputs. They cover missing/mismatched pins,
upstream ancestry, native branch advance/off-branch/missing-branch behavior,
fork tag preservation, invalid build tags, draft-only lookup, API failures,
existing assets, archive layout, exact DLL bytes, reproducibility, architecture
and input rejection. Synthetic PE fixtures are not executable Windows binaries.
The actual tagged workflow requires the final source pins and authorization to
push the reviewed source and build tag; local checks cannot establish that
remote run's acceptance.
