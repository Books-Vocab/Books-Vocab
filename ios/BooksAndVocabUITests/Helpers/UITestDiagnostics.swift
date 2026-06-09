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
        extraEnvironment: [String: String] = [:],
        perfLog: String? = nil
    ) -> XCUIApplication {
        let app = makeConfiguredApp(
            profile: profile,
            extraArgs: extraArgs,
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
        extraEnvironment: [String: String] = [:],
        perfLog: String? = nil
    ) -> XCUIApplication {
        launchApp(
            extraArgs: ["-appLaunchProfile", "ui-smoke", "-isolatedAuthSession"] + extraArgs,
            extraEnvironment: extraEnvironment,
            perfLog: perfLog
        )
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

    func currentTabSummary(in app: XCUIApplication) -> String {
        let selected = app.tabBars.buttons.allElementsBoundByIndex.first(where: { button in
            let value = String(describing: button.value ?? "")
            return value.localizedCaseInsensitiveContains("selected") || value == "1"
        })
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

private extension XCTAttachment {
    func named(_ name: String) -> XCTAttachment {
        self.name = name
        self.lifetime = .keepAlways
        return self
    }
}
