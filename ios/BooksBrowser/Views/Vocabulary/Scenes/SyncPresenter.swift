import SwiftUI

struct SyncPresenterState {
    let isLoggedIn: Bool
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
    @Environment(\.dismiss) var dismiss
    @Environment(\.vocabSkin) var vocabSkin

    let state: SyncPresenterState
    let onPrimaryAction: () -> Void
    let onCancel: () -> Void
    let onShowSettings: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            headerView
                .padding(.top, vocabSkin.metrics.syncOverlayInset)
                .padding(.bottom, vocabSkin.metrics.reviewFoldPadding)
                .animatePhaseChange(state.phase)

            if state.isLoggedIn && !state.steps.isEmpty {
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
        .animatePhaseChange(state.summaryText.isEmpty)
        .navigationTitle("同步".localized)
        .navigationBarTitleDisplayMode(.inline)
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

    // MARK: - Step Row

    func stepRow(_ step: PipelineStep) -> some View {
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

    // MARK: - Detail Color + Status Symbol

    func detailColor(for status: PipelineStep.StepStatus) -> Color {
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
    func statusSymbol(for status: PipelineStep.StepStatus) -> some View {
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
