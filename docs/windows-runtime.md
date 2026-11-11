# Windows x64 runtime

`libTrustWalletCore.dll` is the byte-identical runtime copy of the SDK's
`TrustWalletCore.dll`, named for the existing wallet_core_bindings loader.
Keep it next to the application executable or load it by absolute path.

This Release x64 library uses ClangCL, the MSVC ABI and the dynamic CRT (`/MD`).
Install the Microsoft Visual C++ Redistributable x64 on the deployment machine.
Windows 10 or Windows Server 2016 or later is required. ARM64, MinGW, `/MT`, and
Debug CRT consumers are outside this build configuration.

Free handles and buffers with the corresponding Wallet Core deletion function.
The `licenses` directory contains the applicable first- and third-party notices.
Headers, import/static libraries and CMake SDK metadata are available in the
separate SDK build; they are not required by a Dart dynamic loader.
