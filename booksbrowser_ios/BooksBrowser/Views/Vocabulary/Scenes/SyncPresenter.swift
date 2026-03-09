import SwiftUI

struct SyncPresenterState {
    let isLoggedIn: Bool
    let hasProAccess: Bool
    let isConnected: Bool
    let phase: SyncPhase
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
                .padding(.top, vocabSkin.metrics.overlayHorizontalInset + 12)
                .padding(.bottom, vocabSkin.metrics.reviewFoldPadding)
                .animation(AppMotion.phaseChange, value: state.phase)

            if state.isLoggedIn && state.hasProAccess && !state.steps.isEmpty {
                VocabCard(padding: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(state.steps.enumerated()), id: \.element.id) { index, step in
                            stepRow(step)

                            if index < state.steps.count - 1 {
                                Divider()
                                    .padding(.leading, vocabSkin.metrics.overlayHorizontalInset + 12)
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
                Text(state.summaryText)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(state.phase == .failed ? vocabSkin.palette.destructive : vocabSkin.palette.secondaryText)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, vocabSkin.metrics.summaryHorizontalInset)
                    .padding(.bottom, vocabSkin.metrics.reviewToolbarVerticalInset)
            }

            actionArea
                .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.overlayVerticalInset)
        }
        .vocabCanvasBackground()
        .navigationTitle("同步")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if state.phase == .ready || state.phase == .completed || state.phase == .failed {
                    Button("關閉") { dismiss() }
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
                title: "尚未登入帳號",
                description: "登入後即可將您的生詞庫同步至雲端知識庫。"
            )
        } else if !state.hasProAccess {
            VocabStatusHero(
                systemImage: "sparkles.rectangle.stack",
                tone: vocabSkin.palette.accent,
                title: "同步需 Pro",
                description: "升級後即可將待收錄生詞同步到雲端與知識庫。"
            )
        } else {
            switch state.phase {
            case .ready:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: state.pendingCount == 0
                        ? "強制同步到知識庫"
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
                    title: "同步中…"
                ) {
                    ProgressView()
                        .controlSize(.large)
                }
                .transition(.blurReplace)
            case .completed:
                VocabStatusHero(
                    systemImage: "checkmark.circle.fill",
                    tone: vocabSkin.palette.success,
                    title: "同步完成"
                )
                .transition(.blurReplace)
            case .failed:
                VocabStatusHero(
                    systemImage: "exclamationmark.triangle.fill",
                    tone: vocabSkin.palette.destructive,
                    title: "同步失敗"
                )
                .transition(.blurReplace)
            }
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
                        Label("開始同步", systemImage: "arrow.triangle.2.circlepath")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.primary))
                    .disabled(!state.isConnected)

                    if !state.isConnected {
                        Text("KG 伺服器未連線")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                } else {
                    Button(action: state.isLoggedIn ? onShowPaywall : onShowSettings) {
                        Text(state.isLoggedIn ? "升級為 Pro" : "前往設定登入")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.neutral))
                }
            case .running:
                Button(role: .cancel, action: onCancel) {
                    Text("取消")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
            case .completed:
                Button("完成") { dismiss() }
                    .frame(maxWidth: .infinity)
                    .buttonStyle(.vocabAction(.primary))
            case .failed:
                Button(action: onPrimaryAction) {
                    Label("重試", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.warning))
            }
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
