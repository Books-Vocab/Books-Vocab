// swift-tools-version:6.0
import PackageDescription

// ops-internal Swift tooling that needs external SwiftPM dependencies (and so
// cannot use the single-file `#!/usr/bin/env swift` pattern of
// `ops/catalog_png_inspect.swift`). Built once and cached under
// `.cache/ops-swift-build/` by `ops/lib/kgindex_build.sh`.
//
// `kgindex` is a neutral IndexStore extractor: given an Xcode IndexStore and a
// source-root substring, it emits per-symbol definition + reference records as
// JSON. All dead-code / orphan policy lives in `ops/ui_deadcode.py` so it stays
// unit-testable; this binary carries no policy.
//
// indexstore-db is pinned to release/6.3.1 to stay ABI-compatible with the
// libIndexStore.dylib shipped by Xcode's Swift 6.3 toolchain. On a major Xcode
// upgrade, bump this revision to the matching release branch and re-resolve.
let package = Package(
    name: "kg-ops-swift",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/indexstore-db.git", revision: "release/6.3.1"),
    ],
    targets: [
        .executableTarget(
            name: "kgindex",
            dependencies: [.product(name: "IndexStoreDB", package: "indexstore-db")]
        ),
    ]
)
