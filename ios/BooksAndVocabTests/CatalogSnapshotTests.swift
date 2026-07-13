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
import CryptoKit
import ImageIO
import UIKit
import UniformTypeIdentifiers
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
    private struct AppearanceDeviceVariant {
        let family: String
        let requestedStyle: UIUserInterfaceStyle
        let device: SnapshotDevice

        var requestedName: String {
            Self.styleName(requestedStyle)
        }

        private static func styleName(_ style: UIUserInterfaceStyle) -> String {
            switch style {
            case .light: "light"
            case .dark: "dark"
            case .unspecified: "unspecified"
            @unknown default: "unknown"
            }
        }
    }

    private final class AppearanceLedger: @unchecked Sendable {
        struct Seed {
            let captureID: String
            let family: String
            let device: String
            let category: String
            let scenario: String
            let relPath: String
            let requested: String
            let appearanceSensitive: Bool
        }

        private let lock = NSLock()
        private var seedsByID: [String: Seed] = [:]
        private var actualByID: [String: String] = [:]
        private var unidentifiedViews: [String] = []

        func register(_ seed: Seed) {
            lock.lock()
            defer { lock.unlock() }
            precondition(seedsByID[seed.captureID] == nil, "duplicate appearance capture ID: \(seed.captureID)")
            seedsByID[seed.captureID] = seed
        }

        func recordActual(captureID: String, style: UIUserInterfaceStyle) {
            lock.lock()
            defer { lock.unlock() }
            actualByID[captureID] = Self.styleName(style)
        }

        func recordUnidentifiedView(_ view: UIView) {
            lock.lock()
            defer { lock.unlock() }
            unidentifiedViews.append(String(describing: type(of: view)))
        }

        func snapshot() -> (seeds: [Seed], actualByID: [String: String], unidentifiedViews: [String]) {
            lock.lock()
            defer { lock.unlock() }
            return (
                seedsByID.values.sorted { $0.relPath < $1.relPath },
                actualByID,
                unidentifiedViews
            )
        }

        private static func styleName(_ style: UIUserInterfaceStyle) -> String {
            switch style {
            case .light: "light"
            case .dark: "dark"
            case .unspecified: "unspecified"
            @unknown default: "unknown"
            }
        }
    }

    private final class AppearanceProbeViewController: UIViewController {
        override func loadView() {
            let resolvedColor: UIColor
            switch traitCollection.userInterfaceStyle {
            case .light:
                resolvedColor = .white
            case .dark:
                resolvedColor = .black
            case .unspecified:
                resolvedColor = .red
            @unknown default:
                resolvedColor = .red
            }
            let view = UIView()
            view.backgroundColor = resolvedColor
            self.view = view
        }
    }

    private final class AppearanceStyleBox: @unchecked Sendable {
        private let lock = NSLock()
        private var stored: UIUserInterfaceStyle = .unspecified

        func set(_ style: UIUserInterfaceStyle) {
            lock.lock()
            defer { lock.unlock() }
            stored = style
        }

        var value: UIUserInterfaceStyle {
            lock.lock()
            defer { lock.unlock() }
            return stored
        }
    }

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

    private static func appearancePinnedScenario(
        _ scenario: Scenario,
        requestedStyle: UIUserInterfaceStyle,
        captureID: String
    ) -> Scenario {
        let content = scenario.content
        return Scenario(
            scenario.title,
            layout: scenario.layout,
            file: scenario.file,
            line: scenario.line
        ) { context in
            let controller = content(context)
            // ScenarioViewController reads `controller.view` immediately after
            // this closure returns. Pin the controller before that first view
            // load so SwiftUI/UIKit initialization cannot inherit simulator
            // residue, then pin the root view as a second boundary.
            controller.overrideUserInterfaceStyle = requestedStyle
            let rootView = controller.view!
            rootView.overrideUserInterfaceStyle = requestedStyle
            rootView.accessibilityIdentifier = captureID
            return controller
        }
    }

    private static func catalogDeviceVariants() -> [AppearanceDeviceVariant] {
        func makeVariants(base: SnapshotDevice) -> [AppearanceDeviceVariant] {
            var light = base.style(.light)
            // Preserve the established light directory name. The trait is now
            // explicit even though the path remains backward-compatible.
            light.name = base.name
            return [
                AppearanceDeviceVariant(
                    family: base.name,
                    requestedStyle: .light,
                    device: light
                ),
                AppearanceDeviceVariant(
                    family: base.name,
                    requestedStyle: .dark,
                    device: base.style(.dark)
                ),
            ]
        }

        return makeVariants(base: SnapshotDevice.iPhone15Pro(.portrait))
            + makeVariants(base: SnapshotDevice.iPadPro11(.landscape))
    }

    /// Wall-time budget granted per `(scenario × device)` capture in the main
    /// `Snapshot.run` pass. PlaybookSnapshot's `Snapshot` defaults to a flat
    /// `timeout: 600`s for the *entire* run; a full catalog against a heavy
    /// dataset (e.g. the marketing spec world — 600+ cards, saturated graph)
    /// renders all 1300+ captures in ~770s and blew past that ceiling, so
    /// `snapshot.run` threw `.timeout(600)` *after* producing every main-pass
    /// PNG but *before* the web-view pass ran — silently dropping the 16 graph
    /// PNGs. Measured ~0.58s/capture on iOS 26.4 sim; 2.0s gives >3x head-room
    /// and, being derived from the resolved workload, keeps future catalog
    /// growth from silently re-tripping the ceiling. This only raises the
    /// *ceiling* — `Snapshot.run` still returns the instant its DispatchGroup
    /// completes, so fast/scoped runs pay nothing.
    static let snapshotSecondsPerCapture: TimeInterval = 2.0

    /// Floor so scoped/tiny runs keep a sane budget instead of a near-zero one.
    static let snapshotTimeoutFloor: TimeInterval = 600

    /// Derives the main-pass `Snapshot` timeout from the actual workload.
    static func snapshotTimeout(scenarioCount: Int, deviceCount: Int) -> TimeInterval {
        let captures = max(0, scenarioCount) * max(0, deviceCount)
        return max(snapshotTimeoutFloor, snapshotSecondsPerCapture * TimeInterval(captures))
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
        let deviceVariants = Self.catalogDeviceVariants()
        let appearanceLedger = AppearanceLedger()
        let (mainPlaybook, webViewScenarios) = Self.splitWebViewScenarios(from: playbook)

        let snapshotRunStart = CFAbsoluteTimeGetCurrent()
        let armedBeforeMainPass = CatalogGraphSnapshotFreezer.armedCount
        for (index, variant) in deviceVariants.enumerated() {
            let pinnedPlaybook = Self.appearancePinnedPlaybook(
                mainPlaybook,
                variant: variant,
                ledger: appearanceLedger
            )
            let snapshot = Snapshot(
                directory: outputDirectory,
                clean: index == 0,
                format: .png,
                timeout: Self.snapshotTimeout(
                    scenarioCount: Self.scopedScenarioCount(in: pinnedPlaybook),
                    deviceCount: 1
                ),
                devices: [variant.device],
                viewPreprocessor: Self.appearanceViewPreprocessor(ledger: appearanceLedger)
            )
            try snapshot.run(with: pinnedPlaybook)
        }
        // Anti-drift gate: a CatalogGraphSnapshotScene-wrapped scenario whose
        // key is missing from webViewSnapshotScenarios would arm a waiter
        // inside the main pass, wait out 30s, and silently write a blank
        // canvas. Fail loudly instead.
        let armedDuringMainPass = CatalogGraphSnapshotFreezer.armedCount - armedBeforeMainPass
        guard armedDuringMainPass == 0 else {
            throw WebViewSnapshotError(description: """
            \(armedDuringMainPass) CatalogGraphSnapshotScene waiter(s) armed inside the main \
            Snapshot.run pass — a web-view-backed scenario is missing from \
            CatalogGraphSnapshotFreezer.webViewSnapshotScenarios and would render blank.
            """)
        }
        try await Self.renderWebViewScenarioPNGs(
            webViewScenarios,
            variants: deviceVariants,
            outputDirectory: outputDirectory,
            appearanceLedger: appearanceLedger
        )
        let snapshotRunMs = Self.elapsedMilliseconds(since: snapshotRunStart)

        // Emit the source-of-truth taxonomy index next to the PNGs. `snapshot.run`
        // cleans `outputDirectory` then writes `<device>/<category>/...`, so this
        // sits at the root the `ops/catalog_review_*.py` gallery treats as
        // `source_root`. The gallery consumes it to assign lane/feature/screen
        // instead of guessing from transparent-margin pixels + title regex.
        let indexURL = outputDirectory.appendingPathComponent("catalog_index.json")
        try CatalogScene.Manifest.indexJSONData().write(to: indexURL)
        let appearanceSidecarURL = try Self.writeAndValidateAppearanceSidecar(
            ledger: appearanceLedger,
            outputDirectory: outputDirectory,
            provenance: .current()
        )

        let testBodyMs = Self.elapsedMilliseconds(since: testBodyStart)

        print("KG catalog snapshots written to: \(outputDirectory.path)")
        print("KG catalog index written to: \(indexURL.path)")
        print("KG catalog appearance sidecar written to: \(appearanceSidecarURL.path)")
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

    private typealias WebViewScenario = (
        category: ScenarioCategory,
        scenario: Scenario,
        expectation: CatalogGraphSnapshotFreezer.WebViewArmingExpectation
    )

    /// Splits the filtered playbook into the `Snapshot.run` set and the
    /// WKWebView-backed set (`CatalogGraphSnapshotFreezer.webViewSnapshotScenarios`).
    private static func splitWebViewScenarios(
        from playbook: Playbook
    ) -> (main: Playbook, webView: [WebViewScenario]) {
        let mainPlaybook = Playbook()
        var webView: [WebViewScenario] = []
        for store in playbook.stores {
            for scenario in store.scenarios {
                let key = "\(store.category.rawValue)/\(scenario.title.rawValue)"
                if let expectation = CatalogGraphSnapshotFreezer.webViewSnapshotScenarios[key] {
                    webView.append((store.category, scenario, expectation))
                } else {
                    mainPlaybook.scenarios(of: store.category).add(scenario)
                }
            }
        }
        return (mainPlaybook, webView)
    }

    private static func appearancePinnedPlaybook(
        _ playbook: Playbook,
        variant: AppearanceDeviceVariant,
        ledger: AppearanceLedger
    ) -> Playbook {
        let pinned = Playbook()
        for store in playbook.stores {
            for scenario in store.scenarios {
                let seed = appearanceSeed(
                    category: store.category,
                    scenario: scenario,
                    variant: variant
                )
                ledger.register(seed)
                pinned.scenarios(of: store.category).add(
                    appearancePinnedScenario(
                        scenario,
                        requestedStyle: variant.requestedStyle,
                        captureID: seed.captureID
                    )
                )
            }
        }
        return pinned
    }

    private static func appearanceSeed(
        category: ScenarioCategory,
        scenario: Scenario,
        variant: AppearanceDeviceVariant
    ) -> AppearanceLedger.Seed {
        let relPath = [
            variant.device.name,
            normalizeSnapshotName(category.rawValue),
            normalizeSnapshotName(scenario.title.rawValue) + ".png",
        ].joined(separator: "/")
        let captureID = appearanceCaptureID(
            requested: variant.requestedName,
            relPath: relPath
        )
        return AppearanceLedger.Seed(
            captureID: captureID,
            family: variant.family,
            device: variant.device.name,
            category: category.rawValue,
            scenario: scenario.title.rawValue,
            relPath: relPath,
            requested: variant.requestedName,
            appearanceSensitive: isAppearanceSensitive(
                category: category.rawValue,
                scenario: scenario.title.rawValue
            )
        )
    }

    private static func appearanceCaptureID(requested: String, relPath: String) -> String {
        let canonicalIdentity = "\(requested)|\(relPath)"
        return "catalog-\(sha256(Data(canonicalIdentity.utf8)))"
    }

    /// External-appearance contract for App Store capture surfaces. Catalog
    /// also contains scenarios that deliberately pin their own scheme (for
    /// example Welcome/Step 3 / Dark), so layout cannot be used as a proxy.
    private static let appearanceSensitiveScenarioKeys: Set<String> = [
        "Knowledge Graph View/Populated graph",
        "Vocabulary List View/Populated · mixed sync states",
        "Notebook List View/Populated · multiple notebooks",
        "Stats View/Populated",
        "Today Review/Back",
    ]

    private static func isAppearanceSensitive(
        category: String,
        scenario: String
    ) -> Bool {
        appearanceSensitiveScenarioKeys.contains("\(category)/\(scenario)")
    }

    private static func appearanceViewPreprocessor(
        ledger: AppearanceLedger
    ) -> (UIView) -> UIView {
        { view in
            guard let captureID = view.accessibilityIdentifier, !captureID.isEmpty else {
                ledger.recordUnidentifiedView(view)
                return view
            }
            ledger.recordActual(
                captureID: captureID,
                style: view.traitCollection.userInterfaceStyle
            )
            return view
        }
    }

    private struct AppearanceCaptureEvidence {
        let captureID: String
        let family: String
        let device: String
        let category: String
        let scenario: String
        let relPath: String
        let requested: String
        let actual: String
        let appearanceSensitive: Bool
        let pngSHA256: String
        let pixelSHA256: String
    }

    private struct AppearanceCaptureProof: Encodable {
        let id: String
        let requestedAppearance: String
        let actualAppearance: String
        let pixelSHA256: String
    }

    private struct AppearanceVerdict: Encodable {
        let status: String
        let proofCount: Int
    }

    private struct AppearanceSidecar: Encodable {
        let schema = "kg.catalog.appearance.v1"
        let verdict: AppearanceVerdict
        let sourceCommit: String
        let datasetID: String
        let datasetSHA256: String
        let fixedClock: String
        let observedAt: String
        let captures: [AppearanceCaptureProof]
    }

    private struct AppearanceProvenance {
        let sourceCommit: String
        let datasetID: String
        let datasetSHA256: String
        let fixedClock: String
        let observedAt: String

        static func current() -> Self {
            let environment = ProcessInfo.processInfo.environment
            let summary = FixtureDatasetStore.debugSummary()
            let datasetID = summary.components(separatedBy: " @ ").count == 2
                ? summary.components(separatedBy: " @ ")[0]
                : ""
            return Self(
                sourceCommit: environment["KG_REVIEW_SOURCE_COMMIT"] ?? "",
                datasetID: datasetID,
                datasetSHA256: environment["KG_FIXTURE_DATASET_SHA256"] ?? "",
                fixedClock: FixtureDatasetStore.marketingCapture()?.reviewClock?.frozenNow ?? "",
                observedAt: ISO8601DateFormatter().string(from: Date())
            )
        }
    }

    private struct AppearancePairKey: Hashable {
        let family: String
        let category: String
        let scenario: String
    }

    private struct CatalogAppearanceError: Error, CustomStringConvertible {
        let description: String
    }

    private static func writeAndValidateAppearanceSidecar(
        ledger: AppearanceLedger,
        outputDirectory: URL,
        provenance: AppearanceProvenance
    ) throws -> URL {
        let ledgerSnapshot = ledger.snapshot()
        var issues = ledgerSnapshot.unidentifiedViews.map {
            "snapshot view missing capture identity: \($0)"
        }
        if ledgerSnapshot.seeds.isEmpty {
            issues.append("appearance proof must contain at least one capture")
        }
        if !isLowercaseHex(provenance.sourceCommit, count: 40) {
            issues.append("appearance provenance sourceCommit must be a full lowercase git SHA")
        }
        if provenance.datasetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("appearance provenance datasetID must not be empty")
        }
        if !isLowercaseHex(provenance.datasetSHA256, count: 64) {
            issues.append("appearance provenance datasetSHA256 must be a lowercase SHA-256")
        }
        if provenance.fixedClock.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("appearance provenance fixedClock must not be empty")
        }
        if provenance.observedAt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("appearance provenance observedAt must not be empty")
        }
        var captures: [AppearanceCaptureEvidence] = []

        for seed in ledgerSnapshot.seeds {
            let actual = ledgerSnapshot.actualByID[seed.captureID] ?? "missing"
            let fileURL = outputDirectory.appendingPathComponent(seed.relPath)
            let pngDigest: String
            let pixelDigest: String
            if let data = try? Data(contentsOf: fileURL), let normalizedPixelDigest = pixelSHA256(data) {
                pngDigest = sha256(data)
                pixelDigest = normalizedPixelDigest
            } else {
                pngDigest = "missing"
                pixelDigest = "missing"
                issues.append("capture PNG missing or undecodable: \(seed.relPath)")
            }
            if actual != seed.requested {
                issues.append(
                    "appearance trait mismatch for \(seed.relPath): requested=\(seed.requested) actual=\(actual)"
                )
            }
            captures.append(
                AppearanceCaptureEvidence(
                    captureID: seed.captureID,
                    family: seed.family,
                    device: seed.device,
                    category: seed.category,
                    scenario: seed.scenario,
                    relPath: seed.relPath,
                    requested: seed.requested,
                    actual: actual,
                    appearanceSensitive: seed.appearanceSensitive,
                    pngSHA256: pngDigest,
                    pixelSHA256: pixelDigest
                )
            )
        }

        var grouped: [AppearancePairKey: [String: AppearanceCaptureEvidence]] = [:]
        for capture in captures {
            let key = AppearancePairKey(
                family: capture.family,
                category: capture.category,
                scenario: capture.scenario
            )
            grouped[key, default: [:]][capture.requested] = capture
        }

        let orderedKeys = grouped.keys.sorted {
            ($0.family, $0.category, $0.scenario) < ($1.family, $1.category, $1.scenario)
        }
        for key in orderedKeys {
            let variants = grouped[key] ?? [:]
            let light = variants["light"]
            let dark = variants["dark"]
            let appearanceSensitive = light?.appearanceSensitive ?? dark?.appearanceSensitive ?? false
            let pixelIdentical: Bool? = {
                guard
                    let light,
                    let dark,
                    light.pixelSHA256 != "missing",
                    dark.pixelSHA256 != "missing"
                else { return nil }
                return light.pixelSHA256 == dark.pixelSHA256
            }()

            if appearanceSensitive, light == nil || dark == nil {
                issues.append(
                    "appearance-sensitive pair incomplete: \(key.family)/\(key.category)/\(key.scenario)"
                )
            }
            if appearanceSensitive, pixelIdentical == true {
                issues.append(
                    "appearance-sensitive light/dark PNGs have identical normalized pixels: \(key.family)/\(key.category)/\(key.scenario)"
                )
            }
        }

        let proofs = captures.map {
            AppearanceCaptureProof(
                id: $0.captureID,
                requestedAppearance: $0.requested,
                actualAppearance: $0.actual,
                pixelSHA256: $0.pixelSHA256
            )
        }

        let sidecar = AppearanceSidecar(
            verdict: AppearanceVerdict(
                status: issues.isEmpty ? "pass" : "fail",
                proofCount: proofs.count
            ),
            sourceCommit: provenance.sourceCommit,
            datasetID: provenance.datasetID,
            datasetSHA256: provenance.datasetSHA256,
            fixedClock: provenance.fixedClock,
            observedAt: provenance.observedAt,
            captures: proofs
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let sidecarURL = outputDirectory.appendingPathComponent("catalog_appearance.json")
        try encoder.encode(sidecar).write(to: sidecarURL, options: .atomic)

        guard issues.isEmpty else {
            throw CatalogAppearanceError(
                description: "catalog appearance validation failed:\n- " + issues.joined(separator: "\n- ")
            )
        }
        return sidecarURL
    }

    private static func isLowercaseHex(_ value: String, count: Int) -> Bool {
        value.count == count && value.allSatisfy { ("0"..."9").contains($0) || ("a"..."f").contains($0) }
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func pixelSHA256(_ encodedImageData: Data) -> String? {
        guard
            let source = CGImageSourceCreateWithData(encodedImageData as CFData, nil),
            let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
            image.width > 0,
            image.height > 0,
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)
        else { return nil }

        let width = image.width
        let height = image.height
        let bytesPerRow = width * 4
        var rgba = [UInt8](repeating: 0, count: bytesPerRow * height)
        let drewImage = rgba.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(
                data: bytes.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: bytesPerRow,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                    | CGBitmapInfo.byteOrder32Big.rawValue
            ) else { return false }
            context.setBlendMode(.copy)
            context.interpolationQuality = .none
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drewImage else { return nil }

        var canonical = Data()
        var widthBE = UInt64(width).bigEndian
        var heightBE = UInt64(height).bigEndian
        withUnsafeBytes(of: &widthBE) { canonical.append(contentsOf: $0) }
        withUnsafeBytes(of: &heightBE) { canonical.append(contentsOf: $0) }
        canonical.append(contentsOf: rgba)
        return sha256(canonical)
    }

    private struct WebViewSnapshotError: Error, CustomStringConvertible {
        let description: String
    }

    /// Captures WKWebView-backed scenarios via `SnapshotSupport.data` under
    /// Swift-concurrency waiting (main runloop free → WebContent process can
    /// launch, unlike inside `Snapshot.run`'s spin loop), writing PNGs into the
    /// same `<device>/<category>/<scenario>.png` taxonomy as the main pass.
    ///
    /// Freeze gate(false-green 防護), per `WebViewArmingExpectation`:
    /// `.always` scenarios must arm and freeze exactly once per capture (a
    /// removed wrapper fails loudly instead of silently shipping a blank
    /// canvas); `.datasetDependent` scenarios must freeze every armed waiter
    /// (zero armed / zero frozen is legal on link-less datasets).
    @MainActor
    private static func renderWebViewScenarioPNGs(
        _ scenarios: [WebViewScenario],
        variants: [AppearanceDeviceVariant],
        outputDirectory: URL,
        appearanceLedger: AppearanceLedger
    ) async throws {
        guard !scenarios.isEmpty else { return }
        let fileManager = FileManager.default

        for variant in variants {
            for (category, scenario, expectation) in scenarios {
                let device = variant.device
                let directoryURL = outputDirectory
                    .appendingPathComponent(device.name, isDirectory: true)
                    .appendingPathComponent(normalizeSnapshotName(category.rawValue), isDirectory: true)
                try fileManager.createDirectory(at: directoryURL, withIntermediateDirectories: true)
                let fileURL = directoryURL
                    .appendingPathComponent(normalizeSnapshotName(scenario.title.rawValue))
                    .appendingPathExtension("png")

                let seed = appearanceSeed(
                    category: category,
                    scenario: scenario,
                    variant: variant
                )
                appearanceLedger.register(seed)
                let pinnedScenario = appearancePinnedScenario(
                    scenario,
                    requestedStyle: variant.requestedStyle,
                    captureID: seed.captureID
                )
                let armedBefore = CatalogGraphSnapshotFreezer.armedCount
                let freezesBefore = CatalogGraphSnapshotFreezer.freezeCount
                let data: Data = await withCheckedContinuation { continuation in
                    SnapshotSupport.data(
                        for: pinnedScenario,
                        on: device,
                        format: .png,
                        viewPreprocessor: appearanceViewPreprocessor(ledger: appearanceLedger)
                    ) { data in
                            continuation.resume(returning: data)
                        }
                }
                let armedDelta = CatalogGraphSnapshotFreezer.armedCount - armedBefore
                let freezeDelta = CatalogGraphSnapshotFreezer.freezeCount - freezesBefore
                let expectationSatisfied: Bool
                switch expectation {
                case .always:
                    // Must arm and freeze exactly once — catches both "hook
                    // never fired" and "wrapper removed while key stays listed"
                    // (the latter would otherwise render blank via layer.render).
                    expectationSatisfied = armedDelta == 1 && freezeDelta == 1
                case .datasetDependent:
                    // Every armed waiter must freeze; zero/zero is legal when
                    // the dataset carries no links (empty card, no webview).
                    expectationSatisfied = freezeDelta == armedDelta
                }
                guard expectationSatisfied else {
                    throw WebViewSnapshotError(description: """
                    web-view scenario '\(category.rawValue)/\(scenario.title.rawValue)' on device \
                    '\(device.name)' (expectation: \(expectation)) armed \(armedDelta) snapshot \
                    waiter(s) and produced \(freezeDelta) freeze(s) — the graph canvas would be \
                    blank. Check CatalogGraphSnapshotScene wiring, the kgGraphWebViewInitHook \
                    path, and graph.html readiness (settleGraphForSnapshot).
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

    @Test func snapshotTimeoutScalesWithWorkloadAndKeepsFloor() {
        // Full catalog: 336 scenarios × 4 device variants. The heaviest
        // observed full run (marketing spec world) rendered in ~770s and
        // tripped PlaybookSnapshot's flat 600s default, aborting the main pass
        // before the web-view pass ran. The derived budget must clear that
        // wall time with margin so the graph PNGs are never dropped again.
        let full = Self.snapshotTimeout(scenarioCount: 336, deviceCount: 4)
        #expect(full == 336 * 4 * 2)            // 2688s
        #expect(full > 770 * 2)                 // >2x the worst observed run
        // Scoped / degenerate workloads never drop below the floor.
        #expect(Self.snapshotTimeout(scenarioCount: 1, deviceCount: 1) == Self.snapshotTimeoutFloor)
        #expect(Self.snapshotTimeout(scenarioCount: 0, deviceCount: 0) == Self.snapshotTimeoutFloor)
        #expect(Self.snapshotTimeout(scenarioCount: -5, deviceCount: 4) == Self.snapshotTimeoutFloor)
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

    @Test @MainActor func appearanceSensitiveProbeProducesDistinctLightAndDarkPixels() async {
        let scenario = Scenario("Appearance-sensitive probe", layout: .fixed(length: 64)) {
            AppearanceProbeViewController()
        }
        let baseDevice = SnapshotDevice(
            name: "Appearance Probe",
            size: CGSize(width: 64, height: 64)
        )

        func capture(style: UIUserInterfaceStyle) async -> (data: Data, actual: UIUserInterfaceStyle) {
            let device = baseDevice.style(style)
            let pinned = Self.appearancePinnedScenario(
                scenario,
                requestedStyle: style,
                captureID: style == .dark ? "probe-dark" : "probe-light"
            )
            let actualStyle = AppearanceStyleBox()
            let data: Data = await withCheckedContinuation { continuation in
                SnapshotSupport.data(
                    for: pinned,
                    on: device,
                    format: .png,
                    viewPreprocessor: { view in
                        actualStyle.set(view.traitCollection.userInterfaceStyle)
                        return view
                    }
                ) { data in
                        continuation.resume(returning: data)
                    }
            }
            return (data, actualStyle.value)
        }

        let light = await capture(style: .light)
        let dark = await capture(style: .dark)
        #expect(light.actual == .light)
        #expect(dark.actual == .dark)
        #expect(light.data != dark.data, "appearance-sensitive light/dark renders must not be byte-identical")
    }

    @Test func catalogDeviceVariantsDeclareExplicitAppearanceWithoutRenamingLightDirectories() {
        let variants = Self.catalogDeviceVariants()
        #expect(variants.count == 4)
        #expect(variants.allSatisfy { $0.requestedStyle == .light || $0.requestedStyle == .dark })
        #expect(variants.allSatisfy { $0.device.traitCollection.userInterfaceStyle == $0.requestedStyle })
        #expect(variants.filter { $0.requestedStyle == .light }.allSatisfy { !$0.device.name.contains("(light)") })
        #expect(
            Self.isAppearanceSensitive(
                category: "Knowledge Graph View",
                scenario: "Populated graph"
            )
        )
        #expect(
            !Self.isAppearanceSensitive(
                category: "Welcome",
                scenario: "Step 3 / Dark"
            ),
            "fixed-scheme catalog scenarios must not be judged by global light/dark pair equality"
        )

        let identityInputs = [
            ("light", "iPhone 15 Pro portrait/Knowledge Graph View/Populated graph.png"),
            ("dark", "iPhone 15 Pro portrait (dark)/Knowledge Graph View/Populated graph.png"),
            ("light", "iPad Pro 11 landscape/Knowledge Graph View/Populated graph.png"),
            ("dark", "iPad Pro 11 landscape (dark)/Knowledge Graph View/Populated graph.png"),
        ]
        let captureIDs = identityInputs.map {
            Self.appearanceCaptureID(requested: $0.0, relPath: $0.1)
        }
        #expect(Set(captureIDs).count == captureIDs.count, "appearance proof IDs must not collide")
        #expect(
            captureIDs.allSatisfy {
                guard let first = $0.first, first.isLowercase || first.isNumber else { return false }
                return $0.allSatisfy { character in
                    character.isLowercase
                        || character.isNumber
                        || character == "."
                        || character == "_"
                        || character == "-"
                }
            },
            "appearance proof IDs must satisfy ^[a-z0-9][a-z0-9._-]*$"
        )
        #expect(
            Self.appearanceCaptureID(requested: "light", relPath: identityInputs[0].1) == captureIDs[0],
            "appearance proof IDs must be deterministic"
        )
    }

    @Test func appearanceSidecarRejectsTraitMismatchAndIdenticalSensitivePairs() throws {
        let provenance = AppearanceProvenance(
            sourceCommit: String(repeating: "a", count: 40),
            datasetID: "appearance-test-world",
            datasetSHA256: String(repeating: "b", count: 64),
            fixedClock: "2026-07-13T08:00:00Z",
            observedAt: "2026-07-13T08:01:00Z"
        )

        func png(color: UIColor, metadata: String) throws -> Data {
            let renderer = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 8))
            let image = renderer.image { context in
                color.setFill()
                context.cgContext.fill(CGRect(x: 0, y: 0, width: 8, height: 8))
            }
            let cgImage = try #require(image.cgImage)
            let encoded = NSMutableData()
            let destination = try #require(
                CGImageDestinationCreateWithData(
                    encoded,
                    UTType.png.identifier as CFString,
                    1,
                    nil
                )
            )
            let properties = [
                kCGImagePropertyPNGDictionary: [
                    kCGImagePropertyPNGDescription: metadata,
                ],
            ] as CFDictionary
            CGImageDestinationAddImage(destination, cgImage, properties)
            #expect(CGImageDestinationFinalize(destination))
            return encoded as Data
        }

        func makeRoot(_ label: String) throws -> URL {
            let root = FileManager.default.temporaryDirectory
                .appendingPathComponent("catalog-appearance-\(label)-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            return root
        }

        func registerPair(
            ledger: AppearanceLedger,
            root: URL,
            lightData: Data,
            darkData: Data,
            lightActual: UIUserInterfaceStyle = .light
        ) throws {
            for (requested, actual, data) in [
                ("light", lightActual, lightData),
                ("dark", UIUserInterfaceStyle.dark, darkData),
            ] {
                let relPath = "Probe \(requested)/Surface/State.png"
                let captureID = "\(requested)|\(relPath)"
                ledger.register(
                    AppearanceLedger.Seed(
                        captureID: captureID,
                        family: "Probe",
                        device: "Probe \(requested)",
                        category: "Surface",
                        scenario: "State",
                        relPath: relPath,
                        requested: requested,
                        appearanceSensitive: true
                    )
                )
                ledger.recordActual(captureID: captureID, style: actual)
                let fileURL = root.appendingPathComponent(relPath)
                try FileManager.default.createDirectory(
                    at: fileURL.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                try data.write(to: fileURL)
            }
        }

        let mismatchRoot = try makeRoot("trait-mismatch")
        defer { try? FileManager.default.removeItem(at: mismatchRoot) }
        let mismatchLedger = AppearanceLedger()
        try registerPair(
            ledger: mismatchLedger,
            root: mismatchRoot,
            lightData: try png(color: .white, metadata: "light"),
            darkData: try png(color: .black, metadata: "dark"),
            lightActual: .dark
        )
        #expect(throws: CatalogAppearanceError.self) {
            try Self.writeAndValidateAppearanceSidecar(
                ledger: mismatchLedger,
                outputDirectory: mismatchRoot,
                provenance: provenance
            )
        }
        let mismatchSidecarData = try Data(
            contentsOf: mismatchRoot.appendingPathComponent("catalog_appearance.json")
        )
        let mismatchSidecar = try #require(
            JSONSerialization.jsonObject(with: mismatchSidecarData) as? [String: Any]
        )
        #expect(
            Set(mismatchSidecar.keys) == [
                "schema",
                "verdict",
                "sourceCommit",
                "datasetID",
                "datasetSHA256",
                "fixedClock",
                "observedAt",
                "captures",
            ],
            "appearance sidecar must match the fail-closed gate consumer contract exactly"
        )
        let mismatchVerdict = try #require(mismatchSidecar["verdict"] as? [String: Any])
        #expect(Set(mismatchVerdict.keys) == ["status", "proofCount"])
        let mismatchCaptures = try #require(mismatchSidecar["captures"] as? [[String: Any]])
        #expect(!mismatchCaptures.isEmpty)
        #expect(
            mismatchCaptures.allSatisfy {
                Set($0.keys) == [
                    "id",
                    "requestedAppearance",
                    "actualAppearance",
                    "pixelSHA256",
                ]
            }
        )

        let emptyRoot = try makeRoot("empty-proof")
        defer { try? FileManager.default.removeItem(at: emptyRoot) }
        #expect(throws: CatalogAppearanceError.self) {
            try Self.writeAndValidateAppearanceSidecar(
                ledger: AppearanceLedger(),
                outputDirectory: emptyRoot,
                provenance: provenance
            )
        }

        let identicalRoot = try makeRoot("identical-pair")
        defer { try? FileManager.default.removeItem(at: identicalRoot) }
        let identicalLedger = AppearanceLedger()
        let identicalPixelsA = try png(color: .white, metadata: "encoding-a")
        let identicalPixelsB = try png(color: .white, metadata: "encoding-b")
        #expect(identicalPixelsA != identicalPixelsB)
        #expect(
            Self.pixelSHA256(identicalPixelsA) == Self.pixelSHA256(identicalPixelsB),
            "pixel hashing must ignore PNG metadata and encoding differences"
        )
        try registerPair(
            ledger: identicalLedger,
            root: identicalRoot,
            lightData: identicalPixelsA,
            darkData: identicalPixelsB
        )
        #expect(throws: CatalogAppearanceError.self) {
            try Self.writeAndValidateAppearanceSidecar(
                ledger: identicalLedger,
                outputDirectory: identicalRoot,
                provenance: provenance
            )
        }
    }
}

private extension [String] {
    func ifEmpty(_ fallback: [String]) -> [String] {
        isEmpty ? fallback : self
    }
}
#endif
