import SwiftUI

struct SyncPresenterState {
    struct RowItem: Identifiable {
        let id: UUID
        let row: WordRow.ViewData
        let actionSystemImage: String
        let actionTone: WordRow.ViewData.Tone
        let actionAccessibilityLabel: String
    }

    let isLoggedIn: Bool
    let isConnected: Bool
    let phase: SyncPhase
    let failureKind: SyncFailureKind?
    let pendingCount: Int
    let addCount: Int
    let deleteCount: Int
    let steps: [PipelineStep]
    let summaryText: String
    let pendingRows: [RowItem]

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
        pendingRows: [RowItem] = []
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
    @ObserveInjection private var inject
    @Environment(\.dismiss) var dismiss
    @Environment(\.appSkin) var appSkin

    let state: SyncPresenterState
    let onPrimaryAction: () -> Void
    let onCancel: () -> Void
    let onShowSettings: () -> Void
    var onPendingRowTapped: ((UUID) -> Void)?
    var onPendingActionTapped: ((UUID) -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: appSkin.metrics.heroSectionSpacing) {
                    headerView
                        .padding(.top, appSkin.metrics.syncOverlayInset)
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
                .padding(.horizontal, appSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, appSkin.metrics.overlayVerticalInset)
            }

            actionArea
                .padding(.horizontal, appSkin.metrics.overlayHorizontalInset)
                .padding(.bottom, appSkin.metrics.overlayVerticalInset)
                .background(appSkin.palette.pageBackground)
        }
        .vocabCanvasBackground()
        .animatePhaseChange(state.summaryText.isEmpty)
        .navigationTitle("同步".localized)
        .inlineNavigationBarTitle()
        .appFeedback(.success, trigger: state.phase == .completed) { _, newValue in newValue }
        .appFeedback(.warning, trigger: state.failureKind == .partial) { _, newValue in newValue }
        .appFeedback(.error, trigger: state.failureKind == .full || state.failureKind == .cancelled) { _, newValue in newValue }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("關閉".localized) { dismiss() }
            }
        }
        .enableInjection()
    }

    // MARK: - Pending List

    @ViewBuilder
    private var pendingListSection: some View {
        VocabCard(padding: 0) {
            LazyVStack(spacing: 0) {
                ForEach(Array(state.pendingRows.enumerated()), id: \.element.id) { index, item in
                    HStack(alignment: .top, spacing: AppSpacing.s3) {
                        WordRow(viewData: item.row)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture { onPendingRowTapped?(item.id) }

                        VocabAccessoryIconButton(
                            systemImage: item.actionSystemImage,
                            tone: resolveTone(item.actionTone),
                            accessibilityLabel: item.actionAccessibilityLabel,
                            action: { onPendingActionTapped?(item.id) }
                        )
                        .padding(.top, appSkin.metrics.accessoryTopOffset)
                    }
                    .padding(.horizontal, appSkin.spacing.cardPadding)
                    .transition(.listItemFade)

                    if index < state.pendingRows.count - 1 {
                        Divider()
                            .padding(.leading, appSkin.spacing.cardPadding)
                    }
                }
            }
            .animateSpring(state.pendingRows.count)
        }
    }

    private func resolveTone(_ tone: WordRow.ViewData.Tone) -> Color {
        switch tone {
        case .primary: return appSkin.palette.primaryText
        case .secondary: return appSkin.palette.secondaryText
        case .tertiary: return appSkin.palette.tertiaryText
        case .quaternary: return appSkin.palette.quaternaryText
        case .destructive: return appSkin.palette.destructive
        case .reviewDue: return appSkin.palette.warning
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
                            .padding(.leading, appSkin.metrics.syncOverlayInset)
                    }
                }
            }
            .padding(.horizontal, appSkin.metrics.listRowHorizontalInset)
            .padding(.vertical, TodayReviewMetrics.topBarBottomInset)
            .animation(AppMotion.standardSpring, value: state.steps.map(\.id))
        }
    }

    // MARK: - Step Row

    func stepRow(_ step: PipelineStep) -> some View {
        VocabTimelineRow(
            title: step.label,
            titleTone: step.status == .waiting ? appSkin.palette.tertiaryText : appSkin.palette.primaryText,
            detail: step.status == .waiting ? nil : step.detail,
            detailTone: detailColor(for: step.status)
        ) {
            statusSymbol(for: step.status)
        } trailing: {
            HStack(spacing: AppSpacing.s2) {
                if step.status == .running && step.total > 0 {
                    Text("\(step.current)/\(step.total)")
                        .font(appSkin.typography.monoLabel)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .contentTransition(.numericText())
                        .animation(AppMotion.feedbackPulse, value: step.current)
                }

                StepDurationView(step: step)
            }
        }
    }

    // MARK: - Detail Color + Status Symbol

    // 兩者都委派給共用元件 `SyncStepStatusIcon`：設定頁的逐步進度是第二個消費者，
    // 同一個狀態在兩處長得不一樣是使用者學兩次的成本。
    func detailColor(for status: PipelineStep.StepStatus) -> Color {
        status.detailColor(appSkin)
    }

    @ViewBuilder
    func statusSymbol(for status: PipelineStep.StepStatus) -> some View {
        SyncStepStatusIcon(status: status)
    }
}
