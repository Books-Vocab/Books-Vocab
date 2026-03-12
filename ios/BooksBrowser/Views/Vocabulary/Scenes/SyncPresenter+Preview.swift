import SwiftUI

// MARK: - Step Duration View

struct StepDurationView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let step: PipelineStep

    var body: some View {
        if let start = step.startTime {
            if let end = step.endTime {
                Text(formatDuration(end.timeIntervalSince(start)))
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            } else {
                TimelineView(.periodic(from: .now, by: 0.1)) { timeline in
                    Text(formatDuration(timeline.date.timeIntervalSince(start)))
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(step.status == .retry ? vocabSkin.palette.retry : vocabSkin.palette.secondaryText)
                }
            }
        }
    }

    private func formatDuration(_ duration: TimeInterval) -> String {
        String(format: "%.1fs", duration)
    }
}

// MARK: - Preview Data

private enum SyncPresenterPreviewData {
    static let baseSteps: [PipelineStep] = [
        .init(
            id: "upload_add",
            label: "上傳新單字",
            status: .done,
            current: 12,
            total: 12,
            detail: "10 新增, 2 已存在",
            startTime: Date().addingTimeInterval(-9),
            endTime: Date().addingTimeInterval(-6.4)
        ),
        .init(
            id: "trigger",
            label: "觸發背景 AI 處理",
            status: .running,
            current: 1,
            total: 1,
            detail: "背景管線執行中",
            startTime: Date().addingTimeInterval(-2.2),
            endTime: nil
        ),
        .init(
            id: "pull",
            label: "下載知識庫至本地",
            status: .waiting,
            current: 0,
            total: 0,
            detail: "",
            startTime: nil,
            endTime: nil
        )
    ]

    static let ready = SyncPresenterState(
        isLoggedIn: true,

        isConnected: true,
        phase: .ready,
        failureKind: nil,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: [],
        summaryText: "這次會把待新增與待刪除的變更同步到雲端知識庫。"
    )

    static let running = SyncPresenterState(
        isLoggedIn: true,

        isConnected: true,
        phase: .running,
        failureKind: nil,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: baseSteps,
        summaryText: "請保持網路連線，系統會自動更新本地知識庫。"
    )

    static let failed = SyncPresenterState(
        isLoggedIn: true,

        isConnected: false,
        phase: .failed,
        failureKind: .full,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: [
            .init(
                id: "upload_add",
                label: "上傳新單字",
                status: .error,
                current: 4,
                total: 12,
                detail: "伺服器逾時，請稍後再試",
                startTime: Date().addingTimeInterval(-12),
                endTime: Date().addingTimeInterval(-9)
            )
        ],
        summaryText: "同步在上傳階段失敗，請檢查伺服器狀態後重試。"
    )

    static let partialFailed = SyncPresenterState(
        isLoggedIn: true,

        isConnected: true,
        phase: .failed,
        failureKind: .partial,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: [
            .init(
                id: "upload_delete",
                label: "刪除 KG 單字",
                status: .error,
                current: 1,
                total: 2,
                detail: "部分失敗: obscure",
                startTime: Date().addingTimeInterval(-14),
                endTime: Date().addingTimeInterval(-12)
            ),
            .init(
                id: "upload_add",
                label: "上傳新單字",
                status: .done,
                current: 12,
                total: 12,
                detail: "10 新增, 2 已存在",
                startTime: Date().addingTimeInterval(-12),
                endTime: Date().addingTimeInterval(-8)
            ),
            .init(
                id: "trigger",
                label: "觸發背景 AI 處理",
                status: .done,
                current: 1,
                total: 1,
                detail: "已交由伺服器背景處理",
                startTime: Date().addingTimeInterval(-8),
                endTime: Date().addingTimeInterval(-6)
            ),
            .init(
                id: "pull",
                label: "下載知識庫至本地",
                status: .done,
                current: 1,
                total: 1,
                detail: "本地知識庫已建立完成",
                startTime: Date().addingTimeInterval(-6),
                endTime: Date().addingTimeInterval(-3)
            )
        ],
        summaryText: "部分項目未成功同步，可直接再次重試。"
    )

    static let signedOut = SyncPresenterState(
        isLoggedIn: false,

        isConnected: true,
        phase: .ready,
        failureKind: nil,
        pendingCount: 0,
        addCount: 0,
        deleteCount: 0,
        steps: [],
        summaryText: ""
    )

    static let completed = SyncPresenterState(
        isLoggedIn: true,

        isConnected: true,
        phase: .completed,
        failureKind: nil,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: baseSteps,
        summaryText: "同步完成，所有變更已成功上傳。"
    )
}

#Preview("Sync / Ready") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.ready,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}

#Preview("Sync / Running") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.running,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}

#Preview("Sync / Failed") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.failed,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}

#Preview("Sync / Partial Failure") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.partialFailed,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}

#Preview("Sync / Signed Out") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.signedOut,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}

#Preview("Sync / Completed") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.completed,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},

            )
        }
    }
}
