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
                .padding(.top, 32)
                .padding(.bottom, 24)
                .animation(.spring(response: 0.4, dampingFraction: 0.8), value: state.phase)

            if state.isLoggedIn && state.hasProAccess && !state.steps.isEmpty {
                VocabCard(padding: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(state.steps.enumerated()), id: \.element.id) { index, step in
                            stepRow(step)

                            if index < state.steps.count - 1 {
                                Divider()
                                    .padding(.leading, 32)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 6)
                }
                .padding(.horizontal, 20)
            }

            Spacer()

            if !state.summaryText.isEmpty {
                Text(state.summaryText)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(state.phase == .failed ? vocabSkin.palette.destructive : vocabSkin.palette.secondaryText)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 12)
            }

            actionArea
                .padding(.horizontal, 20)
                .padding(.bottom, 20)
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
            VStack(spacing: 12) {
                Image(systemName: "person.crop.circle.badge.exclamationmark")
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                Text("尚未登入帳號")
                    .font(vocabSkin.typography.sectionTitle)
                Text("登入後即可將您的生詞庫同步至雲端與 Mochi。")
                    .font(vocabSkin.typography.body)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .padding(.horizontal, 40)
            }
        } else if !state.hasProAccess {
            VStack(spacing: 12) {
                Image(systemName: "sparkles.rectangle.stack")
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(vocabSkin.palette.accent)
                Text("同步需 Pro")
                    .font(vocabSkin.typography.sectionTitle)
                Text("升級後即可將待收錄生詞同步到雲端、知識庫與 Mochi。")
                    .font(vocabSkin.typography.body)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .padding(.horizontal, 40)
            }
        } else {
            switch state.phase {
            case .ready:
                VStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)

                    if state.pendingCount == 0 {
                        Text("強制同步到 Mochi")
                            .font(vocabSkin.typography.sectionTitle)
                    } else {
                        VStack(spacing: 4) {
                            Text(L10n.format("%@ 個待處理動作", "\(state.pendingCount)"))
                                .font(vocabSkin.typography.sectionTitle)
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
                    }
                }
                .transition(.blurReplace)
            case .running:
                VStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.large)
                    Text("同步中…")
                        .font(vocabSkin.typography.sectionTitle)
                }
                .transition(.blurReplace)
            case .completed:
                VStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.success)
                        .symbolEffect(.bounce)
                    Text("同步完成")
                        .font(vocabSkin.typography.sectionTitle)
                }
                .transition(.blurReplace)
            case .failed:
                VStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.destructive)
                    Text("同步失敗")
                        .font(vocabSkin.typography.sectionTitle)
                }
                .transition(.blurReplace)
            }
        }
    }

    private func stepRow(_ step: PipelineStep) -> some View {
        HStack(spacing: 12) {
            Group {
                switch step.status {
                case .waiting:
                    Image(systemName: "circle")
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                case .running:
                    ProgressView()
                        .controlSize(.small)
                case .retry:
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .symbolEffect(.scale.up, options: .repeating)
                        .foregroundStyle(vocabSkin.tierColor(for: "intermediate"))
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
            .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(step.label.localized)
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(step.status == .waiting ? vocabSkin.palette.tertiaryText : vocabSkin.palette.primaryText)
                    Spacer()
                    if step.status == .running && step.total > 0 {
                        Text("\(step.current)/\(step.total)")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .contentTransition(.numericText())
                            .animation(.spring, value: step.current)
                    }

                    StepDurationView(step: step)
                }

                if !step.detail.isEmpty && step.status != .waiting {
                    Text(step.detail.localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(detailColor(for: step.status))
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, AppMetrics.spacingMedium)
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
            return vocabSkin.tierColor(for: "intermediate")
        default:
            return vocabSkin.palette.secondaryText
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
                        .foregroundStyle(step.status == .retry ? vocabSkin.tierColor(for: "intermediate") : vocabSkin.palette.secondaryText)
                }
            }
        }
    }

    private func formatDuration(_ duration: TimeInterval) -> String {
        String(format: "%.1fs", duration)
    }
}
