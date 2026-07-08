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
    /// 失敗條件只剩 PlaybookSnapshot 內部 timeout、寫檔錯誤(以 throw 冒出),
    /// 以及 web-view scene 的 freeze gate(見 `renderWebViewScenarioPNGs`)。
    ///
    /// WKWebView-backed scenes(知識圖譜)不走 `snapshot.run`:其等待迴圈用
    /// `RunLoop.run(mode:before:)` 自旋,WebContent process 在裡面 launch 不完
    /// (實測 ~598s 才啟動),圖永遠空白。它們改走 `renderWebViewScenarioPNGs`
    /// 的 async 擷取管線 — Swift concurrency 等待下 main runloop 自由運轉,
    /// web process 正常啟動、d3 收斂後由 `CatalogGraphSnapshotFreezer` 轉成
    /// 原生點陣圖再照相。
    @Test @MainActor func generateAllScenarioPNGs() async throws {
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
        let (mainPlaybook, webViewScenarios) = Self.splitWebViewScenarios(from: playbook)

        let snapshot = Snapshot(
            directory: outputDirectory,
            clean: true,
            format: .png,
            devices: deviceVariants
        )

        let snapshotRunStart = CFAbsoluteTimeGetCurrent()
        let armedBeforeMainPass = CatalogGraphSnapshotFreezer.armedCount
        try snapshot.run(with: mainPlaybook)
        // Anti-drift gate: a CatalogGraphSnapshotScene-wrapped scenario whose
        // key is missing from webViewSnapshotScenarioKeys would arm a waiter
        // inside the main pass, wait out 30s, and silently write a blank
        // canvas. Fail loudly instead.
        let armedDuringMainPass = CatalogGraphSnapshotFreezer.armedCount - armedBeforeMainPass
        guard armedDuringMainPass == 0 else {
            throw WebViewSnapshotError(description: """
            \(armedDuringMainPass) CatalogGraphSnapshotScene waiter(s) armed inside the main \
            Snapshot.run pass — a web-view-backed scenario is missing from \
            CatalogGraphSnapshotFreezer.webViewSnapshotScenarioKeys and would render blank.
            """)
        }
        try await Self.renderWebViewScenarioPNGs(
            webViewScenarios,
            devices: deviceVariants,
            outputDirectory: outputDirectory
        )
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

    // MARK: Web-view scenario pipeline

    /// Splits the filtered playbook into the `Snapshot.run` set and the
    /// WKWebView-backed set (`CatalogGraphSnapshotFreezer.webViewSnapshotScenarioKeys`).
    private static func splitWebViewScenarios(
        from playbook: Playbook
    ) -> (main: Playbook, webView: [(category: ScenarioCategory, scenario: Scenario)]) {
        let mainPlaybook = Playbook()
        var webView: [(category: ScenarioCategory, scenario: Scenario)] = []
        for store in playbook.stores {
            for scenario in store.scenarios {
                let key = "\(store.category.rawValue)/\(scenario.title.rawValue)"
                if CatalogGraphSnapshotFreezer.webViewSnapshotScenarioKeys.contains(key) {
                    webView.append((store.category, scenario))
                } else {
                    mainPlaybook.scenarios(of: store.category).add(scenario)
                }
            }
        }
        return (mainPlaybook, webView)
    }

    private struct WebViewSnapshotError: Error, CustomStringConvertible {
        let description: String
    }

    /// Captures WKWebView-backed scenarios via `SnapshotSupport.data` under
    /// Swift-concurrency waiting (main runloop free → WebContent process can
    /// launch, unlike inside `Snapshot.run`'s spin loop), writing PNGs into the
    /// same `<device>/<category>/<scenario>.png` taxonomy as the main pass.
    ///
    /// Freeze gate(false-green 防護): each capture must consume exactly one
    /// `CatalogGraphSnapshotFreezer` freeze — otherwise the canvas is blank
    /// (legend-only) and the run fails loudly instead of shipping it.
    @MainActor
    private static func renderWebViewScenarioPNGs(
        _ scenarios: [(category: ScenarioCategory, scenario: Scenario)],
        devices: [SnapshotDevice],
        outputDirectory: URL
    ) async throws {
        guard !scenarios.isEmpty else { return }
        let fileManager = FileManager.default

        for device in devices {
            for (category, scenario) in scenarios {
                let directoryURL = outputDirectory
                    .appendingPathComponent(device.name, isDirectory: true)
                    .appendingPathComponent(normalizeSnapshotName(category.rawValue), isDirectory: true)
                try fileManager.createDirectory(at: directoryURL, withIntermediateDirectories: true)
                let fileURL = directoryURL
                    .appendingPathComponent(normalizeSnapshotName(scenario.title.rawValue))
                    .appendingPathExtension("png")

                // NOTE: dark device variants currently follow the simulator's
                // global appearance rather than the per-device trait — that is
                // pre-existing catalog-wide behavior (verified: light/dark PNG
                // pairs are byte-identical in the `Snapshot.run` pass too), not
                // something this async pass introduces or can locally fix.
                let freezesBefore = CatalogGraphSnapshotFreezer.freezeCount
                let data: Data = await withCheckedContinuation { continuation in
                    SnapshotSupport.data(for: scenario, on: device, format: .png) { data in
                        continuation.resume(returning: data)
                    }
                }
                guard CatalogGraphSnapshotFreezer.freezeCount == freezesBefore + 1 else {
                    throw WebViewSnapshotError(description: """
                    web-view scenario '\(category.rawValue)/\(scenario.title.rawValue)' on device \
                    '\(device.name)' completed without a graph freeze — the graph canvas would be \
                    blank. Check CatalogGraphSnapshotScene wiring, the kgGraphWebViewInitHook path, \
                    and graph.html readiness (settleGraphForSnapshot).
                    """)
                }
                try data.write(to: fileURL)
            }
        }
    }

    /// Mirrors PlaybookSnapshot's private `Snapshot.normalize` so web-view
    /// scenario PNGs land in the same directory taxonomy as the main pass.
    private static let snapshotNameNormalizationCharacters = CharacterSet(charactersIn: ".:/")
        .union(.whitespacesAndNewlines)
        .union(.illegalCharacters)
        .union(.controlCharacters)

    private static func normalizeSnapshotName(_ string: String) -> String {
        string.components(separatedBy: snapshotNameNormalizationCharacters).joined(separator: "_")
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
