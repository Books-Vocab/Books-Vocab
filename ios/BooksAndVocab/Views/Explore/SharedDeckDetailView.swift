//
//  SharedDeckDetailView.swift
//  Books & Vocab
//
//  Explore 牌組唯讀預覽 —— card count / sample cards / author + official badge /
//  rating / download count。**主按鈕「複製」留 Phase 2，本 phase 無複製鈕**。
//
//  Header 自本機 SharedDeck store 讀（deckId）；sample cards 由目錄 service 現拉進
//  @State（唯讀預覽，不落地）。四態覆蓋 sample-card 載入區（loading/empty/error/loaded）。
//

import SwiftUI
import SwiftData

struct SharedDeckDetailView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.catalogTaskPolicy) private var catalogTaskPolicy

    let deckId: String

    @State private var deck: SharedDeck?
    @State private var cardsState: CardsState = .loading
    @State private var copyController = SharedDeckCopyController()
    @State private var showCopySheet = false
    /// 已確認的複製目標名稱 —— failure 態的「重試」沿用同一名稱（配合 controller 沿用
    /// 同一把 idempotencyKey）。
    @State private var confirmedCopyName: String?

    /// DEBUG catalog seam：直接注入預覽 sample cards，跳過網路 fetch。
    private let injectedCards: [SharedDeckCard]?
    /// DEBUG catalog seam：強制複製 CTA 呈現指定態（idle/inflight/success/failure），
    /// 供 scenario 決定性快照四態，繞過 auth / 網路。Release 永遠 nil。
    private let previewCopyState: SharedDeckCopyController.CopyState?

    init(deckId: String) {
        self.deckId = deckId
        self.injectedCards = nil
        self.previewCopyState = nil
    }

    #if DEBUG
    init(
        deckId: String,
        previewCards: [SharedDeckCard],
        previewCopyState: SharedDeckCopyController.CopyState? = nil
    ) {
        self.deckId = deckId
        self.injectedCards = previewCards
        self.previewCopyState = previewCopyState
    }
    #endif

    enum CardsState {
        case loading
        case loaded([SharedDeckCard])
        case empty
        case error
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppSpacing.s5) {
                if let deck {
                    header(deck)
                    copySection(deck)
                    sampleCardsSection
                } else {
                    missingDeckState
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.vertical, AppSpacing.s4)
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
        // deck.title 是策展 runtime 資料（i18n 覆蓋外）；nil 時退回 section 名。
        .navigationTitle(deck?.title ?? L10n.string("app.section.explore"))
        .sheet(isPresented: $showCopySheet) {
            SharedDeckCopySheet(
                defaultName: deck?.title ?? "",
                onCancel: { showCopySheet = false },
                onConfirm: { name in
                    showCopySheet = false
                    Task { await performCopy(notebookName: name) }
                }
            )
        }
        .task(id: deckId) { await load() }
        .enableInjection()
    }

    // MARK: - Copy CTA

    /// 「複製到我的單字本」CTA 區。四態走 `state_matrix`：idle/inflight/success/failure，
    /// 外加登出 gate。DEBUG `previewCopyState` 覆寫供 catalog 快照。
    @ViewBuilder
    private func copySection(_ deck: SharedDeck) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            if let previewCopyState {
                copyStateView(previewCopyState, deck: deck)
            } else if !authManager.isLoggedIn {
                loginRequiredCTA
            } else {
                copyStateView(copyController.state, deck: deck)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func copyStateView(_ state: SharedDeckCopyController.CopyState, deck: SharedDeck) -> some View {
        switch state {
        case .idle:
            Button {
                confirmedCopyName = nil
                showCopySheet = true
            } label: {
                Label(L10n.string("explore.copy.cta"), systemImage: "square.and.arrow.down.on.square")
            }
            .buttonStyle(.appAction(.primary))
            .accessibilityLabel(L10n.string("explore.copy.a11y.cta"))
            .accessibilityIdentifier("explore.copy.button")

        case .inflight:
            HStack(spacing: AppSpacing.s2) {
                ProgressView().controlSize(.small)
                Text(L10n.string("explore.copy.inflight"))
                    .font(AppFonts.subhead(weight: .semibold))
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, AppSpacing.actionButtonVerticalPadding)
            .accessibilityIdentifier("explore.copy.inflight")

        case .success(let outcome):
            copySuccessCard(outcome)

        case .failure(let message):
            copyFailureCard(message)
        }
    }

    private var loginRequiredCTA: some View {
        VStack(alignment: .leading, spacing: AppSpacing.microGap) {
            Button {} label: {
                Label(L10n.string("explore.copy.cta"), systemImage: "square.and.arrow.down.on.square")
            }
            .buttonStyle(.appAction(.primary))
            .disabled(true)
            .accessibilityHint(L10n.string("explore.copy.loginRequired"))
            Text(L10n.string("explore.copy.loginRequired"))
                .font(AppFonts.caption())
                .foregroundStyle(appTheme.palette.tertiaryText)
        }
        .accessibilityIdentifier("explore.copy.loginRequired")
    }

    private func copySuccessCard(_ outcome: SharedDeckCopyController.Outcome) -> some View {
        HStack(spacing: AppSpacing.s2) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(appTheme.palette.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text(outcome.alreadyCopied
                     ? L10n.string("explore.copy.success.alreadyCopied")
                     : L10n.format("explore.copy.success", outcome.notebookName))  // notebookName 為 runtime 資料
                    .font(AppFonts.subhead(weight: .semibold))
                    .foregroundStyle(appTheme.palette.primaryText)
                Text(SharedDeckFormat.cardCount(outcome.cardCount))
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
                    .monospacedDigit()
            }
            Spacer(minLength: 0)
        }
        .padding(AppSpacing.s3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                .fill(appTheme.palette.cardBackground)
        )
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("explore.copy.success")
    }

    private func copyFailureCard(_ message: String) -> some View {
        AppStateMessageCard(
            title: message,
            systemImage: "exclamationmark.triangle",
            description: nil
        ) {
            Button(L10n.string("explore.retry")) {
                Task { await performCopy(notebookName: confirmedCopyName) }
            }
            .font(AppFonts.caption(weight: .medium))
            .accessibilityIdentifier("explore.copy.retryButton")
        }
        .accessibilityIdentifier("explore.copy.failure")
    }

    // MARK: - Copy action

    @MainActor
    private func performCopy(notebookName: String?) async {
        confirmedCopyName = notebookName
        await copyController.copy(
            deckId: deckId,
            notebookName: notebookName,
            using: kgService,
            afterCopy: { _ in
                // 2c-2（後續 commit）：copy 成功後針對性增量 pull 新 notebook + 卡片。
            }
        )
        if case .success = copyController.state {
            toastCoordinator.success(L10n.string("explore.copy.toast.success"))
        }
    }

    // MARK: - Header

    private func header(_ deck: SharedDeck) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.s3) {
            HStack(alignment: .top, spacing: AppSpacing.s4) {
                cover(deck)
                    .frame(width: 96, height: 144)
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(deck.title)
                        .font(AppFonts.h2(weight: .semibold))
                        .foregroundStyle(appTheme.palette.primaryText)
                        .lineLimit(3)
                    authorLine(deck)
                    if let rating = deck.ratingAvg, deck.ratingCount > 0 {
                        SharedDeckRatingStars(average: rating, count: deck.ratingCount)
                    }
                    statsLine(deck)
                }
                Spacer(minLength: 0)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func cover(_ deck: SharedDeck) -> some View {
        NotebookCoverView(
            color: NotebookPalette.color(for: deck.color),
            pattern: deck.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) },
            coverImagePath: nil,
            name: deck.title
        )
        .clipShape(RoundedRectangle(cornerRadius: AppBookshelfMetrics.coverCornerRadius, style: .continuous))
        .appElevation(.z0)
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private func authorLine(_ deck: SharedDeck) -> some View {
        HStack(spacing: AppSpacing.microGap) {
            if deck.isOfficial {
                Label {
                    Text(L10n.string("explore.deck.a11y.official"))
                } icon: {
                    Image(systemName: "checkmark.seal.fill")
                }
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(appTheme.palette.accent)
                .labelStyle(.titleAndIcon)
            } else if let author = deck.authorLabel, !author.isEmpty {
                Text(author)   // 發布者名為 runtime 資料，render-safe（截斷）
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
                    .lineLimit(1)
            }
        }
    }

    private func statsLine(_ deck: SharedDeck) -> some View {
        HStack(spacing: AppSpacing.s3) {
            Label(SharedDeckFormat.cardCount(deck.cardCount), systemImage: "rectangle.stack")
            if deck.downloadCount > 0 {
                Label(SharedDeckFormat.compactNumber(deck.downloadCount), systemImage: "arrow.down.circle")
                    .accessibilityLabel(L10n.format("explore.deck.a11y.downloads", SharedDeckFormat.compactNumber(deck.downloadCount)))
            }
        }
        .font(AppFonts.caption())
        .monospacedDigit()
        .foregroundStyle(appTheme.palette.secondaryText)
    }

    // MARK: - Sample cards

    @ViewBuilder
    private var sampleCardsSection: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s3) {
            Text(L10n.string("explore.detail.sampleCards"))
                .font(AppFonts.subhead(weight: .semibold))
                .foregroundStyle(appTheme.palette.primaryText)

            switch cardsState {
            case .loading:
                HStack(spacing: AppSpacing.s2) {
                    ProgressView().controlSize(.small)
                    Text(L10n.string("explore.detail.loadingCards"))
                        .font(AppFonts.caption())
                        .foregroundStyle(appTheme.palette.tertiaryText)
                }
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.vertical, AppSpacing.s4)
            case .empty:
                Text(L10n.string("explore.detail.noCards"))
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
            case .error:
                AppStateMessageCard(
                    title: L10n.string("explore.detail.cardsError"),
                    systemImage: "exclamationmark.triangle",
                    description: L10n.string("explore.error.guidance")
                ) {
                    Button(L10n.string("explore.retry")) { Task { await load() } }
                        .font(AppFonts.caption(weight: .medium))
                }
            case .loaded(let cards):
                VStack(spacing: AppSpacing.s2) {
                    ForEach(cards) { card in
                        SharedDeckCardPreviewRow(card: card)
                    }
                }
            }
        }
    }

    private var missingDeckState: some View {
        VStack(spacing: AppSpacing.s4) {
            Spacer(minLength: 80)
            AppEmptyStateContent(
                title: L10n.string("explore.detail.missing.title"),
                systemImage: "questionmark.square.dashed",
                description: L10n.string("explore.detail.missing.description"),
                style: .bookshelf(appTheme)
            )
            Spacer(minLength: 80)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Load

    @MainActor
    private func load() async {
        deck = fetchDeck()
        if let injectedCards {
            cardsState = injectedCards.isEmpty ? .empty : .loaded(injectedCards)
            return
        }
        guard catalogTaskPolicy.runsTasks else {
            cardsState = .empty
            return
        }
        cardsState = .loading
        do {
            let detail = try await SharedDeckCatalogService(kgService: kgService)
                .fetchDeckDetail(deckId: deckId)
            cardsState = detail.sampleCards.isEmpty ? .empty : .loaded(detail.sampleCards)
        } catch is CancellationError {
            // torn down / superseded — leave state as-is
        } catch {
            AppLog.kg.warning("[Explore] detail fetch failed for \(deckId): \(error.localizedDescription)")
            cardsState = .error
        }
    }

    private func fetchDeck() -> SharedDeck? {
        let target = deckId
        let descriptor = FetchDescriptor<SharedDeck>(
            predicate: #Predicate { $0.remoteId == target }
        )
        return try? modelContext.fetch(descriptor).first
    }
}

// MARK: - Rating stars

struct SharedDeckRatingStars: View {
    @Environment(\.appTheme) private var appTheme
    let average: Double
    let count: Int

    private var filledStars: Int { Int(average.rounded()) }

    var body: some View {
        HStack(spacing: AppSpacing.microGap) {
            ForEach(0..<5, id: \.self) { index in
                Image(systemName: index < filledStars ? "star.fill" : "star")
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.accent)
            }
            Text(SharedDeckFormat.rating(average))
                .font(AppFonts.caption2(weight: .medium))
                .monospacedDigit()
                .foregroundStyle(appTheme.palette.secondaryText)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L10n.format(
            "explore.deck.a11y.rating",
            SharedDeckFormat.rating(average),
            SharedDeckFormat.compactNumber(count)
        ))
    }
}

// MARK: - Sample card preview row

struct SharedDeckCardPreviewRow: View {
    @Environment(\.appTheme) private var appTheme
    let card: SharedDeckCard

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.microGap) {
            HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s2) {
                Text(card.content)   // 卡片內容為策展 runtime 資料，render-safe
                    .font(AppFonts.body(weight: .semibold))
                    .foregroundStyle(appTheme.palette.primaryText)
                    .lineLimit(2)
                if let pos = card.pos, !pos.isEmpty {
                    Text(pos)
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.tertiaryText)
                }
                Spacer(minLength: 0)
            }
            if !card.meaning.isEmpty {
                Text(card.meaning)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(AppSpacing.s3)
        .background(
            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                .fill(appTheme.palette.cardBackground)
        )
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Copy destination sheet

/// 「複製到新單字本」目的地選擇 sheet。MVP：建立新單字本、名稱預填 deck title 可編輯。
/// 純呈現 —— 名稱 draft sheet-local，confirm 才把最終名稱交回 owner 觸發複製。
private struct SharedDeckCopySheet: View {
    @Environment(\.appTheme) private var appTheme
    let defaultName: String
    let onCancel: () -> Void
    let onConfirm: (String) -> Void
    @State private var name: String

    init(defaultName: String, onCancel: @escaping () -> Void, onConfirm: @escaping (String) -> Void) {
        self.defaultName = defaultName
        self.onCancel = onCancel
        self.onConfirm = onConfirm
        _name = State(initialValue: defaultName)
    }

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: AppSpacing.s4) {
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(L10n.string("explore.copy.sheet.nameLabel"))
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(appTheme.palette.secondaryText)
                    TextField(L10n.string("explore.copy.sheet.nameLabel"), text: $name)
                        .textFieldStyle(.roundedBorder)
                        .submitLabel(.done)
                        .onSubmit { if !trimmed.isEmpty { onConfirm(trimmed) } }
                        .accessibilityIdentifier("explore.copy.sheet.nameField")
                }
                Button {
                    onConfirm(trimmed.isEmpty ? defaultName : trimmed)
                } label: {
                    Text(L10n.string("explore.copy.sheet.confirm"))
                }
                .buttonStyle(.appAction(.primary))
                .disabled(trimmed.isEmpty)
                .accessibilityIdentifier("explore.copy.sheet.confirmButton")
                Spacer(minLength: 0)
            }
            .padding(AppShellMetrics.pageHorizontalPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle(L10n.string("explore.copy.sheet.title"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.string("取消"), action: onCancel)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
