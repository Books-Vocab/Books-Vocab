//
//  CatalogSnapshotTests.swift
//  Books & Vocab Tests
//
//  Drives PlaybookSnapshot against the KG catalog to produce PNG renders of
//  every scenario. Output lives in the simulator sandbox's temporary directory;
//  extract via `xcrun simctl get_app_container booted ... data` + a `find`
//  for `kg-catalog-snapshots`. 詳見 docs/sop/ios.md §Catalog Snapshot Export。
//

#if DEBUG && canImport(Playbook)
import Foundation
import Testing
import Playbook
import PlaybookSnapshot
@testable import BooksAndVocab

#if KG_RUN_CATALOG_SNAPSHOTS
private let catalogSnapshotCompileFlagEnabled = true
#else
private let catalogSnapshotCompileFlagEnabled = false
#endif

@Suite struct CatalogSnapshotTests {
    private struct ScopeFile: Decodable {
        let groups: [String]
        let scenarios: [String]
    }

    private static func elapsedMilliseconds(since start: CFAbsoluteTime) -> Int {
        Int(((CFAbsoluteTimeGetCurrent() - start) * 1_000).rounded())
    }

    private static func parseList(_ rawValue: String) -> [String] {
        return rawValue
            .split(whereSeparator: { $0 == "," || $0 == "\n" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private static func parseListEnv(_ key: String) -> [String] {
        parseList(ProcessInfo.processInfo.environment[key] ?? "")
    }

    private static func parseListArguments(_ arguments: [String], flag: String) -> [String] {
        guard let flagIndex = arguments.firstIndex(of: flag) else { return [] }
        let valueIndex = arguments.index(after: flagIndex)
        guard arguments.indices.contains(valueIndex) else { return [] }
        return parseList(arguments[valueIndex])
    }

    private static func parseListArgument(_ flag: String) -> [String] {
        parseListArguments(ProcessInfo.processInfo.arguments, flag: flag)
    }

    private static func parseScopeFile() -> ScopeFile? {
        let url = URL(fileURLWithPath: "/tmp/kg-catalog-scope.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(ScopeFile.self, from: data)
    }

    private static func scopedScenarioCount(in playbook: Playbook) -> Int {
        playbook.stores.reduce(into: 0) { $0 += $1.scenarios.count }
    }

    /// Scope 匹配零 scenario 時的 fail-fast。沒有這條,空 playbook 會在下游以
    /// 「catalog_index.json 不存在」(NSCocoaErrorDomain Code=4,輸出目錄從未建立)
    /// 冒出,完全看不出是 scope 打錯(category 名大小寫敏感,如 `Settings`≠`settings`)。
    private struct EmptyScopeError: Error, CustomStringConvertible {
        let groups: [String]
        let scenarios: [String]

        var description: String {
            """
            catalog scope matched zero scenarios (category names are case-sensitive). \
            groups=\(groups) scenarios=\(scenarios). \
            Valid groups: \(CatalogScene.Manifest.categoryNames.sorted().joined(separator: ", "))
            """
        }
    }

    /// Render every scenario registered by `CatalogScene.buildPlaybook()` to PNG
    /// at `<NSTemporaryDirectory>/kg-catalog-snapshots/<device>/<category>/<scenario>.png`.
    ///
    /// 本 test 不對結果做 assertion;它的職責是「生圖」,給 Claude / CLI 後續比對。
    /// 失敗條件只剩 PlaybookSnapshot 內部 timeout 或寫檔錯誤,會以 throw 冒出。
    @Test @MainActor func generateAllScenarioPNGs() throws {
        guard
            catalogSnapshotCompileFlagEnabled
                || ProcessInfo.processInfo.environment["KG_RUN_CATALOG_SNAPSHOTS"] == "1"
        else {
            print("KG catalog snapshot export skipped; enable compile flag KG_RUN_CATALOG_SNAPSHOTS or set env KG_RUN_CATALOG_SNAPSHOTS=1 to render PNGs.")
            return
        }

        let testBodyStart = CFAbsoluteTimeGetCurrent()
        let outputDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-catalog-snapshots", isDirectory: true)
        let fileScope = Self.parseScopeFile()
        let groups = Self.parseListEnv("KG_CATALOG_GROUPS")
            .ifEmpty(Self.parseListArgument("-KG_CATALOG_GROUPS"))
            .ifEmpty(fileScope?.groups ?? [])
        let scenarios = Self.parseListEnv("KG_CATALOG_SCENARIOS")
            .ifEmpty(Self.parseListArgument("-KG_CATALOG_SCENARIOS"))
            .ifEmpty(fileScope?.scenarios ?? [])
        let filter = try CatalogScene.filter(groups: groups, scenarios: scenarios)
        let playbookBuildStart = CFAbsoluteTimeGetCurrent()
        let playbook = CatalogScene.buildPlaybook(filter: filter)
        let playbookBuildMs = Self.elapsedMilliseconds(since: playbookBuildStart)
        let resolvedCategories = playbook.stores.map { $0.category.rawValue }.sorted()
        let resolvedScenarioCount = Self.scopedScenarioCount(in: playbook)
        if resolvedScenarioCount == 0, !(groups.isEmpty && scenarios.isEmpty) {
            throw EmptyScopeError(groups: groups, scenarios: scenarios)
        }
        let scopeSummary = [
            groups.isEmpty ? nil : "groups=\(groups.joined(separator: ", "))",
            scenarios.isEmpty ? nil : "scenarios=\(scenarios.joined(separator: ", "))",
        ]
        .compactMap { $0 }
        .joined(separator: " | ")

        // 寬版規格參考（web 重寫的 responsive 標準答案）。Gallery/parity
        // 端以 review_manifest 的 devices 欄位區分，iPhone 仍為首選裝置。
        let deviceVariants: [SnapshotDevice] = [
            SnapshotDevice.iPhone15Pro(.portrait),
            SnapshotDevice.iPhone15Pro(.portrait).style(.dark),
            SnapshotDevice.iPadPro11(.landscape),
            SnapshotDevice.iPadPro11(.landscape).style(.dark)
        ]
        let snapshot = Snapshot(
            directory: outputDirectory,
            clean: true,
            format: .png,
            devices: deviceVariants
        )

        let snapshotRunStart = CFAbsoluteTimeGetCurrent()
        try snapshot.run(with: playbook)
        let snapshotRunMs = Self.elapsedMilliseconds(since: snapshotRunStart)

        // Emit the source-of-truth taxonomy index next to the PNGs. `snapshot.run`
        // cleans `outputDirectory` then writes `<device>/<category>/...`, so this
        // sits at the root the `ops/catalog_review_*.py` gallery treats as
        // `source_root`. The gallery consumes it to assign lane/feature/screen
        // instead of guessing from transparent-margin pixels + title regex.
        let indexURL = outputDirectory.appendingPathComponent("catalog_index.json")
        try CatalogScene.Manifest.indexJSONData().write(to: indexURL)

        let testBodyMs = Self.elapsedMilliseconds(since: testBodyStart)

        print("KG catalog snapshots written to: \(outputDirectory.path)")
        print("KG catalog index written to: \(indexURL.path)")
        print(
            """
            KG catalog snapshot debug:
             - env.groups: \(ProcessInfo.processInfo.environment["KG_CATALOG_GROUPS"] ?? "<empty>")
             - env.scenarios: \(ProcessInfo.processInfo.environment["KG_CATALOG_SCENARIOS"] ?? "<empty>")
             - fixture.dataset: \(FixtureDatasetStore.debugSummary())
             - scopeFile.present: \(fileScope != nil)
             - resolved.categories: \(resolvedCategories.joined(separator: " | "))
             - resolved.scenarioCount: \(resolvedScenarioCount)
             - resolved.deviceVariantCount: \(deviceVariants.count)
             - timing.playbookBuildMs: \(playbookBuildMs)
             - timing.snapshotRunMs: \(snapshotRunMs)
             - timing.testBodyMs: \(testBodyMs)
            """
        )
        if !scopeSummary.isEmpty {
            print("KG catalog snapshot scope: \(scopeSummary)")
        }
    }

    @Test func parseListArgumentsReadsLaunchArgumentPairs() {
        let groups = Self.parseListArguments(
            ["xctest", "-KG_CATALOG_GROUPS", "Bookshelf View, Today Review"],
            flag: "-KG_CATALOG_GROUPS"
        )
        let scenarios = Self.parseListArguments(
            ["xctest", "-KG_CATALOG_SCENARIOS", "Today Review/Front\nBookshelf View/Populated · mixed formats"],
            flag: "-KG_CATALOG_SCENARIOS"
        )
        #expect(groups == ["Bookshelf View", "Today Review"])
        #expect(scenarios == ["Today Review/Front", "Bookshelf View/Populated · mixed formats"])
    }
}

private extension [String] {
    func ifEmpty(_ fallback: [String]) -> [String] {
        isEmpty ? fallback : self
    }
}
#endif
