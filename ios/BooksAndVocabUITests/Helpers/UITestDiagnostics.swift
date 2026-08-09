import XCTest

class UITestCase: XCTestCase {
    private(set) var currentApp: XCUIApplication?
    private var screenshotStepIndex = 0

    override func setUpWithError() throws {
        continueAfterFailure = false
        screenshotStepIndex = 0
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
        app.launch()
        return app
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
        add(XCTAttachment(string: app.debugDescription).named("\(namePrefix) Debug Description"))
        add(XCTAttachment(string: currentTabSummary(in: app)).named("\(namePrefix) Current Tab"))
        add(XCTAttachment(string: visibleElementSummary(in: app)).named("\(namePrefix) Visible Elements"))
    }

    func captureStep(
        _ name: String,
        app: XCUIApplication,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        screenshotStepIndex += 1
        let screenshot = app.screenshot()
        let safeName = name
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let stepName = String(format: "%02d-%@", screenshotStepIndex, safeName.isEmpty ? "step" : safeName)
        add(XCTAttachment(screenshot: screenshot).named("Step \(stepName)"))

        guard let dir = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !dir.isEmpty else { return }
        let url = URL(fileURLWithPath: dir).appendingPathComponent("\(stepName).png")
        do {
            try FileManager.default.createDirectory(
                at: URL(fileURLWithPath: dir),
                withIntermediateDirectories: true
            )
            try screenshot.pngRepresentation.write(to: url)
        } catch {
            XCTContext.runActivity(named: "Failed to write UI step screenshot") { activity in
                activity.add(XCTAttachment(string: "\(url.path): \(error)").named("Screenshot Write Error"))
            }
        }
    }

    func attachText(_ text: String, named name: String) {
        add(XCTAttachment(string: text).named(name))
    }

    func currentTabSummary(in app: XCUIApplication) -> String {
        // 用 Selected accessibility trait 判定；iOS 26.4 sim 上觀察到
        // button.value 不帶 "selected"/"1" 字串，嗅探 value 會誤報 <no selected tab>。
        let selected = app.tabBars.buttons.allElementsBoundByIndex.first(where: \.isSelected)
        return selected?.label ?? "<no selected tab>"
    }

    private func visibleElementSummary(in app: XCUIApplication, limit: Int = 24) -> String {
        let visible = app.descendants(matching: .any).allElementsBoundByIndex
            .filter { $0.exists && !$0.frame.isEmpty && !$0.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .prefix(limit)

        if visible.isEmpty {
            return "<no visible labelled elements>"
        }

        return visible.enumerated().map { index, element in
            let id = element.identifier.isEmpty ? "-" : element.identifier
            let label = element.label.replacingOccurrences(of: "\n", with: " ")
            return "\(index + 1). \(element.elementType.summaryName) | \(id) | \(label)"
        }.joined(separator: "\n")
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
