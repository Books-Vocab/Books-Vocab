import SwiftUI
import SwiftData

struct TodayReviewSession: Identifiable {
    let id = UUID()
    let entries: [VocabularyEntry]
}

struct TodayReviewView: View {
    @Environment(\.modelContext) private var modelContext
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
            Group {
                if let current = currentEntry {
                    VStack(spacing: AppMetrics.spacingLarge) {
                        header(current: current)

                        AppCard(padding: 0) {
                            ZStack {
                                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusGlass, style: .continuous)
                                    .fill(Color.white)

                                reviewCardFront(current)
                                    .opacity(showBack ? 0 : 1)

                                reviewCardBack(current)
                                    .opacity(showBack ? 1 : 0)
                                    .rotation3DEffect(.degrees(180), axis: (x: 0, y: 1, z: 0))
                            }
                            .frame(minHeight: AppMetrics.cardMinHeight)
                        }
                        .shadow(
                            color: .black.opacity(AppShadows.paperFloatOpacity),
                            radius: AppShadows.paperFloatRadius,
                            y: AppShadows.paperFloatY
                        )
                        .contentShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusGlass, style: .continuous))
                        .onTapGesture {
                            guard !isAdvancing else { return }
                            withAnimation(.spring(response: 0.45, dampingFraction: 0.82)) {
                                showBack.toggle()
                            }
                        }
                        .rotation3DEffect(
                            .degrees(showBack ? 180 : 0),
                            axis: (x: 0, y: 1, z: 0)
                        )
                        .padding(.horizontal, AppMetrics.spacingLarge)

                        if showBack {
                            reviewActionBar
                        } else {
                            Text("先翻面，再做記憶判斷。")
                                .font(AppFonts.caption())
                                .foregroundStyle(.secondary)
                        }

                        Spacer()
                    }
                    .padding(.top, AppMetrics.spacingLarge)
                } else {
                    completionState
                }
            }
            .navigationTitle("今日複習")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .navigationBar)
            .background(AppColors.paperLight.ignoresSafeArea())
            .overlay {
                LinkedCardOverlayStack(stack: $linkedCardStack)
            }
        }
    }

    // MARK: - Header

    private func header(current: VocabularyEntry) -> some View {
        HStack(alignment: .center) {
            Text(progressText)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(.secondary)
            Spacer()
            Text(showBack ? "背面" : "正面")
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(.tertiary)
            Button("詳情") {
                linkedCardStack.append(current)
            }
            .font(AppFonts.caption(weight: .semibold))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .compatibleGlass(in: Capsule())
            Button("關閉") {
                onClose()
            }
            .font(AppFonts.caption(weight: .semibold))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .compatibleGlass(in: Capsule())
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
    }

    // MARK: - Action Bar

    private var reviewActionBar: some View {
        HStack(spacing: AppMetrics.spacingSmall) {
            reviewButton(
                title: "忘記了",
                caption: "縮短間隔",
                tone: AppColors.translation(.light)
            ) {
                submit(.forgot)
            }
            reviewButton(
                title: "記得",
                caption: "進入下一張",
                tone: AppColors.saved(.light)
            ) {
                submit(.remembered)
            }
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
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
            .font(AppFonts.subhead(weight: .semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .compatibleGlass(in: Capsule())
            Spacer()
        }
        .padding(.horizontal, AppMetrics.spacingLarge)
    }

    // MARK: - State

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
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

    // MARK: - Card Front

    private func reviewCardFront(_ current: VocabularyEntry) -> some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                HStack(spacing: AppMetrics.spacingSmall) {
                    AppTag(text: current.reviewMode.localizedTitle, tone: AppColors.translation(.light))
                    if let pos = current.partOfSpeech {
                        AppTag(text: pos, tone: AppColors.accent(.light))
                    }
                }
                Spacer(minLength: 0)

                switch current.reviewMode {
                case .recognition:
                    Text(current.word)
                        .font(.system(size: 62, weight: .semibold, design: .serif))
                        .foregroundStyle(.primary)
                        .minimumScaleFactor(0.75)

                case .production:
                    Text(current.translation)
                        .font(.system(size: 46, weight: .semibold, design: .default))
                        .foregroundStyle(AppColors.translation(.light))
                        .minimumScaleFactor(0.75)

                    if let example = current.primaryReviewExample {
                        CardRichTextRenderer.text(
                            example,
                            style: CardRichTextStyle(
                                font: .system(size: 24, weight: .regular, design: .default),
                                textColor: .secondary,
                                highlightColor: AppColors.translation(.light),
                                italic: true
                            ),
                            mode: .cloze,
                            truncateAroundMarkedWordRadius: 5
                        )
                    }
                }

                Text(frontInstruction(for: current.reviewMode))
                    .font(.system(size: 20, weight: .medium, design: .default))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack {
                Label("點擊看答案", systemImage: "rectangle.portrait.on.rectangle.portrait")
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(.tertiary)
                Spacer()
            }
        }
        .padding(AppMetrics.heroCardPadding)
    }

    // MARK: - Card Back

    private func reviewCardBack(_ current: VocabularyEntry) -> some View {
        let card = current.cardPresentation

        return VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                switch card.reviewMode {
                case .recognition:
                    Text(card.word)
                        .font(.system(size: 26, weight: .semibold, design: .serif))
                        .foregroundStyle(.secondary)

                    Text(card.translation)
                        .font(.system(size: 44, weight: .semibold, design: .default))
                        .foregroundStyle(AppColors.translation(.light))

                case .production:
                    Text(card.translation)
                        .font(.system(size: 22, weight: .medium, design: .default))
                        .foregroundStyle(.secondary)

                    Text(card.word)
                        .font(.system(size: 54, weight: .semibold, design: .serif))
                        .foregroundStyle(.primary)
                        .minimumScaleFactor(0.75)
                }

                if let example = card.examples.first {
                    CardRichTextRenderer.text(
                        example,
                        style: CardRichTextStyle(
                            font: .system(size: 26, weight: .regular, design: .default),
                            textColor: .secondary,
                            highlightColor: AppColors.translation(.light),
                            italic: true
                        ),
                        truncateAroundMarkedWordRadius: 5
                    )
                }

                if let explanation = card.explanation, !explanation.isEmpty {
                    CardRichTextRenderer.text(
                        explanation,
                        style: CardRichTextStyle(
                            font: .system(size: 18, weight: .regular, design: .default),
                            textColor: .secondary,
                            highlightColor: AppColors.accent(.light),
                            italic: false
                        )
                    )
                }

                if !card.linkGroups.isEmpty {
                    reviewLinkStrip(for: current)
                }
            }

            Spacer()

            HStack {
                Label("點擊回正面", systemImage: "rectangle.portrait.on.rectangle.portrait")
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(.tertiary)
                Spacer()
            }
        }
        .padding(AppMetrics.heroCardPadding)
    }

    // MARK: - Link Strip

    private func reviewLinkStrip(for entry: VocabularyEntry) -> some View {
        let fullGroups = entry.cardPresentation.linkGroups
        let groups = fullGroups.map { $0.limited(to: 2) }

        return HStack(alignment: .top, spacing: 10) {
            Image(systemName: "paperclip")
                .font(.system(size: 15, weight: .thin))
                .foregroundStyle(.secondary)
                .padding(.top, 2)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    ForEach(Array(groups.enumerated()), id: \.element.id) { index, group in
                        compactLinkGroup(group, fullGroup: fullGroups[index])
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(groups.enumerated()), id: \.element.id) { index, group in
                        compactLinkGroup(group, fullGroup: fullGroups[index])
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                .fill(Color.primary.opacity(0.04))
        )
        .overlay(
            RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                .stroke(Color.primary.opacity(0.04), lineWidth: 0.8)
        )
    }

    private func compactLinkGroup(
        _ group: CardLinkGroupPresentation,
        fullGroup: CardLinkGroupPresentation
    ) -> some View {
        HStack(spacing: 4) {
            Text("\(group.label)：")
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(.secondary)

            ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                if let target = linkedEntry(for: item) {
                    Button {
                        linkedCardStack.append(target)
                    } label: {
                        Text(item.word)
                            .font(.system(size: 18, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.primary)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(item.word)
                        .font(.system(size: 18, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.primary)
                }

                if index < group.items.count - 1 {
                    Text("·")
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(.tertiary)
                }
            }

            let overflowCount = group.overflowed(relativeToFullGroup: fullGroup)
            if overflowCount > 0 {
                Text("+\(overflowCount)")
                    .font(AppFonts.caption(weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private func linkedEntry(for link: KGCardLinkSummary) -> VocabularyEntry? {
        allEntries.first { $0.kgCardId == link.cardId }
    }

    // MARK: - Review Button

    private func reviewButton(
        title: String,
        caption: String,
        tone: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(AppFonts.h2(weight: .semibold))
                Text(caption)
                    .font(AppFonts.caption())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, AppMetrics.spacingLarge)
            .padding(.horizontal, AppMetrics.spacingMedium)
        }
        .buttonStyle(.plain)
        .foregroundStyle(tone)
        .compatibleGlass(
            in: RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
        )
        .disabled(isAdvancing)
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
