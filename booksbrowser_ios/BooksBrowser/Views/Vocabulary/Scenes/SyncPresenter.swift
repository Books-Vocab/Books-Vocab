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
            VocabStatusHero(
                systemImage: "person.crop.circle.badge.exclamationmark",
                tone: vocabSkin.palette.tertiaryText,
                title: "尚未登入帳號",
                description: "登入後即可將您的生詞庫同步至雲端與 Mochi。"
            )
        } else if !state.hasProAccess {
            VocabStatusHero(
                systemImage: "sparkles.rectangle.stack",
                tone: vocabSkin.palette.accent,
                title: "同步需 Pro",
                description: "升級後即可將待收錄生詞同步到雲端、知識庫與 Mochi。"
            )
        } else {
            switch state.phase {
            case .ready:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: state.pendingCount == 0
                        ? "強制同步到 Mochi"
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
                        .animation(.spring, value: step.current)
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
