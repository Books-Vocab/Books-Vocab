//
//  CatalogSnapshotTests.swift
//  BooksBrowserTests
//
//  Drives PlaybookSnapshot against the KG catalog to produce PNG renders of
//  every scenario. Output lives in the simulator sandbox's temporary directory;
//  extract via `xcrun simctl get_app_container booted ... data` + a `find`
//  for `kg-catalog-snapshots`. 詳見 docs/sop/ios.md §Catalog Snapshot Export。
//

#if DEBUG
import Foundation
import Testing
import Playbook
import PlaybookSnapshot
@testable import BooksBrowser

@Suite struct CatalogSnapshotTests {
    /// Render every scenario registered by `CatalogScene.buildPlaybook()` to PNG
    /// at `<NSTemporaryDirectory>/kg-catalog-snapshots/<device>/<category>/<scenario>.png`.
    ///
    /// 本 test 不對結果做 assertion;它的職責是「生圖」,給 Claude / CLI 後續比對。
    /// 失敗條件只剩 PlaybookSnapshot 內部 timeout 或寫檔錯誤,會以 throw 冒出。
    @Test func generateAllScenarioPNGs() throws {
        let outputDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-catalog-snapshots", isDirectory: true)

        let snapshot = Snapshot(
            directory: outputDirectory,
            clean: true,
            format: .png(.basic),
            devices: [
                SnapshotDevice.iPhone15Pro(.portrait),
                SnapshotDevice.iPhone15Pro(.portrait).style(.dark)
            ]
        )

        try snapshot.run(with: CatalogScene.buildPlaybook())

        print("KG catalog snapshots written to: \(outputDirectory.path)")
    }
}
#endif
