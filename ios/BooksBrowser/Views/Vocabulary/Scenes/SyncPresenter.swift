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
    let pendingRows: [PendingVocabPresenterState.RowItem]

    init(
        isLoggedIn: Bool,
        isConnected: Bool,
        phase: SyncPhase,
        failureKind: SyncFailureKind?,
        pendingCount: Int,
        addCount: Int,
        deleteCount: Int,
        steps: [PipelineStep],
        summaryText: String,
        pendingRows: [PendingVocabPresenterState.RowItem] = []
    ) {
        self.isLoggedIn = isLoggedIn
        self.isConnected = isConnected
        self.phase = phase
        self.failureKind = failureKind
        self.pendingCount = pendingCount
        self.addCount = addCount
        self.deleteCount = deleteCount
        self.steps = steps
        self.summaryText = summaryText
        self.pendingRows = pendingRows
    }
}

struct SyncPresenter: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.vocabSkin) var vocabSkin

    let state: SyncPresenterState
    let onPrimaryAction: () -> Void
    let onCancel: () -> Void
    let onShowSettings: () -> Void
    var onPendingRowTapped: ((UUID) -> Void)?
    var onPendingActionTapped: ((UUID) -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: vocabSkin.metrics.heroSectionSpacing) {
                    headerView
                        .padding(.top, vocabSkin.metrics.syncOverlayInset)
                        .animatePhaseChange(state.phase)

                    if state.isLoggedIn && state.phase == .ready && !state.pendingRows.isEmpty {
                        pendingListSection
                    }

                    if state.isLoggedIn && !state.steps.isEmpty {
                        stepsSection
                    }

                    if !state.summaryText.isEmpty {
                        summaryCard
                            .transition(.feedbackBadge)
                    }
                }
                .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.overlayVerticalInset)
            }

            actionArea
                .padding(.horizontal, vocabSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.overlayVerticalInset)
                .background(vocabSkin.palette.pageBackground)
        }
        .vocabCanvasBackground()
        .animatePhaseChange(state.summaryText.isEmpty)
        .navigationTitle("同步".localized)
        .inlineNavigationBarTitle()
        .sensoryFeedback(.success, trigger: state.phase == .completed)
        .sensoryFeedback(.warning, trigger: state.failureKind == .partial)
        .sensoryFeedback(.error, trigger: state.failureKind == .full || state.failureKind == .cancelled)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("關閉".localized) { dismiss() }
            }
        }
    }

    // MARK: - Pending List

    @ViewBuilder
    private var pendingListSection: some View {
        VocabCard(padding: 0) {
            LazyVStack(spacing: 0) {
                ForEach(Array(state.pendingRows.enumerated()), id: \.element.id) { index, item in
                    HStack(alignment: .top, spacing: 12) {
                        WordRow(viewData: item.row)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture { onPendingRowTapped?(item.id) }

                        VocabAccessoryIconButton(
                            systemImage: item.actionSystemImage,
                            tone: resolveTone(item.actionTone),
                            action: { onPendingActionTapped?(item.id) }
                        )
                        .padding(.top, vocabSkin.metrics.accessoryTopOffset)
                    }
                    .padding(.horizontal, vocabSkin.spacing.cardPadding)
                    .transition(.listItemFade)

                    if index < state.pendingRows.count - 1 {
                        Divider()
                            .padding(.leading, vocabSkin.spacing.cardPadding)
                    }
                }
            }
            .animateSpring(state.pendingRows.count)
        }
    }

    private func resolveTone(_ tone: WordRow.ViewData.Tone) -> Color {
        switch tone {
        case .primary: return vocabSkin.palette.primaryText
        case .secondary: return vocabSkin.palette.secondaryText
        case .tertiary: return vocabSkin.palette.tertiaryText
        case .quaternary: return vocabSkin.palette.quaternaryText
        case .destructive: return vocabSkin.palette.destructive
        case .reviewDue: return vocabSkin.palette.warning
        }
    }

    // MARK: - Steps

    @ViewBuilder
    private var stepsSection: some View {
        VocabCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(state.steps.enumerated()), id: \.element.id) { index, step in
                    stepRow(step)
                        .transition(.listInsert)

                    if index < state.steps.count - 1 {
                        Divider()
                            .padding(.leading, vocabSkin.metrics.syncOverlayInset)
                    }
                }
            }
            .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)
            .padding(.vertical, vocabSkin.metrics.reviewTopBarBottomInset)
            .animation(AppMotion.standardSpring, value: state.steps.map(\.id))
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
                .symbolEffect(.bounce, value: true)
        case .skipped:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(vocabSkin.palette.secondaryText)
        case .error:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(vocabSkin.palette.destructive)
        }
    }
}
