# Native release branches, tags and source pins

Linux, Windows and macOS share one native customization branch. This keeps
upstream synchronization separate without maintaining three platform forks.

| Reference | Purpose |
| --- | --- |
| `master` | Clean mirror of official upstream history. |
| `master-SHARED` | Shared-library, native platform build and release CI changes for all three platforms. |
| `wasi` | WASM-specific changes and validated WASM source. |
| `4.9.3` | Fork version tag at the exact validated WASI commit; also the source for GitHub's automatic source archives. |
| `4.9.3-linux`, `4.9.3-windows`, `4.9.3-macos` | Immutable native build tags, preferably at the same reviewed `master-SHARED` commit. |

Tags are repository-wide references; creating a platform tag does not change
`master` or any other branch. The workflow builds the tag's fixed commit, never
the latest branch head. A platform tag's source must already be integrated into
the remote `master-SHARED` history. A branch filter alongside a tag filter cannot
establish this ancestry; the workflows use tag triggers and a source check.

## Preparing a version

1. Fetch the official version without replacing the fork's version tag:

   ```sh
   git fetch --no-tags upstream refs/tags/4.9.3:refs/upstream-tags/4.9.3
   ```

   Integrate the verified official version into `wasi` and `master-SHARED`,
   retaining the real upstream
   parent history and each branch's customizations. A squash or copied files
   alone do not establish the required ancestry. Keep all three platforms'
   native CI changes in `master-SHARED`. Maintaining the clean `master` mirror
   is separate from release CI and is not required to trigger platform builds.
2. Validate and commit the complete WASI source, obtaining its real full
   40-character commit SHA. Set `WASM_SOURCE_COMMIT` to that SHA in all three
   native release workflows, then commit and review the complete native source
   and CI changes. The plain fork version tag must identify that same WASI
   commit, even though native artifacts use a different reviewed commit.
3. After push/release authorization, push the reviewed branch histories first.
   Create the fork `4.9.3` tag at the validated WASI commit and prepare one
   existing, mutable draft Release for `4.9.3`. Verify every intended asset name
   is absent before triggering its build. Never move a historical version tag
   or change its automatic source archive to repair an old release.
4. Create and push `4.9.3-linux`, `4.9.3-windows` and `4.9.3-macos` at the
   reviewed native commit. Each tag starts its own workflow from that commit.
   Source and build jobs have read-only repository access; privileged Release
   lookup jobs do not execute checked-out repository code. See the platform
   guides for their build and upload details.
5. Inspect the hosted build, runtime and uploaded-asset checks before publishing
   the draft. Workflows neither publish the draft nor silently replace assets.
   Local script checks do not establish hosted runner acceptance. The first
   remote execution remains a separate step after final pins and authorization.

All three workflows pin the validated 4.9.3 WASI integration commit
`6b5741e52d0b61ff0254abf8301f0c0ea77f7083`. Its tree matches the previously
validated WASI source and retains the official 4.9.3 and prior WASI ancestry.
The plain fork `4.9.3` tag must resolve to that exact commit before builds pass
the source check. Pinning source alone does not establish hosted CI acceptance.

## Common source check

`tools/shared-release-tag` accepts only `<version>-linux`, `<version>-windows`
or `<version>-macos`, with an optional `-r<N>` suffix where `N >= 1` and has no
leading zero. All platform suffixes map to the plain version Release.
`tools/shared-release-source` then requires:

- The fork version tag resolves to the exact pinned full WASI commit.
- The build commit is an ancestor of `origin`'s freshly fetched
  `refs/heads/master-SHARED` commit. A missing branch or off-branch commit
  fails before the official upstream fetch. The branch may have advanced after
  tagging, so an old build tag can still be rerun.
- The official upstream version commit is an ancestor of both the native build
  commit and the fork WASI tag commit. The two customized branches do not need
  to contain each other. Official tags are fetched into `FETCH_HEAD` without
  overwriting fork tags.

Only after every check passes does the script emit `release_tag` for downstream
jobs. The source pin, plain version tag and platform build tags are separate
inputs with different purposes; none can substitute for another.

## Retries and existing assets

For transient failures rerun all jobs: cleanup may already have removed an
earlier job's temporary artifact. For a source or CI correction, review and
integrate the new native commit into `master-SHARED`, then use a new immutable
tag such as `4.9.3-windows-r1`, `4.9.3-macos-r1` or `4.9.3-linux-r1`.
Never move an existing tag, force-push release history or automatically delete
an existing asset. A successful upload makes a retry refuse that asset; inspect
any failed post-upload verification before deciding how to handle it.

Windows and macOS require the Release to remain a mutable draft at lookup and
upload. Linux retains its existing support for a mutable draft or published
Release; keep a new multi-platform version in draft while collecting assets.
Uploads check for an absent asset immediately before upload and verify its size
and SHA-256 afterward. Temporary Actions artifacts use run/attempt-specific
names, expire after one day and have an always-run cleanup job; service outages
or forced cancellation can defer deletion until expiry.

Platform details: [Linux](linux-release.md), [Windows](windows-release.md),
[macOS](macos-release.md).
