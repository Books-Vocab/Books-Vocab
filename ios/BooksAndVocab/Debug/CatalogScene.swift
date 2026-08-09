#if DEBUG && targetEnvironment(simulator) && canImport(Playbook)
import Foundation
import Playbook
import PlaybookUI
import SwiftUI
import UIKit

/// Agent-only UI workbench. UI World supplies structured state; Playbook only
/// supplies opt-in scenarios that are useful while developing or debugging UI.
/// A new production view does not have to register here.
struct CatalogScene: View {
    private static let playbook = buildPlaybook()
    private static let scenarios = CatalogAgentContract.scenarios(in: playbook)
    private let launch = CatalogAgentContract.launchConfiguration()

    @ViewBuilder
    var body: some View {
        if launch.indexOnly {
            Color.clear
                .background(CatalogAgentWindowReporter {
                    CatalogAgentContract.reportReady(
                        session: launch.session,
                        scenarios: Self.scenarios.map(\.descriptor)
                    )
                })
        } else if let requested = launch.scenarioID {
            if let selected = Self.scenarios.first(where: { $0.id == requested }) {
                CatalogAgentScenarioHost(
                    scenario: selected.scenario,
                    session: launch.session,
                    descriptor: selected.descriptor,
                    allScenarios: Self.scenarios.map(\.descriptor)
                )
                .ignoresSafeArea()
            } else {
                Text(verbatim: "Catalog scenario not found: \(requested)")
                    .background(CatalogAgentWindowReporter {
                        CatalogAgentContract.reportReady(
                            session: launch.session,
                            scenarios: Self.scenarios.map(\.descriptor),
                            error: "scenario-not-found",
                            requestedScenario: requested
                        )
                    })
            }
        } else {
            PlaybookCatalog(title: "KG UI Workbench", playbook: Self.playbook)
                .background(CatalogAgentWindowReporter {
                    CatalogAgentContract.reportReady(
                        session: launch.session,
                        scenarios: Self.scenarios.map(\.descriptor)
                    )
                })
        }
    }

    static func buildPlaybook() -> Playbook {
        let playbook = Playbook()
        let registrations: [(Playbook) -> Void] = [
            ReaderScenarios.register,
            NotebooksScenarios.register,
            NotebookListScenarios.register,
            VocabScenarios.register,
            WordDetailScenarios.register,
            PodcastPlayerScenarios.register,
            NotebookEditSheetScenarios.register,
            BannerScenarios.register,
            SyncScenarios.register,
            PaywallScenarios.register,
            WordEditScenarios.register,
            ArchivedVocabScenarios.register,
            CollocationExplainScenarios.register,
            KGVocabEmptyStateScenarios.register,
            VocabActivityHeatmapScenarios.register,
            VocabCalendarGridScenarios.register,
            VocabForecastScenarios.register,
            NotebookFilterChipScenarios.register,
            NotebookReviewActionBarScenarios.register,
            SelectionToolbarScenarios.register,
            PodcastSeriesHeroScenarios.register,
            PodcastShelfScenarios.register,
            PodcastSettingsPopoverScenarios.register,
            LoginSheetScenarios.register,
            VocabHighlightPickerScenarios.register,
            DeleteAccountSheetScenarios.register,
            TranslationLanguageSettingsScenarios.register,
            BookCardScenarios.register,
            VocabComponentScenarios.register,
            VocabShellComponentsScenarios.register,
            VocabShellChromeScenarios.register,
            VocabSceneShellScenarios.register,
            NotebookCoverScenarios.register,
            LinkReasonSheetScenarios.register,
            ReaderNotebookPickerScenarios.register,
            SubscriptionViewsScenarios.register,
            PodcastContinueCardScenarios.register,
            PodcastShelfCardsScenarios.register,
            SettingsActionsScenarios.register,
            SettingsSectionsScenarios.register,
            SettingsAccountSectionScenarios.register,
            ReviewCalendarScenarios.register,
            AppStartupRecoveryScenarios.register,
            VocabularyListViewScenarios.register,
            StatsViewScenarios.register,
            PodcastHomeViewScenarios.register,
            BookshelfViewScenarios.register,
            KnowledgeGraphViewScenarios.register,
            PDFReaderViewScenarios.register,
            SyncViewScenarios.register,
            NotebookListViewScenarios.register,
            PodcastEpisodeListViewScenarios.register,
            PodcastPlayerViewScenarios.register,
            NotebookCardEditorialCoverScenarios.register,
            KGVocabRowScenarios.register,
            KGVocabSearchScenarios.register,
            PodcastSentenceCellsScenarios.register,
            TodayReviewShortcutScenarios.register,
            ReviewFoldScenarios.register,
            SettingsAccountDetailScenarios.register,
            SettingsSubscriptionSectionScenarios.register,
            TodayReviewPhaseScenarios.register,
            ReaderChromeScenarios.register,
            SettingsScenarios.register,
            TodayReviewScenarios.register,
            WelcomeScenarios.register,
            ExploreViewScenarios.register,
            SharedDeckDetailViewScenarios.register,
        ]
        registrations.forEach { $0(playbook) }
        return playbook
    }
}

enum CatalogAgentContract {
    struct LaunchConfiguration {
        let session: String?
        let scenarioID: String?
        let indexOnly: Bool
    }

    struct ScenarioDescriptor: Encodable {
        let id: String
        let category: String
        let title: String
    }

    struct RegisteredScenario {
        let descriptor: ScenarioDescriptor
        let scenario: Scenario

        var id: String { descriptor.id }
    }

    private struct IndexDocument: Encodable {
        let schema = "kg.ios.catalog-agent.index.v1"
        let scenarios: [ScenarioDescriptor]
    }

    private struct ReadyDocument: Encodable {
        let schema = "kg.ios.catalog-agent.ready.v1"
        let session: String
        let status: String
        let renderer = "simulator-window"
        let scenario: ScenarioDescriptor?
        let requestedScenario: String?
        let error: String?
    }

    static func launchConfiguration(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> LaunchConfiguration {
        LaunchConfiguration(
            session: value(after: "-catalogAgentSession", in: arguments),
            scenarioID: value(after: "-catalogScenario", in: arguments),
            indexOnly: arguments.contains("-catalogIndexOnly")
        )
    }

    static func scenarios(in playbook: Playbook) -> [RegisteredScenario] {
        var registered: [RegisteredScenario] = []
        for store in playbook.stores {
            let category = store.category.rawValue
            registered.append(contentsOf: store.scenarios.map { scenario in
                let title = scenario.title.rawValue
                return RegisteredScenario(
                    descriptor: .init(
                        id: "\(category)/\(title)",
                        category: category,
                        title: title
                    ),
                    scenario: scenario
                )
            })
        }
        let duplicates = Dictionary(grouping: registered, by: \.id)
            .filter { $0.value.count > 1 }
            .keys
            .sorted()
        precondition(
            duplicates.isEmpty,
            "Duplicate Catalog scenario IDs: \(duplicates.joined(separator: ", "))"
        )
        return registered.sorted { $0.id.localizedStandardCompare($1.id) == .orderedAscending }
    }

    static func reportReady(
        session: String?,
        scenarios: [ScenarioDescriptor],
        selected: ScenarioDescriptor? = nil,
        error: String? = nil,
        requestedScenario: String? = nil
    ) {
        guard let session, isSafeSessionID(session) else { return }
        do {
            let directory = try sessionDirectory(session)
            try write(
                IndexDocument(scenarios: scenarios),
                to: directory.appendingPathComponent("index.json")
            )
            try write(
                ReadyDocument(
                    session: session,
                    status: error == nil ? "ok" : "error",
                    scenario: selected,
                    requestedScenario: requestedScenario,
                    error: error
                ),
                to: directory.appendingPathComponent("ready.json")
            )
        } catch {
            assertionFailure("Catalog agent readiness write failed: \(error)")
        }
    }

    private static func value(after flag: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(of: flag), arguments.indices.contains(index + 1) else {
            return nil
        }
        return arguments[index + 1]
    }

    private static func isSafeSessionID(_ value: String) -> Bool {
        value.range(of: #"^catalog-[A-Za-z0-9T-]+$"#, options: .regularExpression) != nil
    }

    private static func sessionDirectory(_ session: String) throws -> URL {
        let documents = try FileManager.default.url(
            for: .documentDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = documents
            .appendingPathComponent("catalog-agent", isDirectory: true)
            .appendingPathComponent(session, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private static func write<Value: Encodable>(_ value: Value, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(value).write(to: url, options: .atomic)
    }
}

private struct CatalogAgentScenarioHost: UIViewControllerRepresentable {
    let scenario: Scenario
    let session: String?
    let descriptor: CatalogAgentContract.ScenarioDescriptor
    let allScenarios: [CatalogAgentContract.ScenarioDescriptor]

    func makeUIViewController(context: Context) -> CatalogAgentScenarioViewController {
        let scenarioContext = ScenarioContext(
            snapshotWaiter: SnapshotWaiter(),
            isSnapshot: false,
            screenSize: currentScreenSize()
        )
        let controller = CatalogAgentScenarioViewController(context: scenarioContext, scenario: scenario)
        controller.onReady = {
            CatalogAgentContract.reportReady(
                session: session,
                scenarios: allScenarios,
                selected: descriptor
            )
        }
        return controller
    }

    func updateUIViewController(_ uiViewController: CatalogAgentScenarioViewController, context: Context) {}

    private func currentScreenSize() -> CGSize {
        (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.screen.bounds.size
            ?? CGSize(width: 440, height: 956)
    }
}

private final class CatalogAgentScenarioViewController: ScenarioViewController {
    var onReady: (() -> Void)?
    private var didReportReady = false

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !didReportReady else { return }
        didReportReady = true
        view.layoutIfNeeded()
        DispatchQueue.main.async { [weak self] in
            self?.onReady?()
        }
    }
}

private struct CatalogAgentWindowReporter: UIViewRepresentable {
    let onReady: () -> Void

    func makeUIView(context: Context) -> ReporterView {
        let view = ReporterView()
        view.onReady = onReady
        return view
    }

    func updateUIView(_ uiView: ReporterView, context: Context) {
        uiView.onReady = onReady
    }

    final class ReporterView: UIView {
        var onReady: (() -> Void)?
        private var didReportReady = false

        override func didMoveToWindow() {
            super.didMoveToWindow()
            guard window != nil, !didReportReady else { return }
            didReportReady = true
            DispatchQueue.main.async { [weak self] in
                self?.window?.layoutIfNeeded()
                self?.onReady?()
            }
        }
    }
}

#Preview {
    CatalogScene()
}
#endif
