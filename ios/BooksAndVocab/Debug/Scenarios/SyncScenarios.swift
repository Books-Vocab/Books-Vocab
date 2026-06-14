#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SyncPresenter` — the vocabulary sync overlay.
///
/// 故意完全不接 `SyncCoordinator`（其 init 為 @MainActor 且會跑真實 pipeline）。
/// `SyncPresenterState` 由 UI World `syncPresenter.*` seed 物化，讓 ready /
/// running / completed / failed(.partial/full) 狀態與 pending rows / steps 同源。
/// `SyncPresenter` 用到 `.navigationTitle` / `.toolbar` / `dismiss`，故每個 scenario
/// 包一層 NavigationStack 提供導覽容器。
enum SyncScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Sync") {
            Scenario("Ready · pending rows", layout: .fill) {
                presenter(fixtureID: .ready)
            }
            Scenario("Running · steps in flight", layout: .fill) {
                presenter(fixtureID: .running)
            }
            Scenario("Completed", layout: .fill) {
                presenter(fixtureID: .completed)
            }
            Scenario("Failed · partial", layout: .fill) {
                presenter(fixtureID: .partialFailure)
            }
            Scenario("Failed · full error", layout: .fill) {
                presenter(fixtureID: .fullFailure)
            }
        }
    }

    // MARK: - Presenter wrapper

    private static func presenter(fixtureID: UIWorldSyncPresenterFixtureID) -> some View {
        let seed = FixtureDatasetStore.requireSyncPresenterSeed(for: fixtureID)
        return AppThemeContainer {
            NavigationStack {
                SyncPresenter(
                    state: state(from: seed, fixtureID: fixtureID),
                    onPrimaryAction: {},
                    onCancel: {},
                    onShowSettings: {},
                    onPendingRowTapped: { _ in },
                    onPendingActionTapped: { _ in }
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - Materialization

    private static func state(
        from seed: UIWorldSyncPresenterSeed,
        fixtureID: UIWorldSyncPresenterFixtureID
    ) -> SyncPresenterState {
        precondition(
            seed.pendingCount == seed.addCount + seed.deleteCount,
            "UI World syncPresenter.\(fixtureID.rawValue) pendingCount must equal addCount + deleteCount"
        )
        if seed.phase == "ready" {
            precondition(
                seed.pendingRows.count == seed.pendingCount,
                "UI World syncPresenter.\(fixtureID.rawValue) ready pendingRows must equal pendingCount"
            )
        }
        return SyncPresenterState(
            isLoggedIn: seed.isLoggedIn,
            isConnected: seed.isConnected,
            phase: phase(seed.phase, fixtureID: fixtureID),
            failureKind: seed.failureKind.map { failureKind($0, fixtureID: fixtureID) },
            pendingCount: seed.pendingCount,
            addCount: seed.addCount,
            deleteCount: seed.deleteCount,
            steps: seed.steps.map { step($0, fixtureID: fixtureID) },
            summaryText: seed.summaryText,
            pendingRows: seed.pendingRows.map { pendingRow($0, fixtureID: fixtureID) }
        )
    }

    private static func pendingRow(
        _ seed: UIWorldSyncPresenterSeed.PendingRow,
        fixtureID: UIWorldSyncPresenterFixtureID
    ) -> SyncPresenterState.RowItem {
        guard let id = UUID(uuidString: seed.id) else {
            preconditionFailure("UI World syncPresenter.\(fixtureID.rawValue) pending row id must be a UUID: \(seed.id)")
        }
        return SyncPresenterState.RowItem(
            id: id,
            row: WordRow.ViewData(
                id: id,
                word: seed.word,
                wordTone: tone(seed.wordTone, fixtureID: fixtureID),
                isStrikethrough: seed.isStrikethrough,
                partOfSpeech: seed.partOfSpeech,
                translation: seed.translation,
                bookTitle: nil,
                chapterTitle: nil,
                difficultyTier: nil,
                reviewProgress: nil,
                leadingSystemImage: nil,
                leadingTone: nil,
                trailingLabel: nil,
                trailingTone: nil,
                statusText: nil,
                statusTone: nil
            ),
            actionSystemImage: seed.actionSystemImage,
            actionTone: tone(seed.actionTone, fixtureID: fixtureID),
            actionAccessibilityLabel: seed.actionAccessibilityLabel
        )
    }

    private static func step(_ seed: UIWorldSyncPresenterSeed.Step, fixtureID: UIWorldSyncPresenterFixtureID) -> PipelineStep {
        PipelineStep(
            id: seed.id,
            label: seed.label,
            status: stepStatus(seed.status, fixtureID: fixtureID),
            current: seed.current,
            total: seed.total,
            detail: seed.detail
        )
    }

    private static func phase(_ raw: String, fixtureID: UIWorldSyncPresenterFixtureID) -> SyncPhase {
        switch raw {
        case "ready": return .ready
        case "running": return .running
        case "completed": return .completed
        case "failed": return .failed
        default: preconditionFailure("UI World syncPresenter.\(fixtureID.rawValue) has unknown phase \(raw)")
        }
    }

    private static func failureKind(_ raw: String, fixtureID: UIWorldSyncPresenterFixtureID) -> SyncFailureKind {
        switch raw {
        case "partial": return .partial
        case "full": return .full
        case "cancelled": return .cancelled
        default: preconditionFailure("UI World syncPresenter.\(fixtureID.rawValue) has unknown failureKind \(raw)")
        }
    }

    private static func stepStatus(_ raw: String, fixtureID: UIWorldSyncPresenterFixtureID) -> PipelineStep.StepStatus {
        switch raw {
        case "waiting": return .waiting
        case "running": return .running
        case "retry": return .retry
        case "done": return .done
        case "skipped": return .skipped
        case "error": return .error
        default: preconditionFailure("UI World syncPresenter.\(fixtureID.rawValue) has unknown step status \(raw)")
        }
    }

    private static func tone(_ raw: String, fixtureID: UIWorldSyncPresenterFixtureID) -> WordRow.ViewData.Tone {
        switch raw {
        case "primary": return .primary
        case "secondary": return .secondary
        case "tertiary": return .tertiary
        case "quaternary": return .quaternary
        case "destructive": return .destructive
        case "reviewDue": return .reviewDue
        default: preconditionFailure("UI World syncPresenter.\(fixtureID.rawValue) has unknown tone \(raw)")
        }
    }
}
#endif
