// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "WalletCoreBinaryConsumer",
    platforms: [.macOS(.v12)],
    products: [.executable(name: "consumer", targets: ["Consumer"])],
    targets: [
        .binaryTarget(name: "TrustWalletCore", path: "TrustWalletCore.xcframework"),
        .executableTarget(name: "Consumer", dependencies: ["TrustWalletCore"])
    ]
)
