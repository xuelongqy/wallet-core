"""Offline release guards and packaging tests; synthetic PE bytes are not runnable."""

import importlib.util
import pathlib
import tarfile
import tempfile
import unittest


TOOLS = pathlib.Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PACKAGE = module('package_windows', 'package-windows-release.py')
LINUX = module('tests_linux_release', 'tests-linux-release.py')


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.source = self.root / 'sdk'
        self.dll = self.source / 'shared/bin/TrustWalletCore.dll'
        self.dll.parent.mkdir(parents=True)
        image = bytearray(256)
        image[:2] = b'MZ'
        image[0x3c:0x40] = (128).to_bytes(4, 'little')
        image[128:132] = b'PE\0\0'
        image[132:134] = (0x8664).to_bytes(2, 'little')
        image[150:152] = (0x2000).to_bytes(2, 'little')
        image[152:154] = (0x20b).to_bytes(2, 'little')
        self.dll.write_bytes(image)
        (self.source / 'licenses').mkdir()
        for name in PACKAGE.LICENSES:
            (self.source / 'licenses' / name).write_text(name)
        self.destination = self.root / 'Windows.tar.gz'

    def test_layout_alias_bytes_and_reproducibility(self):
        (self.source / 'unrelated.txt').write_text('must not be published')
        PACKAGE.package(self.source, self.destination)
        with tarfile.open(self.destination) as archive:
            self.assertEqual(archive.getnames(), ['windows-x64/libTrustWalletCore.dll',
                                                 'windows-x64/README.md'] +
                             [f'windows-x64/licenses/{name}' for name in PACKAGE.LICENSES])
            self.assertEqual(archive.extractfile('windows-x64/libTrustWalletCore.dll').read(),
                             self.dll.read_bytes())
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid, member.mtime, member.mode), (0, 0, 0, 0o644))
        second = self.root / 'second.tar.gz'
        PACKAGE.package(self.source, second)
        self.assertEqual(self.destination.read_bytes(), second.read_bytes())

    def test_missing_input_does_not_create_archive(self):
        for relative in ('shared/bin/TrustWalletCore.dll', 'licenses/WalletCore-3rd-party.txt'):
            with self.subTest(relative=relative):
                path = self.source / relative
                content = path.read_bytes()
                path.unlink()
                with self.assertRaises(ValueError):
                    PACKAGE.package(self.source, self.destination)
                self.assertFalse(self.destination.exists())
                path.write_bytes(content)

    def test_reject_wrong_pe_architecture_type_and_truncation(self):
        valid = self.dll.read_bytes()
        for offset, replacement in ((132, b'\x64\xaa'), (150, b'\0\0'), (152, b'\x0b\x01'),
                                    (128, b'bad!'), (0, b'bad')):
            with self.subTest(offset=offset):
                image = bytearray(valid)
                image[offset:offset + len(replacement)] = replacement
                self.dll.write_bytes(image)
                with self.assertRaises(ValueError):
                    PACKAGE.package(self.source, self.destination)
                self.assertFalse(self.destination.exists())
        self.dll.write_bytes(b'MZ')
        with self.assertRaises(ValueError):
            PACKAGE.package(self.source, self.destination)

    def test_reject_file_and_directory_symlinks(self):
        saved = self.root / 'saved.dll'
        self.dll.rename(saved)
        self.dll.symlink_to(saved)
        with self.assertRaises(ValueError):
            PACKAGE.package(self.source, self.destination)
        self.dll.unlink()
        saved.rename(self.dll)
        shared = self.source / 'shared'
        directory = self.root / 'shared'
        shared.rename(directory)
        shared.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            PACKAGE.package(self.source, self.destination)

    def test_never_overwrite(self):
        self.destination.write_bytes(b'existing asset')
        with self.assertRaises(FileExistsError):
            PACKAGE.package(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'existing asset')


class ReleaseLookupTests(LINUX.ReleaseLookupTests):
    workflow_name = 'windows-release.yml'
    asset_name = 'Windows.tar.gz'
    allow_published = False


class SourceCheckTests(LINUX.SourceCheckTests):
    platform = 'windows'


class ReleaseTagTests(LINUX.ReleaseTagTests):
    platform = 'windows'


if __name__ == '__main__':
    unittest.main()
