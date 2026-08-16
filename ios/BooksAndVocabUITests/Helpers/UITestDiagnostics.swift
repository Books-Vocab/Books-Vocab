import XCTest

class UITestCase: XCTestCase {
    private(set) var currentApp: XCUIApplication?
    private(set) var lastCapturedScreenshotPath: String?
    private var screenshotStepIndex = 0

    override func setUpWithError() throws {
        continueAfterFailure = false
        screenshotStepIndex = 0
        lastCapturedScreenshotPath = nil
    }

    override func tearDownWithError() throws {
        let failed = (testRun?.failureCount ?? 0) > 0 || (testRun?.unexpectedExceptionCount ?? 0) > 0
        if let app = currentApp, failed {
            attachDiagnostics(for: app)
        }
        currentApp = nil
        try super.tearDownWithError()
    }

    @discardableResult
    func launchApp(
        profile: UITestLaunchProfile = .standard,
        extraArgs: [String] = [],
        fixtures: [UITestFixture] = [],
        extraEnvironment: [String: String] = [:],
        perfLog: String? = nil
    ) -> XCUIApplication {
        let app = makeConfiguredApp(
            profile: profile,
            extraArgs: extraArgs,
            fixtures: fixtures,
            extraEnvironment: extraEnvironment,
            perfLog: perfLog
        )
        currentApp = app
        // A prior file-importer interaction can leave iOS 26's Files
        // document-picker process in front of the target app.  In that state
        // XCTest can still query the target app's background AX tree, but no
        // target control is hittable; `app.activate()` alone does not dismiss
        // the system presentation.  Terminate only this exact system app so
        // the launch seam remains hermetic without touching other Simulator
        // state or using coordinate-based dismissal.
        XCUIApplication(bundleIdentifier: "com.apple.DocumentsApp").terminate()
        app.launch()
        // `launch()` can still expose the app's background AX tree while a
        // system presentation is settling; explicitly activate the test
        // application before resolving any selectors.
        app.activate()
        dismissStaleDocumentPicker(in: app)
        return app
    }

    private func dismissStaleDocumentPicker(in app: XCUIApplication) {
        let pickerMarker = app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "DOC.")
        ).firstMatch
        guard pickerMarker.waitUntilExists(timeout: 2) else { return }

        let cancelButton = app.buttons.matching(
            NSPredicate(format: "label == %@ OR label == %@", "Cancel", "取消")
        ).firstMatch
        guard cancelButton.waitUntilExists(timeout: 2) else {
            XCTFail("stale document picker exposed DOC.* controls but no localized cancel button")
            return
        }
        cancelButton.tapWhenReady(timeout: 5)
        XCTAssertTrue(
            pickerMarker.waitUntilGone(timeout: 5),
            "stale document picker remained after semantic cancellation"
        )
    }

    @discardableResult
    func launchIsolatedApp(
        extraArgs: [String] = [],
        fixtures: [UITestFixture] = [],
        extraEnvironment: [String: String] = [:],
        perfLog: String? = nil
    ) -> XCUIApplication {
        // Hermetic by default: an isolated world must never reach the real
        // backend — a live catalog sync reconciles seeded series away, and a
        // fake token's 401 wipes local data. An unreachable address fails with
        // connection-refused (not 401), so nothing is torn down. Callers that
        // genuinely need a server pass their own KG_UI_TEST_SERVER_URL.
        var environment = extraEnvironment
        if environment["KG_UI_TEST_SERVER_URL"] == nil {
            environment["KG_UI_TEST_SERVER_URL"] = "http://127.0.0.1:9"
        }
        return launchApp(
            extraArgs: ["-appLaunchProfile", "ui-smoke", "-isolatedAuthSession"] + extraArgs,
            fixtures: fixtures,
            extraEnvironment: environment,
            perfLog: perfLog
        )
    }

    @discardableResult
    func step<T>(
        _ name: String,
        app: XCUIApplication,
        file: StaticString = #filePath,
        line: UInt = UInt(#line),
        _ action: () throws -> T
    ) throws -> T {
        do {
            let value = try action()
            captureStep(name, app: app, file: file, line: line)
            return value
        } catch {
            captureStep("\(name)-failed", app: app, file: file, line: line)
            throw error
        }
    }

    func attachDiagnostics(
        for app: XCUIApplication,
        namePrefix: String = "UITest Failure"
    ) {
        add(XCTAttachment(screenshot: app.screenshot()).named("\(namePrefix) Screenshot"))
        // Do not request app.debugDescription here.  On iOS 26, the Reader's
        // Readium/WebKit accessibility tree can be enormous; requesting the
        // complete remote snapshot after a failure can keep xcodebuild alive
        // for minutes and hide the original assertion.  The failure screenshot
        // and the bounded summaries below are the compact run-receipt contract.
        add(XCTAttachment(
            string: "Full accessibility-tree dump intentionally omitted; use the failure screenshot and focused query output."
        ).named("\(namePrefix) Diagnostics Policy"))
        add(XCTAttachment(string: currentTabSummary(in: app)).named("\(namePrefix) Current Tab"))
        add(XCTAttachment(string: boundedElementSummary(in: app)).named("\(namePrefix) Visible Elements"))
    }

    func captureStep(
        _ name: String,
        assetID: String? = nil,
        app: XCUIApplication,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        screenshotStepIndex += 1
        let screenshot = app.screenshot()
        let safeName = name
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let stepName = String(
            format: "%02d-%@-%@",
            screenshotStepIndex,
            nameForEvidenceArtifact,
            safeName.isEmpty ? "step" : safeName
        )
        add(XCTAttachment(screenshot: screenshot).named("Step \(stepName)"))

        guard let dir = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !dir.isEmpty else { return }
        let outputName = assetID ?? stepName
        let safeAssetID = outputName
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let url = URL(fileURLWithPath: dir).appendingPathComponent("\(safeAssetID).png")
        lastCapturedScreenshotPath = url.path
        do {
            try FileManager.default.createDirectory(
                at: URL(fileURLWithPath: dir),
                withIntermediateDirectories: true
            )
            guard !FileManager.default.fileExists(atPath: url.path) else {
                XCTFail("UI evidence screenshot collision: \(url.path)")
                return
            }
            try screenshot.pngRepresentation.write(to: url, options: .withoutOverwriting)
        } catch {
            XCTContext.runActivity(named: "Failed to write UI step screenshot") { activity in
                activity.add(XCTAttachment(string: "\(url.path): \(error)").named("Screenshot Write Error"))
            }
        }
    }

    private var nameForEvidenceArtifact: String {
        let safe = name
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return safe.isEmpty ? String(describing: type(of: self)) : safe
    }

    func attachText(_ text: String, named name: String) {
        add(XCTAttachment(string: text).named(name))
    }

    func currentTabSummary(in app: XCUIApplication) -> String {
        // 用 Selected accessibility trait 判定；iOS 26.4 sim 上觀察到
        // button.value 不帶 "selected"/"1" 字串，嗅探 value 會誤報 <no selected tab>。
        for index in 0..<6 {
            let candidate = app.tabBars.buttons.element(boundBy: index)
            guard candidate.exists else { break }
            if candidate.isSelected { return candidate.label }
        }
        return "<no selected tab>"
    }

    private func boundedElementSummary(in app: XCUIApplication) -> String {
        // Query only small, high-signal collections.  In particular, never
        // enumerate descendants(matching: .any), which includes the full
        // Readium document tree on a failed Reader test.
        let candidates: [(String, XCUIElementQuery)] = [
            ("buttons", app.buttons),
            ("textFields", app.textFields),
            ("sliders", app.sliders),
            ("tabBarButtons", app.tabBars.buttons),
        ]
        let lines = candidates.flatMap { kind, query in
            (0..<6).compactMap { index -> String? in
                let element = query.element(boundBy: index)
                guard element.exists else { return nil }
                let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
                let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !label.isEmpty || !identifier.isEmpty else { return nil }
                return "\(kind) | \(identifier.isEmpty ? "-" : identifier) | \(label.isEmpty ? "-" : label)"
            }
        }
        return lines.isEmpty ? "<no bounded labelled controls>" : lines.joined(separator: "\n")
    }
}

private extension XCUIElement.ElementType {
    var summaryName: String {
        switch self {
        case .button: return "button"
        case .cell: return "cell"
        case .collectionView: return "collectionView"
        case .image: return "image"
        case .link: return "link"
        case .navigationBar: return "navigationBar"
        case .other: return "other"
        case .scrollView: return "scrollView"
        case .staticText: return "staticText"
        case .tabBar: return "tabBar"
        case .textField: return "textField"
        default: return "\(self.rawValue)"
        }
    }
}

// `fileprivate` 到 2026-08-09 為止都夠用，因為只有本檔在附加診斷。
// `TodayReviewFrontBudgetUITests` 起，量測型 UI 測試也要替附件命名。
extension XCTAttachment {
    func named(_ name: String) -> XCTAttachment {
        self.name = name
        self.lifetime = .keepAlways
        return self
    }
}
