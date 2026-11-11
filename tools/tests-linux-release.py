"""Offline native release guards and packaging tests; synthetic ELF bytes are not runnable."""

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from unittest import mock


TOOLS = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("package_linux", TOOLS / "package-linux-release.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CHECK_SPEC = importlib.util.spec_from_file_location("check_shared", TOOLS / "check-shared-library.py")
CHECK = importlib.util.module_from_spec(CHECK_SPEC)
CHECK_SPEC.loader.exec_module(CHECK)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.source = self.root / "libraries"
        for arch, machine in (("x64", 62), ("arm64", 183)):
            path = self.source / f"linux-{arch}" / "libTrustWalletCore.so"
            path.parent.mkdir(parents=True)
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            header[16:18] = (3).to_bytes(2, "little")
            header[18:20] = machine.to_bytes(2, "little")
            path.write_bytes(header)
        self.destination = self.root / "Linux.tar.gz"

    def test_layout_and_reproducibility(self):
        (self.source / "unrelated.txt").write_text("must not be published")
        MODULE.package(self.source, self.destination)
        with tarfile.open(self.destination) as archive:
            self.assertEqual(archive.getnames(), ["linux-x64/libTrustWalletCore.so",
                                                 "linux-arm64/libTrustWalletCore.so"])
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid, member.mtime, member.mode), (0, 0, 0, 0o644))
        second = self.root / "second.tar.gz"
        MODULE.package(self.source, second)
        self.assertEqual(self.destination.read_bytes(), second.read_bytes())

    def test_missing_architecture_does_not_create_archive(self):
        (self.source / "linux-arm64/libTrustWalletCore.so").unlink()
        with self.assertRaises(ValueError):
            MODULE.package(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_wrong_architecture_does_not_create_archive(self):
        arm = self.source / "linux-arm64/libTrustWalletCore.so"
        arm.write_bytes((self.source / "linux-x64/libTrustWalletCore.so").read_bytes())
        with self.assertRaises(ValueError):
            MODULE.package(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_reject_static_archive(self):
        (self.source / "linux-x64/libTrustWalletCore.so").write_bytes(b"!<arch>\n")
        with self.assertRaises(ValueError):
            MODULE.package(self.source, self.destination)

    def test_reject_symlink(self):
        arm = self.source / "linux-arm64/libTrustWalletCore.so"
        saved = self.root / "saved.so"
        arm.rename(saved)
        arm.symlink_to(saved)
        with self.assertRaises(ValueError):
            MODULE.package(self.source, self.destination)

    def test_never_overwrite(self):
        self.destination.write_bytes(b"existing asset")
        with self.assertRaises(FileExistsError):
            MODULE.package(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"existing asset")


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.library = pathlib.Path(self.temporary.name) / 'libTrustWalletCore.so'
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        header[16:18] = (3).to_bytes(2, 'little')
        header[18:20] = (62).to_bytes(2, 'little')
        self.library.write_bytes(header)
        self.dynamic = '(SONAME) Library soname: [libTrustWalletCore.so]\n(NEEDED) Shared library: [libc.so.6]'
        self.versions = 'GLIBC_2.17 GLIBC_2.34 GLIBCXX_3.4.29'
        self.dependencies = 'libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6'

    def check(self):
        with mock.patch.object(CHECK, 'output', side_effect=[self.dynamic, self.versions, self.dependencies]):
            CHECK.check_elf(self.library, 'x64')

    def test_accept_exact_baseline(self):
        self.check()

    def test_reject_glibc_above_baseline(self):
        self.versions += ' GLIBC_2.35'
        with self.assertRaisesRegex(SystemExit, 'GLIBC requirement exceeds'):
            self.check()

    def test_reject_glibcxx_above_baseline(self):
        self.versions += ' GLIBCXX_3.4.30'
        with self.assertRaisesRegex(SystemExit, 'GLIBCXX requirement exceeds'):
            self.check()

    def test_reject_private_glibc(self):
        self.versions += ' GLIBC_PRIVATE'
        with self.assertRaisesRegex(SystemExit, 'private or extended'):
            self.check()

    def test_reject_rpath(self):
        self.dynamic += '\n(RUNPATH) Library runpath: [/tmp/build]'
        with self.assertRaisesRegex(SystemExit, 'runtime search path'):
            self.check()

    def test_reject_unexpected_dependency(self):
        self.dynamic += '\n(NEEDED) Shared library: [libprotobuf.so.32]'
        with self.assertRaisesRegex(SystemExit, 'Unexpected runtime dependencies'):
            self.check()

    def test_reject_missing_dependency(self):
        self.dependencies = 'libc.so.6 => not found'
        with self.assertRaisesRegex(SystemExit, 'not found'):
            self.check()

    def test_reject_wrong_machine(self):
        with self.assertRaisesRegex(SystemExit, 'Wrong ELF architecture'):
            CHECK.check_elf(self.library, 'arm64')


class ReleaseTagTests(unittest.TestCase):
    platform = 'linux'

    def parse(self, *args):
        return subprocess.run(['bash', str(TOOLS / 'shared-release-tag'), self.platform, *args],
                              text=True, capture_output=True, check=False)

    def test_initial_and_retry_tags(self):
        for tag in (f'4.8.1-{self.platform}', f'4.8.1-{self.platform}-r1', f'4.8.1-{self.platform}-r20'):
            with self.subTest(tag=tag):
                result = self.parse(tag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '4.8.1')

    def test_reject_invalid_tags(self):
        for args in ((), ('',), ('master-SHARED',), ('4.8.1',), ('4.8.1-rc1-linux',),
                     ('4.8.1-linux-r0',), ('4.8.1-linux-r01',), ('4.8.1-linux-r1-extra',),
                     ('refs/tags/4.8.1-linux',), ('4.8.1-linux\necho bad',),
                     ('4.8.1-linux', 'extra')):
            with self.subTest(args=args):
                self.assertNotEqual(self.parse(*(arg.replace('-linux', f'-{self.platform}')
                                                for arg in args)).returncode, 0)

    def test_reject_other_platform_tags(self):
        for platform in ('linux', 'windows', 'macos'):
            if platform != self.platform:
                with self.subTest(platform=platform):
                    self.assertNotEqual(self.parse(f'4.9.3-{platform}').returncode, 0)

    def test_reject_unknown_platform(self):
        result = subprocess.run(['bash', str(TOOLS / 'shared-release-tag'),
                                 'darwin', '4.9.3-darwin'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


class SourceCheckTests(unittest.TestCase):
    """Run the real gate and fetches against separate local native/upstream remotes."""
    platform = 'linux'
    version = '4.9.3'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        self.native_remote = self.root / 'native.git'
        self.upstream_remote = self.root / 'upstream.git'
        for remote in (self.native_remote, self.upstream_remote):
            self.git('init', '-q', '--bare', str(remote))
        self.git('init', '-q')
        self.git('config', 'user.name', 'Source test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('remote', 'add', 'origin', str(self.native_remote))
        # Keep the script's official URL, but let Git itself route it offline.
        self.git('config', f'url.{self.upstream_remote}.insteadOf',
                 'https://github.com/trustwallet/wallet-core.git')
        self.base = self.commit('root')
        self.upstream = self.commit('official version')
        self.wasi = self.commit('WASI customization')
        self.git('tag', self.version, self.wasi)
        self.git('push', '-q', str(self.upstream_remote),
                 f'{self.upstream}:refs/tags/{self.version}')
        self.git('checkout', '-q', '--detach', self.upstream)
        self.shared = self.commit('native customization')
        self.native_head = self.commit('later native change')
        self.set_native_branch(self.native_head)
        self.git('checkout', '-q', '--detach', self.shared)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True,
                                       stderr=subprocess.PIPE).strip()

    def commit(self, message):
        self.git('commit', '-qm', message, '--allow-empty')
        return self.git('rev-parse', 'HEAD')

    def set_native_branch(self, commit):
        self.git('push', '-q', '--force', 'origin', f'{commit}:refs/heads/master-SHARED')

    def source_check(self, succeeds, *, pin=None):
        destination = self.root / f'output-{len(list(self.root.glob("output-*")))}'
        environment = dict(os.environ, BUILD_TAG=f'{self.version}-{self.platform}',
                           WASM_SOURCE_COMMIT=self.wasi if pin is None else pin,
                           GITHUB_OUTPUT=str(destination))
        result = subprocess.run(['bash', str(TOOLS / 'shared-release-source'), self.platform],
                                cwd=self.repo, env=environment, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, succeeds, result.stderr)
        self.assertEqual(destination.exists(), succeeds,
                         'A failed source check must not emit a release tag')
        if succeeds:
            self.assertEqual(destination.read_text(), f'release_tag={self.version}\n')
        return result

    def test_native_branch_can_advance_after_build_tag(self):
        self.source_check(True)
        # The upstream fetch must not replace the fork's WASI tag.
        self.assertEqual(self.git('rev-parse', f'refs/tags/{self.version}'), self.wasi)

    def test_build_at_native_branch_head(self):
        self.git('checkout', '-q', '--detach', self.native_head)
        self.source_check(True)

    def test_reject_build_not_integrated_into_native_branch(self):
        self.git('checkout', '-q', '--detach', self.wasi)
        self.source_check(False)

    def test_reject_missing_native_branch(self):
        self.git('--git-dir', str(self.native_remote), 'update-ref', '-d',
                 'refs/heads/master-SHARED')
        self.source_check(False)

    def test_reject_build_without_official_ancestor(self):
        self.set_native_branch(self.base)
        self.git('checkout', '-q', '--detach', self.base)
        self.source_check(False)

    def test_reject_wasi_without_official_ancestor(self):
        self.git('tag', '-f', self.version, self.base)
        self.source_check(False, pin=self.base)

    def test_reject_wrong_official_commit(self):
        self.git('push', '-q', '--force', str(self.upstream_remote),
                 f'{self.wasi}:refs/tags/{self.version}')
        self.source_check(False)

    def test_reject_missing_official_tag(self):
        self.git('--git-dir', str(self.upstream_remote), 'update-ref', '-d',
                 f'refs/tags/{self.version}')
        self.source_check(False)

    def test_reject_missing_fork_tag(self):
        self.git('tag', '-d', self.version)
        self.source_check(False)

    def test_reject_mismatched_source_pin(self):
        self.source_check(False, pin=self.shared)

    def test_missing_or_invalid_source_pin_fails_closed(self):
        for pin in ('', self.wasi[:-1], self.wasi.upper()):
            with self.subTest(pin=pin):
                result = self.source_check(False, pin=pin)
                self.assertIn('Set WASM_SOURCE_COMMIT', result.stderr)


class ReleaseLookupTests(unittest.TestCase):
    """Execute the workflow's actual inline lookup with gh replaced by a fixture."""
    workflow_name = 'linux-release.yml'
    asset_name = 'Linux.tar.gz'
    allow_published = True

    def lookup(self, pages, succeeds, *, fail_api=False, raw_json=None):
        workflow = (TOOLS.parent / '.github/workflows' / self.workflow_name).read_text()
        match = re.search(r'(?ms)^ +# BEGIN RELEASE LOOKUP[^\n]*\n(.*?)^ +# END RELEASE LOOKUP', workflow)
        self.assertIsNotNone(match)
        script = textwrap.dedent(match.group(1))
        stub = '''
gh() {
  [[ "$*" == 'api --paginate --slurp repos/test/wallet-core/releases?per_page=100' ]] || return 97
  [[ "$FAIL_API" == 0 ]] || return 22
  printf '%s' "$TEST_RELEASES"
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            destination = pathlib.Path(temporary) / 'github-output'
            environment = dict(os.environ, GH_REPO='test/wallet-core', RELEASE_TAG='4.8.1',
                               GITHUB_OUTPUT=str(destination), FAIL_API=str(int(fail_api)),
                               TEST_RELEASES=raw_json if raw_json is not None else json.dumps(pages))
            result = subprocess.run(['bash', '-c', stub + script], env=environment,
                                    text=True, capture_output=True, check=False)
            if succeeds:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(destination.read_text(), 'release_id=123\n')
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(destination.exists(), 'Failure must not emit a release ID')

    @staticmethod
    def release(**changes):
        return dict(dict(id=123, tag_name='4.8.1', draft=True, immutable=False, assets=[]), **changes)

    def test_find_draft_on_later_page(self):
        self.lookup([[self.release(tag_name='4.8.0')], [self.release()]], True)

    def test_published_release(self):
        self.lookup([[self.release(draft=False)]], self.allow_published)

    def test_missing_release(self):
        self.lookup([[self.release(tag_name='4.8.0')]], False)

    def test_ambiguous_release(self):
        self.lookup([[self.release()], [self.release(id=456)]], False)

    def test_immutable_release(self):
        self.lookup([[self.release(immutable=True)]], False)

    def test_existing_asset(self):
        self.lookup([[self.release(assets=[{'name': self.asset_name}])]], False)

    def test_api_error_is_not_treated_as_missing_release(self):
        self.lookup([], False, fail_api=True)

    def test_invalid_json(self):
        self.lookup([], False, raw_json='not JSON')

    def test_invalid_release_id(self):
        self.lookup([[self.release(id=0)]], False)


if __name__ == "__main__":
    unittest.main()
