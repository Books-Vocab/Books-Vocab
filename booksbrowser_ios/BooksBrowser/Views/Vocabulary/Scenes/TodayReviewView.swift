import SwiftUI
import SwiftData

struct TodayReviewSession: Identifiable {
    let id = UUID()
    let entries: [VocabularyEntry]
}

// MARK: - TodayReviewView (Mochi-inspired layout)

struct TodayReviewView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.vocabSkin) private var vocabSkin
    @Query private var allEntries: [VocabularyEntry]
    @State private var queue: [VocabularyEntry]
    @State private var currentIndex = 0
    @State private var showBack = false
    @State private var isAdvancing = false
    @State private var linkedCardStack: [VocabularyEntry] = []
    let onClose: () -> Void

    init(entries: [VocabularyEntry], onClose: @escaping () -> Void) {
        _queue = State(initialValue: entries)
        self.onClose = onClose
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let current = currentEntry {
                    // Top bar — minimal
                    topBar(current: current)

                    // Card area — takes all space
                    ScrollView {
                        reviewCard(current)
                            .padding(.horizontal, AppMetrics.spacingLarge)
                            .padding(.top, AppMetrics.spacingMedium)
                            .padding(.bottom, AppMetrics.spacingXXL)
                    }

                    // Bottom toolbar — Mochi-style actions
                    bottomToolbar
                } else {
                    completionState
                }
            }
            .vocabCanvasBackground()
            .toolbar(.hidden, for: .navigationBar)
            .overlay {
                LinkedCardOverlayStack(stack: $linkedCardStack)
            }
        }
    }

    // MARK: - Top Bar

    private func topBar(current: VocabularyEntry) -> some View {
        HStack(alignment: .center, spacing: AppMetrics.spacingMedium) {
            Text(progressText)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            Spacer()

            Text(showBack ? "背面" : "正面")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.quaternaryText)

            Button("詳情") {
                linkedCardStack.append(current)
            }
            .buttonStyle(.ghost(vocabSkin.palette.secondaryText))

            Button("關閉") {
                onClose()
            }
            .buttonStyle(.ghost(vocabSkin.palette.secondaryText))
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
        .padding(.vertical, AppMetrics.spacingSmall)
    }

    // MARK: - Review Card (Mochi layout)

    private func reviewCard(_ current: VocabularyEntry) -> some View {
        VocabCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                // Front content — Button to toggle reveal (not onTapGesture, avoids ScrollView gesture conflict)
                Button {
                    guard !isAdvancing else { return }
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                        showBack.toggle()
                    }
                } label: {
                    reviewCardFront(current)
                }
                .buttonStyle(.plain)

                // Back content — visible after reveal, links are tappable
                if showBack {
                    CardSectionDivider(horizontalPadding: AppMetrics.heroCardPadding)

                    reviewCardBack(current)
                }
            }
        }
    }

    private func reviewCardFront(_ current: VocabularyEntry) -> some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
            // Mode + POS tags
            HStack(spacing: AppMetrics.spacingSmall) {
                Text(current.reviewMode.localizedTitle)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                if let pos = current.partOfSpeech {
                    Text("·")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                    Text(pos)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                Spacer()
                if let tier = current.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

            Spacer(minLength: AppMetrics.spacingLarge)

            // The prompt
            switch current.reviewMode {
            case .recognition:
                Text(current.word)
                    .font(vocabSkin.typography.reviewWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .minimumScaleFactor(0.6)

            case .production:
                Text(current.translation)
                    .font(vocabSkin.typography.translationTitle)
                    .foregroundStyle(vocabSkin.palette.translationText)
                    .minimumScaleFactor(0.6)
            }

            // Example (with highlight mark)
            if current.reviewMode == .production, let example = current.primaryReviewExample {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.example,
                        textColor: vocabSkin.palette.secondaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: true
                    ),
                    mode: .cloze,
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
            }

            Spacer(minLength: AppMetrics.spacingLarge)

            // Tap hint
            HStack {
                Text(showBack ? "點擊收合" : "點擊展開答案")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                Spacer()
            }
        }
        .padding(AppMetrics.heroCardPadding)
        .frame(minHeight: showBack ? nil : AppMetrics.cardMinHeight)
    }

    private func reviewCardBack(_ current: VocabularyEntry) -> some View {
        let card = current.cardPresentation

        return VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
            // Answer
            switch card.reviewMode {
            case .recognition:
                Text(card.translation)
                    .font(vocabSkin.typography.translationTitle)
                    .foregroundStyle(vocabSkin.palette.translationText)

            case .production:
                Text(card.word)
                    .font(vocabSkin.typography.reviewWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .minimumScaleFactor(0.6)
            }

            // Example with highlight mark
            if let example = card.examples.first {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.example,
                        textColor: vocabSkin.palette.secondaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: true
                    ),
                    truncateAroundMarkedWordRadius: 5
                )
                .lineSpacing(4)
            }

            // Explanation
            if let explanation = card.explanation, !explanation.isEmpty {
                CardSectionDivider(horizontalPadding: AppMetrics.heroCardPadding)

                CardExplanationSection(explanation: explanation, colorScheme: .light)
                    .lineSpacing(4)
            }

            // Links
            if !card.linkGroups.isEmpty {
                CardSectionDivider(horizontalPadding: AppMetrics.heroCardPadding)

                reviewLinkStrip(for: current)
            }
        }
        .padding(AppMetrics.heroCardPadding)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }



    // MARK: - Bottom Toolbar (Mochi-style)

    private var bottomToolbar: some View {
        HStack(spacing: 0) {
            // Navigation arrows
            HStack(spacing: AppMetrics.spacingSmall) {
                Button {
                    guard currentIndex > 0 else { return }
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
                        showBack = false
                        currentIndex -= 1
                    }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 16, weight: .thin))
                }
                .disabled(currentIndex <= 0)

                Button {
                    guard currentIndex < queue.count - 1 else { return }
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
                        showBack = false
                        currentIndex += 1
                    }
                } label: {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 16, weight: .thin))
                }
                .disabled(currentIndex >= queue.count - 1)
            }
            .foregroundStyle(.secondary)

            Spacer()

            // Review actions — ghost buttons
            if showBack {
                HStack(spacing: AppMetrics.spacingSmall) {
                    Button {
                        submit(.forgot)
                    } label: {
                        Label("Forgot", systemImage: "xmark")
                            .font(AppFonts.subhead(weight: .medium))
                    }
                    .buttonStyle(.ghost(vocabSkin.palette.destructive))

                    Button {
                        submit(.remembered)
                    } label: {
                        Label("Remembered", systemImage: "checkmark")
                            .font(AppFonts.subhead(weight: .medium))
                    }
                    .buttonStyle(.ghost(vocabSkin.palette.success))
                }
                .transition(.opacity)
            }
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
        .padding(.vertical, AppMetrics.spacingMedium)
        .background(
            Rectangle()
                .fill(vocabSkin.palette.pageBackground)
                .shadow(color: .black.opacity(0.03), radius: 8, y: -4)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    // MARK: - Completion

    private var completionState: some View {
        VStack(spacing: AppMetrics.spacingLarge) {
            Spacer()
            ContentUnavailableView(
                "今天複習完成",
                systemImage: "checkmark.circle",
                description: Text("這一輪 session 的卡片都處理完了。")
            )
            Button("返回生詞庫") {
                onClose()
            }
            .buttonStyle(.ghost(vocabSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
    }

    // MARK: - Link Strip

    private func reviewLinkStrip(for entry: VocabularyEntry) -> some View {
        let fullGroups = entry.cardPresentation.linkGroups
        let groups = fullGroups.map { $0.limited(to: 2) }

        return HStack(alignment: .top, spacing: 8) {
            Image(systemName: "paperclip")
                .font(.system(size: 13, weight: .thin))
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(groups.enumerated()), id: \.element.id) { index, group in
                    compactLinkGroup(group, fullGroup: fullGroups[index])
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func compactLinkGroup(
        _ group: CardLinkGroupPresentation,
        fullGroup: CardLinkGroupPresentation
    ) -> some View {
        HStack(spacing: 4) {
            Text("\(group.label)：")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                if let target = linkedEntry(for: item) {
                    Button {
                        linkedCardStack.append(target)
                    } label: {
                        Text(item.word)
                            .font(.system(size: 16, weight: .semibold, design: .monospaced))
                            .foregroundStyle(vocabSkin.palette.primaryText)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(item.word)
                        .font(.system(size: 16, weight: .semibold, design: .monospaced))
                        .foregroundStyle(vocabSkin.palette.primaryText)
                }

                if index < group.items.count - 1 {
                    Text("|")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }
            }

            let overflowCount = group.overflowed(relativeToFullGroup: fullGroup)
            if overflowCount > 0 {
                Text("+\(overflowCount)")
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
    }

    // MARK: - State

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    private func linkedEntry(for link: KGCardLinkSummary) -> VocabularyEntry? {
        allEntries.first { $0.kgCardId == link.cardId }
    }

    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry, !isAdvancing else { return }
        isAdvancing = true

        current.applyReviewFeedback(feedback)

        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
            showBack = false
            currentIndex += 1
        }

        Task { @MainActor in
            try? modelContext.save()
            isAdvancing = false
        }
    }

    private func frontInstruction(for mode: VocabularyCardMode) -> String {
        switch mode {
        case .recognition:
            return "先想意思，再點卡片翻面"
        case .production:
            return "先想英文，再點卡片翻面"
        }
    }
}
