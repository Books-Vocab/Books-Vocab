import XCTest

class UITestCase: XCTestCase {
    private(set) var currentApp: XCUIApplication?

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    override func tearDownWithError() throws {
        if let app = currentApp, let testRun, !testRun.hasSucceeded {
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

    func attachDiagnostics(
        for app: XCUIApplication,
        namePrefix: String = "UITest Failure"
    ) {
        add(XCTAttachment(screenshot: app.screenshot()).named("\(namePrefix) Screenshot"))
        add(XCTAttachment(string: app.debugDescription).named("\(namePrefix) Debug Description"))
        add(XCTAttachment(string: currentTabSummary(in: app)).named("\(namePrefix) Current Tab"))
        add(XCTAttachment(string: visibleElementSummary(in: app)).named("\(namePrefix) Visible Elements"))
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
