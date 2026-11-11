#!/usr/bin/env python3
"""Build and check the C-only macOS frameworks; never replace an existing output."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ASSET = 'TrustWalletCore-macos.xcframework.zip'
FRAMEWORK = 'TrustWalletCore.framework'
INSTALL_NAME = '@rpath/TrustWalletCore.framework/Versions/A/TrustWalletCore'
LICENSES = ('WalletCore.txt', 'WalletCore-3rd-party.txt', 'Protobuf.txt', 'Boost.txt', 'TrezorCrypto.txt', 'rust-dependencies.json',
            'rust-stdlib/COPYRIGHT-library.html')
ENV = {key: value for key, value in os.environ.items() if not key.startswith('DYLD_')}


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True, stderr=subprocess.STDOUT, env=ENV)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_binary(binary, architectures, names, install_name=INSTALL_NAME):
    if set(run('lipo', '-archs', binary).split()) != set(architectures):
        raise ValueError(f'Wrong architectures: {binary}')
    result = {}
    for arch in architectures:
        exports = {line.removeprefix('_') for line in run('nm', '-arch', arch, '-gUj', binary).splitlines()}
        if not set(names) <= exports:
            raise ValueError(f'Missing public C exports ({arch}): {sorted(set(names) - exports)}')
        build = run('xcrun', 'vtool', '-arch', arch, '-show-build', binary)
        if re.findall(r'\bplatform\s+(\S+)', build) != ['MACOS'] or re.findall(r'\bminos\s+(\S+)', build) != ['12.0']:
            raise ValueError(f'Expected macOS minimum 12.0 ({arch}): {build}')
        deps = run('otool', '-arch', arch, '-L', binary)
        libraries = [line.strip().split(' (')[0] for line in deps.splitlines() if line.startswith('\t')]
        if not libraries or libraries[0] != install_name or any(
                not name.startswith(('/usr/lib/', '/System/Library/')) for name in libraries[1:]):
            raise ValueError(f'Unexpected install name or runtime dependency ({arch}): {deps}')
        result[arch] = dict(public_c_exports=len(names), all_global_exports=len(exports),
                            build=build, dependencies=libraries)
    return result


def files(directory):
    return {str(path.relative_to(directory)): ('symlink', os.readlink(path)) if path.is_symlink()
            else ('file', digest(path)) for path in sorted(directory.rglob('*'))
            if path.is_symlink() or path.is_file()}


def check_links(directory):
    for path in directory.rglob('*'):
        if path.is_symlink():
            target = path.readlink()
            if target.is_absolute() or not path.resolve().is_relative_to(directory.resolve()) or not path.exists():
                raise ValueError(f'Unsafe or broken symlink: {path} -> {target}')
        elif not path.is_file() and not path.is_dir():
            raise ValueError(f'Unsupported file: {path}')


def check_framework(framework, architectures, names, version):
    check_links(framework)
    if (framework / 'Versions/Current').readlink() != Path('A'):
        raise ValueError('Invalid framework Current symlink')
    for name in ('Headers', 'Modules', 'Resources', 'TrustWalletCore'):
        if (framework / name).readlink() != Path('Versions/Current') / name:
            raise ValueError(f'Invalid framework {name} symlink')
    with (framework / 'Resources/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if any(info.get(key) != value for key, value in {
            'CFBundleExecutable': 'TrustWalletCore', 'CFBundlePackageType': 'FMWK',
            'CFBundleShortVersionString': version, 'CFBundleVersion': version,
            'LSMinimumSystemVersion': '12.0', 'MinimumOSVersion': '12.0'}.items()):
        raise ValueError('Wrong framework version or minimum OS metadata')
    run('codesign', '--verify', '--deep', '--strict', framework)
    return check_binary(framework / 'TrustWalletCore', architectures, names)


def consumers(xcframework, names, work, architecture=None):
    """The build driver requires a native host; explicit slice checks can use Rosetta locally."""
    arch = architecture or platform.machine()
    slice_dir = xcframework / 'macos-arm64_x86_64'
    if not slice_dir.exists():
        slice_dir, = [path for path in xcframework.iterdir() if path.is_dir()]
    framework = slice_dir / FRAMEWORK
    (work / 'public-api-names.h').write_text('static const char *public_api[] = {\n' +
                                           ''.join(json.dumps(name) + ',\n' for name in names) + '};\n')
    native = work / 'native-consumer'
    run('xcrun', 'clang', '-arch', arch, '-mmacosx-version-min=12.0', '-I', work,
        '-F', slice_dir, '-framework', 'TrustWalletCore', f'-Wl,-rpath,{slice_dir}',
        ROOT / 'tests/macos/consumer.c', '-o', native)
    native_result = run(native, framework / 'TrustWalletCore')
    package = work / 'swiftpm'
    shutil.copytree(ROOT / 'tests/macos/swiftpm', package)
    shutil.copytree(xcframework, package / 'TrustWalletCore.xcframework', symlinks=True)
    command = ['swift', 'build', '--package-path', package, '-c', 'release', '--arch', arch,
               '-Xlinker', '-rpath', '-Xlinker', '@executable_path/Frameworks']
    run(*command)
    bin_dir = Path(run(*command, '--show-bin-path').strip())
    embedded = bin_dir / 'Frameworks'
    embedded.mkdir()
    shutil.copytree(framework, embedded / FRAMEWORK, symlinks=True)
    swift_result = run(bin_dir / 'consumer')
    return dict(host_architecture=platform.machine(), executed_architecture=arch,
                native=native_result.strip(), swiftpm=swift_result.strip())


def make_framework(libraries, headers, destination, version):
    a = destination / 'Versions/A'
    (a / 'Resources').mkdir(parents=True)
    shutil.copytree(headers, a / 'Headers')
    if (a / 'Headers/TrustWalletCore.h').exists():
        raise ValueError('Input headers must not include the generated umbrella header')
    names = sorted(path.name for path in (a / 'Headers').glob('*.h'))
    if not names:
        raise ValueError('No public headers')
    (a / 'Headers/TrustWalletCore.h').write_text('#pragma once\n' + ''.join(f'#include "{name}"\n' for name in names))
    (a / 'Modules').mkdir()
    (a / 'Modules/module.modulemap').write_text(
        'framework module TrustWalletCore {\n  umbrella header "TrustWalletCore.h"\n  export *\n  module * { export * }\n}\n')
    with (a / 'Resources/Info.plist').open('wb') as stream:
        plistlib.dump(dict(CFBundleDevelopmentRegion='en', CFBundleExecutable='TrustWalletCore',
                          CFBundleIdentifier='com.trustwallet.wallet-core.c', CFBundleInfoDictionaryVersion='6.0',
                          CFBundleName='TrustWalletCore', CFBundlePackageType='FMWK',
                          CFBundleShortVersionString=version, CFBundleVersion=version,
                          CFBundleSupportedPlatforms=['MacOSX'], LSMinimumSystemVersion='12.0',
                          MinimumOSVersion='12.0'), stream, sort_keys=True)
    (destination / 'Versions/Current').symlink_to('A')
    for name in ('Headers', 'Modules', 'Resources', 'TrustWalletCore'):
        (destination / name).symlink_to('Versions/Current/' + name)
    run('lipo', '-create', *libraries, '-output', a / 'TrustWalletCore')
    run('install_name_tool', '-id', INSTALL_NAME, a / 'TrustWalletCore')
    run('codesign', '--force', '--sign', '-', '--timestamp=none', destination)


def write_zip(source, destination):
    check_links(source)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_dir() and not path.is_symlink():
                continue
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((stat.S_IFLNK | 0o777) if path.is_symlink() else
                                  (stat.S_IFREG | (0o755 if os.access(path, os.X_OK) else 0o644))) << 16
            archive.writestr(info, os.fsencode(path.readlink()) if path.is_symlink() else path.read_bytes())


def extract_zip(archive_path, destination):
    """Validate the entire ZIP before writing, then create symlinks last."""
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = {entry.filename for entry in entries}
        if len(names) != len(entries):
            raise ValueError('Duplicate ZIP entries')
        links = {}
        for entry in entries:
            path = PurePosixPath(entry.filename)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if path.is_absolute() or path.as_posix() != entry.filename or '..' in path.parts or '\\' in entry.filename or not path.parts or kind not in (stat.S_IFREG, stat.S_IFLNK):
                raise ValueError(f'Unsafe ZIP entry: {entry.filename}')
            if kind == stat.S_IFLNK:
                target = PurePosixPath(archive.read(entry).decode())
                if target.is_absolute() or '..' in target.parts or '\\' in str(target):
                    raise ValueError(f'Unsafe ZIP symlink: {entry.filename}')
                links[entry.filename] = target
        for name in names:
            if any(parent.as_posix() in names for parent in PurePosixPath(name).parents if parent != PurePosixPath('.')):
                raise ValueError(f'ZIP file used as parent: {name}')
        destination.mkdir()
        for entry in entries:
            path = destination / entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.filename not in links:
                path.write_bytes(archive.read(entry))
                path.chmod(stat.S_IMODE(entry.external_attr >> 16))
        for name, target in links.items():
            (destination / name).symlink_to(str(target))
    check_links(destination)


def slice_package(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        raise ValueError('Expected a plain release version')
    for commit in (args.source_commit, args.wasi_source_commit):
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Expected exact source commit SHAs')
    names = [line.strip() for line in args.exports.read_text().splitlines()[2:] if line.strip()]
    if len(names) != len(set(names)) or len(names) < 466:
        raise ValueError('Incomplete public C API list')
    check_links(args.headers)
    check_binary(args.library, [args.arch], names, '@rpath/libTrustWalletCore.dylib')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        work = Path(temporary)
        stage = work / 'slice'
        stage.mkdir()
        framework = stage / FRAMEWORK
        make_framework([args.library], args.headers, framework, args.version)
        metadata = dict(version=args.version, source_commit=args.source_commit,
                        wasi_source_commit=args.wasi_source_commit, architecture=args.arch,
                        binary=check_framework(framework, [args.arch], names, args.version))
        (stage / 'public-api.txt').write_text('\n'.join(names) + '\n')
        shutil.copytree(args.licenses, stage / 'licenses')
        for name in LICENSES:
            if not (stage / 'licenses' / name).is_file():
                raise ValueError(f'Missing license: {name}')
        xc = work / 'TrustWalletCore.xcframework'
        run('xcodebuild', '-create-xcframework', '-framework', framework, '-output', xc)
        metadata['runtime'] = consumers(xc, names, work, args.arch)
        metadata['tools'] = {tool: run(*command).strip() for tool, command in {
            'xcode': ('xcodebuild', '-version'), 'clang': ('xcrun', 'clang', '--version'),
            'sdk': ('xcrun', '--show-sdk-version'), 'swift': ('swift', '--version'),
            'rust': ('rustc', '--version'), 'cmake': ('cmake', '--version')}.items()}
        (stage / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        stage.rename(args.output)
    print(args.output)


def package(arm64, x86_64, output):
    if output.exists():
        raise FileExistsError(output)
    manifests = [json.loads((source / 'manifest.json').read_text()) for source in (arm64, x86_64)]
    for source in (arm64, x86_64):
        check_links(source)
    for key in ('version', 'source_commit', 'wasi_source_commit'):
        if manifests[0][key] != manifests[1][key]:
            raise ValueError(f'Slice {key} mismatch')
    version = manifests[0]['version']
    names = (arm64 / 'public-api.txt').read_text().splitlines()
    if (x86_64 / 'public-api.txt').read_text().splitlines() != names or len(names) < 466:
        raise ValueError('Slice public API mismatch')
    for arch, source, manifest in zip(('arm64', 'x86_64'), (arm64, x86_64), manifests):
        if manifest['architecture'] != arch or manifest['runtime']['executed_architecture'] != arch:
            raise ValueError('Wrong slice architecture or native runtime host')
        check_framework(source / FRAMEWORK, [arch], names, version)
    for folder in ('Headers', 'Modules', 'licenses'):
        first = arm64 / (FRAMEWORK + '/' if folder != 'licenses' else '') / folder
        second = x86_64 / (FRAMEWORK + '/' if folder != 'licenses' else '') / folder
        if files(first) != files(second):
            raise ValueError(f'Slice {folder} mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        payload = work / 'payload'
        payload.mkdir()
        framework = work / FRAMEWORK
        headers = work / 'headers'
        shutil.copytree(arm64 / FRAMEWORK / 'Headers', headers)
        (headers / 'TrustWalletCore.h').unlink()
        make_framework([source / FRAMEWORK / 'TrustWalletCore' for source in (arm64, x86_64)], headers, framework, version)
        xc = payload / 'TrustWalletCore.xcframework'
        run('xcodebuild', '-create-xcframework', '-framework', framework, '-output', xc)
        with (xc / 'Info.plist').open('rb') as stream:
            library, = plistlib.load(stream)['AvailableLibraries']
        expected = dict(LibraryIdentifier='macos-arm64_x86_64', LibraryPath=FRAMEWORK,
                        SupportedArchitectures=['arm64', 'x86_64'], SupportedPlatform='macos')
        if any(library.get(key) != value for key, value in expected.items()) or library.get(
                'BinaryPath', FRAMEWORK + '/Versions/A/TrustWalletCore') != FRAMEWORK + '/Versions/A/TrustWalletCore':
            raise ValueError(f'Unexpected XCFramework metadata: {library}')
        report = check_framework(xc / 'macos-arm64_x86_64' / FRAMEWORK, ['arm64', 'x86_64'], names, version)
        shutil.copytree(arm64 / 'licenses', payload / 'licenses')
        (payload / 'manifest.json').write_text(json.dumps(dict(slices=manifests, binary=report), indent=2) + '\n')
        stage = work / 'result'
        stage.mkdir()
        archive = stage / ASSET
        write_zip(payload, archive)
        relocated = work / 'round trip with spaces'
        extract_zip(archive, relocated)
        if files(payload) != files(relocated):
            raise ValueError('ZIP round trip changed the framework or licenses')
        check_framework(relocated / 'TrustWalletCore.xcframework/macos-arm64_x86_64' / FRAMEWORK,
                        ['arm64', 'x86_64'], names, version)
        report['runtime'] = consumers(relocated / 'TrustWalletCore.xcframework', names, work)
        checksum = run('swift', 'package', 'compute-checksum', archive).strip()
        if checksum != digest(archive):
            raise ValueError('SwiftPM and SHA256 checksum mismatch')
        (stage / (ASSET + '.sha256')).write_text(f'{checksum}  {ASSET}\n')
        (stage / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        stage.rename(output)
    print(output / ASSET)


def collect_licenses(boost, output):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    for name, source in {
            'WalletCore.txt': ROOT / 'LICENSE', 'WalletCore-3rd-party.txt': ROOT / 'LICENSE-3RD-PARTY.txt',
            'TrezorCrypto.txt': ROOT / 'trezor-crypto/crypto/LICENSE',
            'Protobuf.txt': ROOT / 'build/local/src/protobuf/protobuf-3.20.3/LICENSE',
            'Boost.txt': boost / 'LICENSE_1_0.txt'}.items():
        shutil.copyfile(source, output / name)
    metadata = json.loads(run('cargo', 'metadata', '--locked', '--format-version', '1',
                              '--manifest-path', ROOT / 'rust/Cargo.toml'))
    packages = {package['id']: package for package in metadata['packages']}
    nodes = {node['id']: node for node in metadata['resolve']['nodes']}
    root_id, = [key for key, package in packages.items() if package['name'] == 'wallet-core-rs']
    pending, seen = [root_id], set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        pending += [dep['pkg'] for dep in nodes[key]['deps']
                    if any(kind['kind'] != 'dev' for kind in dep['dep_kinds'])]
    inventory = []
    for package in sorted((packages[key] for key in seen), key=lambda item: (item['name'], item['version'])):
        source = Path(package['manifest_path']).parent
        candidates = {path for path in source.iterdir() if path.is_file() and
                      path.name.lower().startswith(('license', 'licence', 'copying', 'notice'))}
        if package['license_file']:
            candidates.add(source / package['license_file'])
        notices = []
        for path in sorted(candidates):
            destination = output / 'rust-crates' / (package['name'] + '-' + package['version']) / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            notices.append(destination.relative_to(output).as_posix())
        inventory.append(dict(name=package['name'], version=package['version'], license=package['license'],
                              source=package['source'] or 'WalletCore source tree', license_files=notices))
    (output / 'rust-dependencies.json').write_text(json.dumps(inventory, indent=2) + '\n')
    rust_doc = Path(run('rustc', '--print', 'sysroot').strip()) / 'share/doc/rust'
    (output / 'rust-stdlib').mkdir()
    shutil.copyfile(rust_doc / 'COPYRIGHT-library.html', output / 'rust-stdlib/COPYRIGHT-library.html')
    shutil.copytree(rust_doc / 'licenses', output / 'rust-stdlib/licenses')
    (output / 'README.txt').write_text(
        'WalletCore, bundled third-party, Protobuf, TrezorCrypto, and Boost notices are included.\n'
        'rust-dependencies.json records the conservative normal/build dependency closure from locked Cargo metadata.\n'
        'rust-crates preserves source-package notices; packages without standalone notices retain declared licenses.\n'
        'Workspace crates use the WalletCore source license. rust-stdlib contains compiler-provided library notices.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    thin = commands.add_parser('slice')
    for name in ('library', 'headers', 'licenses', 'exports', 'output'):
        thin.add_argument('--' + name, type=Path, required=True)
    thin.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    for name in ('version', 'source-commit', 'wasi-source-commit'):
        thin.add_argument('--' + name, required=True)
    licenses = commands.add_parser('licenses')
    licenses.add_argument('--boost', type=Path, required=True)
    licenses.add_argument('--output', type=Path, required=True)
    universal = commands.add_parser('package')
    universal.add_argument('arm64', type=Path)
    universal.add_argument('x86_64', type=Path)
    universal.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'slice':
        slice_package(args)
    elif args.command == 'licenses':
        collect_licenses(args.boost, args.output)
    else:
        package(args.arm64, args.x86_64, args.output)


if __name__ == '__main__':
    main()
