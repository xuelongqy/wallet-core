# Linux shared-library releases

This workflow belongs to `master-SHARED`, not the upstream mirror `master`.
It builds native x64 and ARM64 shared libraries using the exact commit of a
`<version>-linux` tag (or `<version>-linux-r<N>` retry). It does not use the moving branch head.
The common [branch, tag and source policy](platform-releases.md) also applies
to Windows and macOS.

## Publishing later

1. Merge the verified upstream version tag into `master-SHARED`, preserving
   its shared-library and visibility
   changes. Review, validate, commit and push that merge and these CI files.
2. Create the fork version tag at the exact validated `wasi`
   source commit and set `WASM_SOURCE_COMMIT` in the workflow to that same SHA.
   Fetch official tags without importing them into the fork's tag namespace:
   `git fetch --no-tags upstream refs/tags/4.9.3:refs/upstream-tags/4.9.3`.
   Ensure an existing, mutable GitHub Release for the fork tag. A draft Release is
   suitable while collecting assets. `Linux.tar.gz` must not already exist.
3. After publication authorization, create and push `4.9.3-linux` at the
   reviewed shared-build commit already integrated into remote `master-SHARED`.
   Its suffix maps to Release `4.9.3`. Pushing this tag starts the workflow.
   No `workflow_dispatch` or default-branch workflow is required.
4. Inspect both build validations and the verified upload. Publish the draft
   only after every intended asset has been verified. If an upload already
   succeeded, rerunning intentionally refuses to overwrite it. Review any
   failed post-upload check before manually deciding how to handle that asset.

Never move an existing build tag to silently change the source of a release.
For transient failures, rerun **all jobs**, not only failed jobs: cleanup may
have removed the other architecture's temporary library. For CI/build fixes,
commit and push the correction, then push a fresh `4.9.3-linux-r1`, `-r2`, etc.
Each retry maps to Release `4.9.3` and remains immutable. Keep the Release in
draft until checks pass. Existing assets are never automatically replaced.
The workflow verifies that the fork's version tag matches the pinned WASM
source commit. It fetches remote `master-SHARED` and requires the build commit
to be an ancestor of that branch; the branch may advance after tagging.
The official upstream commit must be an ancestor of both the
checked-out shared-library build commit and the fork's `wasi` release commit.
These two customized branches need not be ancestors of each other. Previously
published version tags retain their original sources.

Linux, Windows and macOS pin the validated 4.9.3 WASI integration commit
`6b5741e52d0b61ff0254abf8301f0c0ea77f7083`. The plain fork version tag must
match this full SHA. The source check fails closed on a missing or mismatched
tag, pin, or required ancestry; hosted CI remains a separate validation.

The Release lookup uses paginated release lists, including drafts, and requires
exactly one matching tag. The ID is carried to the upload job for subsequent
checks, rather than using the published-release-only REST tag endpoint.

## Build and retention policy

- Native `ubuntu-22.04` and `ubuntu-22.04-arm` runners each use an Ubuntu 22.04
  container: Clang 14, GCC/libstdc++ 11, Ruby 3.0, Rust nightly-2025-12-11,
  cbindgen 0.29.2 and repository-pinned Protobuf 3.20.3.
- ELF architecture, SONAME, runtime dependencies, lack of RPATH/RUNPATH,
  public C API loading and Arc configuration queries must pass. Maximum
  required versions are GLIBC 2.34 and GLIBCXX 3.4.29. These checks do not
  replace application tests on supported distributions.
- Dependency caches are isolated by architecture and build inputs. The final
  shared libraries are not cached. Dependency compilation respects
  `CMAKE_BUILD_PARALLEL_LEVEL` (four in CI), including Protobuf and its plugins.
- Per-run/per-attempt temporary Artifacts carry the two libraries between jobs,
  expire after one day, and are deleted by an always-run cleanup job. Cancellation
  or service outages can prevent immediate cleanup; expiry is the fallback.
- Only `Linux.tar.gz` is uploaded to the existing Release, with these two entries:

  ```text
  linux-x64/libTrustWalletCore.so
  linux-arm64/libTrustWalletCore.so
  ```

  The archive is not saved as an Actions Artifact. Upload size and SHA-256 are
  checked against the GitHub asset metadata. There is no automatic Release
  creation or asset replacement.
- Source-check and build jobs have read-only repository access. Release lookup
  and upload receive `contents: write` (draft visibility requires push access).
  The lookup job does not checkout or execute repository scripts. Only cleanup
  receives `actions: write`. Upload jobs for the same version are serialized.

## Offline checks

From the repository root:

```sh
actionlint .github/workflows/linux-release.yml
shellcheck tools/linux-release-build tools/shared-release-tag tools/shared-release-source
for script in tools/linux-release-build tools/shared-release-tag tools/shared-release-source tools/install-dependencies; do
  bash -n "$script"
done
PYTHONDONTWRITEBYTECODE=1 python3 tools/tests-linux-release.py -v
```

Packaging tests use synthetic ELF headers and verify layout, reproducibility,
architecture mismatch rejection and non-overwriting behavior. Mocked ELF
inspection tests also exercise the ABI-version and runtime-dependency gates.
Tag tests cover initial/retry tags and invalid input. The workflow's actual
source check performs real fetches against separate temporary native/upstream
Git remotes. Tests cover a native branch advancing after tagging, off-branch
and missing native source, mismatched/missing pins, missing upstream ancestry,
and preservation of the fork WASI tag. The workflow's actual inline Release
lookup is exercised with mocked paginated GitHub responses,
including drafts, missing/duplicate versions, immutable releases and existing
assets. They do not
claim to execute the Linux builds. The first real two-architecture CI run must
be performed after the reviewed files and build tag are pushed.
