"""Run actual multi-target bindgen paths with Cargo replaced by a call recorder."""

import os
import pathlib
import subprocess
import tempfile
import unittest


TOOLS = pathlib.Path(__file__).resolve().parent
TARGETS = {
    'android': ('aarch64-linux-android', 'armv7-linux-androideabi',
                'x86_64-linux-android', 'i686-linux-android'),
    'ios': ('aarch64-apple-ios', 'aarch64-apple-ios-sim', 'x86_64-apple-ios',
            'aarch64-apple-darwin', 'x86_64-apple-darwin',
            'aarch64-apple-ios-macabi', 'x86_64-apple-ios-macabi'),
}


class PlatformTargetsTests(unittest.TestCase):
    def test_one_target_per_build_in_order_and_stop_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / 'rust/target/release').mkdir(parents=True)
            (root / 'rust/target/release/libwallet_core_rs.a').write_bytes(b'fixture')
            (root / 'build/local/lib').mkdir(parents=True)
            (root / 'codegen-v2').mkdir()
            ndk = root / 'ndk'
            ndk.mkdir()
            (ndk / 'aarch64-linux-android28-clang').touch()
            log = root / 'calls'
            environment_file = root / 'bash-env'
            environment_file.write_text('''
cargo() {
  printf '%s\n' "$*" >> "$BINDGEN_CALLS"
  if [[ "$1" == build && -n "$FAIL_TARGET" && " $* " == *" --target $FAIL_TARGET "* ]]; then
    return 37
  fi
}
cbindgen() { printf 'cbindgen\n' >> "$BINDGEN_CALLS"; }
uname() { printf 'Darwin\n'; }
xcodebuild() { :; }
lipo() {
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == -output ]]; then
      printf 'fixture' > "$2"
      return
    fi
    shift
  done
  return 1
}
''')
            for platform, targets in TARGETS.items():
                builds = [f'build --locked -Z build-std=std,panic_abort --target {target} --release --lib'
                          for target in targets]
                for failed in ('', *targets):
                    with self.subTest(platform=platform, failed_target=failed or 'none'):
                        log.unlink(missing_ok=True)
                        environment = dict(os.environ, BASH_ENV=str(environment_file),
                                           BINDGEN_CALLS=str(log), FAIL_TARGET=failed,
                                           ANDROID_NDK_HOME=str(ndk), TW_RUST_NATIVE_TARGET='')
                        result = subprocess.run(['bash', str(TOOLS / 'rust-bindgen'), platform],
                                                cwd=root, env=environment, text=True,
                                                capture_output=True)
                        expected = builds[:targets.index(failed) + 1] if failed else builds + [
                            'cbindgen', 'run -- cpp']
                        self.assertEqual(result.returncode, 37 if failed else 0, result.stderr)
                        self.assertEqual(log.read_text().splitlines(), expected)


if __name__ == '__main__':
    unittest.main()
