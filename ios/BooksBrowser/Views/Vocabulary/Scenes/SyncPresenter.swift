import SwiftUI

struct SyncPresenterState {
    let isLoggedIn: Bool
    let hasProAccess: Bool
    let isConnected: Bool
    let phase: SyncPhase
    let failureKind: SyncFailureKind?
    let pendingCount: Int
    let addCount: Int
    let deleteCount: Int
    let steps: [PipelineStep]
    let summaryText: String
}

struct SyncPresenter: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin

    let state: SyncPresenterState
    let onPrimaryAction: () -> Void
    let onCancel: () -> Void
    let onShowSettings: () -> Void
    let onShowPaywall: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            headerView
                .padding(.top, vocabSkin.metrics.syncOverlayInset)
                .padding(.bottom, vocabSkin.metrics.reviewFoldPadding)
                .animation(AppMotion.phaseChange, value: state.phase)

            if state.isLoggedIn && state.hasProAccess && !state.steps.isEmpty {
                VocabCard(padding: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(state.steps.enumerated()), id: \.element.id) { index, step in
                            stepRow(step)

                            if index < state.steps.count - 1 {
                                Divider()
                                    .padding(.leading, vocabSkin.metrics.syncOverlayInset)
                            }
                        }
                    }
                    .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)
                    .padding(.vertical, vocabSkin.metrics.reviewTopBarBottomInset)
                }
                .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
            }

            Spacer()

            if !state.summaryText.isEmpty {
                summaryCard
                    .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
                    .padding(.bottom, vocabSkin.metrics.reviewToolbarVerticalInset)
                    .transition(.feedbackBadge)
            }

            actionArea
                .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.overlayVerticalInset)
        }
        .vocabCanvasBackground()
        .navigationTitle("同步".localized)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .sensoryFeedback(.success, trigger: state.phase == .completed)
        .sensoryFeedback(.warning, trigger: state.failureKind == .partial)
        .sensoryFeedback(.error, trigger: state.failureKind == .full || state.failureKind == .cancelled)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if state.phase == .ready || state.phase == .completed || state.phase == .failed {
                    Button("關閉".localized) { dismiss() }
                }
            }
        }
    }

    @ViewBuilder
    private var headerView: some View {
        if !state.isLoggedIn {
            VocabStatusHero(
                systemImage: "person.crop.circle.badge.exclamationmark",
                tone: vocabSkin.palette.tertiaryText,
                title: "尚未登入帳號".localized,
                description: "登入後即可將您的生詞庫同步至雲端知識庫。".localized
            )
        } else if !state.hasProAccess {
            VocabStatusHero(
                systemImage: "sparkles.rectangle.stack",
                tone: vocabSkin.palette.accent,
                title: "同步需 Pro".localized,
                description: "升級後即可將待收錄生詞同步到雲端與知識庫。".localized
            )
        } else {
            switch state.phase {
            case .ready:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: state.pendingCount == 0
                        ? "強制同步到知識庫".localized
                        : L10n.format("%@ 個待處理動作", "\(state.pendingCount)")
                ) {
                    HStack(spacing: vocabSkin.spacing.inlineGap) {
                        if state.addCount > 0 {
                            VocabToneChip(
                                text: L10n.format("%@ 新增", "\(state.addCount)"),
                                tone: vocabSkin.palette.success
                            )
                        }
                        if state.deleteCount > 0 {
                            VocabToneChip(
                                text: L10n.format("%@ 刪除", "\(state.deleteCount)"),
                                tone: vocabSkin.palette.destructive
                            )
                        }
                    }
                }
                .transition(.blurReplace)
            case .running:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: "同步中…".localized
                ) {
                    ProgressView()
                        .controlSize(.large)
                }
                .transition(.blurReplace)
            case .completed:
                VocabStatusHero(
                    systemImage: "checkmark.circle.fill",
                    tone: vocabSkin.palette.success,
                    title: "同步完成".localized
                )
                .transition(.blurReplace)
            case .failed:
                failedHero
                .transition(.blurReplace)
            }
        }
    }

    @ViewBuilder
    private var failedHero: some View {
        switch state.failureKind {
        case .partial:
            VocabStatusHero(
                systemImage: "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90",
                tone: vocabSkin.palette.warning,
                title: "部分同步完成".localized,
                description: "已完成的步驟會保留，失敗項目可直接重試。".localized
            )
        case .cancelled:
            VocabStatusHero(
                systemImage: "pause.circle.fill",
                tone: vocabSkin.palette.warning,
                title: "同步已取消".localized,
                description: "目前進度已停止，可在準備好後重新開始。".localized
            )
        default:
            VocabStatusHero(
                systemImage: "exclamationmark.triangle.fill",
                tone: vocabSkin.palette.destructive,
                title: "同步失敗".localized,
                description: "請檢查網路、登入狀態或伺服器健康後再試。".localized
            )
        }
    }

    private func stepRow(_ step: PipelineStep) -> some View {
        VocabTimelineRow(
            title: step.label,
            titleTone: step.status == .waiting ? vocabSkin.palette.tertiaryText : vocabSkin.palette.primaryText,
            detail: step.status == .waiting ? nil : step.detail,
            detailTone: detailColor(for: step.status)
        ) {
            statusSymbol(for: step.status)
        } trailing: {
            HStack(spacing: 8) {
                if step.status == .running && step.total > 0 {
                    Text("\(step.current)/\(step.total)")
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .contentTransition(.numericText())
                        .animation(AppMotion.feedbackPulse, value: step.current)
                }

                StepDurationView(step: step)
            }
        }
    }

    private var actionArea: some View {
        VStack(spacing: 8) {
            switch state.phase {
            case .ready:
                if state.isLoggedIn && state.hasProAccess {
                    Button(action: onPrimaryAction) {
                        Label("開始同步".localized, systemImage: "arrow.triangle.2.circlepath")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.primary))
                    .disabled(!state.isConnected)

                    if !state.isConnected {
                        Text("KG 伺服器未連線".localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                } else {
                    Button(action: state.isLoggedIn ? onShowPaywall : onShowSettings) {
                        Text(state.isLoggedIn ? "升級為 Pro".localized : "前往設定登入".localized)
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.neutral))
                }
            case .running:
                Button(role: .cancel, action: onCancel) {
                    Text("取消".localized)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
            case .completed:
                Button("完成".localized) { dismiss() }
                    .frame(maxWidth: .infinity)
                    .buttonStyle(.vocabAction(.primary))
            case .failed:
                Button(action: onPrimaryAction) {
                    Label(state.failureKind == .partial ? "重試失敗項目".localized : "重試".localized, systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(state.failureKind == .full ? .warning : .neutral))
            }
        }
    }

    private var summaryCard: some View {
        VocabStateMessageCard(
            title: summaryTitle,
            systemImage: summaryIcon,
            description: state.summaryText
        )
    }

    private var summaryTitle: String {
        switch state.failureKind {
        case .partial:
            return "有些項目需要再試一次".localized
        case .cancelled:
            return "同步在中途停止".localized
        case .full:
            return "同步沒有完成".localized
        case nil:
            return state.phase == .completed ? "同步完成".localized : "同步摘要".localized
        }
    }

    private var summaryIcon: String {
        switch state.failureKind {
        case .partial:
            return "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90"
        case .cancelled:
            return "pause.circle"
        case .full:
            return "exclamationmark.triangle.fill"
        case nil:
            return state.phase == .completed ? "checkmark.circle.fill" : "text.alignleft"
        }
    }

    private func detailColor(for status: PipelineStep.StepStatus) -> Color {
        switch status {
        case .error:
            return vocabSkin.palette.destructive
        case .retry:
            return vocabSkin.palette.retry
        default:
            return vocabSkin.palette.secondaryText
        }
    }

    @ViewBuilder
    private func statusSymbol(for status: PipelineStep.StepStatus) -> some View {
        switch status {
        case .waiting:
            Image(systemName: "circle")
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        case .running:
            ProgressView()
                .controlSize(.small)
        case .retry:
            Image(systemName: "arrow.triangle.2.circlepath")
                .symbolEffect(.scale.up, options: .repeating)
                .foregroundStyle(vocabSkin.palette.retry)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(vocabSkin.palette.success)
                .symbolEffect(.bounce)
        case .skipped:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(vocabSkin.palette.secondaryText)
        case .error:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(vocabSkin.palette.destructive)
        }
    }
}

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
        hasProAccess: true,
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
        hasProAccess: true,
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
        hasProAccess: true,
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
        hasProAccess: true,
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
        hasProAccess: false,
        isConnected: true,
        phase: .ready,
        failureKind: nil,
        pendingCount: 0,
        addCount: 0,
        deleteCount: 0,
        steps: [],
        summaryText: ""
    )

    static let noPro = SyncPresenterState(
        isLoggedIn: true,
        hasProAccess: false,
        isConnected: true,
        phase: .ready,
        failureKind: nil,
        pendingCount: 14,
        addCount: 12,
        deleteCount: 2,
        steps: [],
        summaryText: ""
    )

    static let completed = SyncPresenterState(
        isLoggedIn: true,
        hasProAccess: true,
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
                onShowPaywall: {}
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
                onShowPaywall: {}
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
                onShowPaywall: {}
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
                onShowPaywall: {}
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
                onShowPaywall: {}
            )
        }
    }
}

#Preview("Sync / No Pro") {
    AppThemeContainer {
        NavigationStack {
            SyncPresenter(
                state: SyncPresenterPreviewData.noPro,
                onPrimaryAction: {},
                onCancel: {},
                onShowSettings: {},
                onShowPaywall: {}
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
                onShowPaywall: {}
            )
        }
    }
}
