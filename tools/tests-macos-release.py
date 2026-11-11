"""Offline release guards and malformed package tests; no synthetic native PASS."""

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile

TOOLS = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PACKAGE = module('package_macos', 'package-macos-release.py')
LINUX = module('tests_linux_release', 'tests-linux-release.py')


class ReleaseTagTests(LINUX.ReleaseTagTests):
    platform = 'macos'


class SourceCheckTests(LINUX.SourceCheckTests):
    platform = 'macos'


class ReleaseLookupTests(LINUX.ReleaseLookupTests):
    workflow_name = 'macos-release.yml'
    asset_name = PACKAGE.ASSET
    allow_published = False


class BinaryTests(unittest.TestCase):
    def check(self, *, arch='arm64', exports='_TWTest\n', build='platform MACOS\nminos 12.0\n', deps=None):
        if deps is None:
            deps = f'test:\n\t{PACKAGE.INSTALL_NAME} (version)\n\t/usr/lib/libSystem.B.dylib (version)\n'
        with mock.patch.object(PACKAGE, 'run', side_effect=[arch, exports, build, deps]):
            return PACKAGE.check_binary(Path('library'), ['arm64'], ['TWTest'])

    def test_expected_metadata(self):
        self.assertEqual(self.check()['arm64']['public_c_exports'], 1)

    def test_reject_wrong_arch_exports_minimum_platform_dependency_and_id(self):
        for options in (dict(arch='x86_64'), dict(exports='_Other\n'), dict(build='platform MACOS\nminos 15.0\n'),
                        dict(build='platform IOS\nminos 12.0\n'), dict(build='platform MACOS\nminos 12.0.1\n'),
                        dict(deps=f'test:\n\t{PACKAGE.INSTALL_NAME} (version)\n\t/opt/homebrew/lib/libprotobuf.dylib (version)\n'),
                        dict(deps='test:\n\t@rpath/other.dylib (version)\n')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.check(**options)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        (self.source / 'Versions/A').mkdir(parents=True)
        (self.source / 'Versions/A/binary').write_bytes(b'verified native binary')
        (self.source / 'Versions/A/binary').chmod(0o755)
        (self.source / 'Versions/Current').symlink_to('A')
        (self.source / 'binary').symlink_to('Versions/Current/binary')
        self.archive = self.root / 'release.zip'

    def test_reproducible_zip_preserves_bytes_modes_and_versioned_symlinks(self):
        PACKAGE.write_zip(self.source, self.archive)
        second = self.root / 'second.zip'
        PACKAGE.write_zip(self.source, second)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())
        relocated = self.root / 'round trip'
        PACKAGE.extract_zip(self.archive, relocated)
        self.assertEqual(PACKAGE.files(self.source), PACKAGE.files(relocated))
        self.assertEqual(stat.S_IMODE((relocated / 'binary').stat().st_mode), 0o755)

    def test_archive_never_overwrites(self):
        self.archive.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            PACKAGE.write_zip(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), b'existing')

    def test_reject_external_or_broken_source_symlink(self):
        for target in ('/etc/passwd', '../outside', 'missing'):
            path = self.source / 'unsafe'
            path.symlink_to(target)
            with self.subTest(target=target), self.assertRaises(ValueError):
                PACKAGE.write_zip(self.source, self.archive)
            self.assertFalse(self.archive.exists())
            path.unlink()

    def test_reject_unsafe_zip_before_writing(self):
        for entries in ([('../escape', 'data', stat.S_IFREG)], [('/absolute', 'data', stat.S_IFREG)],
                        [('a\\b', 'data', stat.S_IFREG)], [('a/./b', 'data', stat.S_IFREG)], [('link', '/etc/passwd', stat.S_IFLNK)],
                        [('link', '../escape', stat.S_IFLNK)], [('same', 'a', stat.S_IFREG), ('same', 'b', stat.S_IFREG)],
                        [('parent', 'data', stat.S_IFREG), ('parent/child', 'data', stat.S_IFREG)]):
            with self.subTest(entries=entries):
                archive = self.root / 'unsafe.zip'
                with zipfile.ZipFile(archive, 'w') as stream:
                    for name, content, kind in entries:
                        info = zipfile.ZipInfo(name)
                        info.external_attr = (kind | 0o644) << 16
                        stream.writestr(info, content)
                output = self.root / 'output'
                with self.assertRaises(ValueError):
                    PACKAGE.extract_zip(archive, output)
                self.assertFalse(output.exists())


class SliceTests(unittest.TestCase):
    def test_reject_metadata_architecture_api_and_headers_mismatch_before_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arm, intel = root / 'arm', root / 'intel'
            names = '\n'.join(f'TWFunction{i}' for i in range(466)) + '\n'
            for arch, directory in (('arm64', arm), ('x86_64', intel)):
                (directory / PACKAGE.FRAMEWORK / 'Headers').mkdir(parents=True)
                (directory / PACKAGE.FRAMEWORK / 'Modules').mkdir()
                (directory / 'licenses').mkdir()
                (directory / PACKAGE.FRAMEWORK / 'Headers/header.h').write_text('same')
                (directory / 'public-api.txt').write_text(names)
                (directory / 'manifest.json').write_text(json.dumps(dict(version='4.9.3', source_commit='a'*40,
                    wasi_source_commit='b'*40, architecture=arch, runtime=dict(host_architecture=arch, executed_architecture=arch))))
            original = (intel / 'manifest.json').read_text()
            for key, value in (('version', '4.9.2'), ('source_commit', 'c'*40), ('wasi_source_commit', 'd'*40),
                               ('architecture', 'arm64'), ('runtime', dict(host_architecture='arm64', executed_architecture='arm64'))):
                changes = json.loads(original)
                changes[key] = value
                (intel / 'manifest.json').write_text(json.dumps(changes))
                with self.subTest(key=key), mock.patch.object(PACKAGE, 'check_framework'), self.assertRaises(ValueError):
                    PACKAGE.package(arm, intel, root / 'output')
                self.assertFalse((root / 'output').exists())
            (intel / 'manifest.json').write_text(original)
            (intel / PACKAGE.FRAMEWORK / 'Headers/header.h').write_text('wrong')
            with mock.patch.object(PACKAGE, 'check_framework'), self.assertRaisesRegex(ValueError, 'Headers mismatch'):
                PACKAGE.package(arm, intel, root / 'output')
            (intel / 'public-api.txt').write_text('TWIncomplete\n')
            with self.assertRaisesRegex(ValueError, 'public API mismatch'):
                PACKAGE.package(arm, intel, root / 'output')
            (root / 'output').mkdir()
            with self.assertRaises(FileExistsError):
                PACKAGE.package(arm, intel, root / 'output')


class UploadTests(unittest.TestCase):
    def test_actual_upload_script_is_bound_to_release_id_and_verifies_sha_size(self):
        workflow = (TOOLS.parent / '.github/workflows/macos-release.yml').read_text()
        script = textwrap.dedent(re.search(r'(?ms)^ +# BEGIN RELEASE UPLOAD[^\n]*\n(.*?)^ +# END RELEASE UPLOAD', workflow).group(1))
        stub = '''
gh() {
  if [[ "$*" == "api repos/test/wallet-core/releases/123" ]]; then
    if [[ -f "$POSTED" ]]; then printf '%s' "$AFTER"; else printf '%s' "$BEFORE"; fi
  elif [[ "$*" == 'api --method POST https://uploads.github.com/repos/test/wallet-core/releases/123/assets?name=TrustWalletCore-macos.xcframework.zip -H Content-Type: application/zip --input downloads/TrustWalletCore-macos.xcframework.zip' ]]; then
    touch "$POSTED"
  else return 97; fi
}
'''
        before = dict(id=123, tag_name='4.9.3', draft=True, immutable=False, assets=[])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'downloads').mkdir()
            asset = root / 'downloads' / PACKAGE.ASSET
            asset.write_bytes(b'validated package')
            after = dict(before, assets=[dict(name=PACKAGE.ASSET, state='uploaded', size=asset.stat().st_size,
                                              digest='sha256:' + PACKAGE.digest(asset))])
            cases = [(before, after, True, True)]
            cases += [(dict(before, **change), after, False, False) for change in
                      (dict(id=999), dict(tag_name='4.9.2'), dict(draft=False), dict(immutable=True),
                       dict(assets=[dict(name=PACKAGE.ASSET)]))]
            cases += [(before, dict(after, **change), False, True) for change in
                      (dict(id=999), dict(draft=False), dict(assets=[dict(after['assets'][0], size=1)]),
                       dict(assets=[dict(after['assets'][0], digest='sha256:wrong')]))]
            for initial, final, succeeds, posted in cases:
                marker = root / 'posted'
                marker.unlink(missing_ok=True)
                env = dict(os.environ, BEFORE=json.dumps(initial), AFTER=json.dumps(final), POSTED=str(marker),
                           GH_REPO='test/wallet-core', RELEASE_TAG='4.9.3', RELEASE_ID='123', GITHUB_STEP_SUMMARY=str(root / 'summary'))
                # macOS stat differs from the Linux publisher; stub only the size utility.
                command = stub + '\nstat() { command wc -c < "$3" | tr -d " "; }\n' + script
                result = subprocess.run(['bash', '-c', command], cwd=root, env=env, text=True, capture_output=True)
                with self.subTest(initial=initial, final=final):
                    self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                    self.assertEqual(marker.exists(), posted)


if __name__ == '__main__':
    unittest.main()
