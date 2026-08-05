import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.kgService) private var kgService
    @Environment(\.detailRouter) private var detailRouter
    @Environment(\.modelContext) private var modelContext
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var state = WordDetailSceneState()
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    @State private var isEditing = false
    @State private var showAddLink = false
    @State private var isConfirmingDelete = false
    @State private var isArchiving = false

    @Bindable var entry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    private let wrapInNavigation: Bool
    private let showsInlineChrome: Bool
    private let onInlineClose: (() -> Void)?
    private let onDeleted: (() -> Void)?
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

    init(
        entry: VocabularyEntry,
        allEntries: [VocabularyEntry] = [],
        wrapInNavigation: Bool = true,
        showsInlineChrome: Bool? = nil,
        onClose: (() -> Void)? = nil,
        onDeleted: (() -> Void)? = nil,
        linkedCardStack: Binding<[VocabularyEntry]>? = nil,
        presentsEagerly: Bool = false
    ) {
        self.entry = entry
        self.allEntries = allEntries
        self.wrapInNavigation = wrapInNavigation
        self.showsInlineChrome = showsInlineChrome ?? wrapInNavigation
        self.onInlineClose = onClose
        self.onDeleted = onDeleted
        self.externalLinkedCardStack = linkedCardStack
        // Catalog / snapshot seam: seed the presentation synchronously so a
        // `layer.render(in:)` snapshot captures the card, not the loading
        // placeholder the deferred `.task` would still be showing. The live app
        // keeps `presentsEagerly == false` and its brief loading→card fade.
        if presentsEagerly {
            let seeded = WordDetailSceneState()
            seeded.refreshPresentation(for: entry, in: allEntries)
            _state = State(initialValue: seeded)
        }
    }

    var body: some View {
        Group {
            if let presenterState = state.presenterState {
                WordDetailPresenter(
                    state: presenterState,
                    isExcludedFromReader: entry.isExcludedFromReader,
                    isArchived: entry.isArchived,
                    canArchive: entry.isSynced,
                    showsChrome: showsInlineChrome,
                    onClose: showsInlineChrome ? { handleClose() } : nil,
                    onEdit: { isEditing = true },
                    onLinkTapped: handleLinkTap,
                    onToggleExcludeFromReader: { entry.isExcludedFromReader.toggle() },
                    onToggleArchive: { handleToggleArchive() },
                    onDelete: { isConfirmingDelete = true },
                    onAddLink: { showAddLink = true },
                    onDeleteLink: { link in
                        state.deleteLink(link, from: entry, allEntries: allEntries, kgService: kgService)
                    },
                    onHideLink: { link in
                        state.hideLink(link, from: entry, allEntries: allEntries, kgService: kgService)
                    },
                    onUnhideLink: { link in
                        state.unhideLink(link, from: entry, allEntries: allEntries, kgService: kgService)
                    }
                )
                .overlay(alignment: .top) {
                    if let actionError = state.actionError {
                        AppBanner(
                            message: actionError,
                            systemImage: "exclamationmark.triangle",
                            onDismiss: { state.dismissActionError() }
                        )
                        .padding(.top, AppSpacing.s1)
                    }
                }
            } else {
                VocabStateMessageCard(
                    title: "載入中".localized,
                    systemImage: "doc.text"
                ) {
                    ProgressView()
                        .controlSize(.small)
                }
                .padding()
            }
        }
        .animation(AppMotion.contentFade, value: state.presenterState != nil)
        .task(id: "\(entry.id)|\(entry.graphLinksJSON.hashValue)") {
            // Yield once so SwiftUI can render the loading placeholder before
            // we run the (lightweight but synchronous) presentation computation.
            await Task.yield()
            state.refreshPresentation(for: entry, in: allEntries)
        }
        .overlay {
            if shouldUseLinkedOverlayStack {
                LinkedCardOverlayStack(stack: linkedCardStack, allEntries: allEntries)
            }
        }
        .toastSheet(isPresented: $isEditing) {
            WordEditSheet(entry: entry)
        }
        .confirmationDialog(
            WordDetailCopy.deleteTitle(word: entry.word),
            isPresented: $isConfirmingDelete,
            titleVisibility: .visible
        ) {
            Button(WordDetailCopy.delete, role: .destructive) { handleDelete() }
            Button(WordDetailCopy.cancel, role: .cancel) {}
        } message: {
            Text(WordDetailCopy.deleteMessage(linkCount: state.presenterState?.card.totalLinkCount ?? 0))
        }
        .toastSheet(isPresented: $showAddLink) {
            AddLinkSheet(
                sourceEntry: entry,
                allEntries: allEntries,
                onSelect: { target in
                    state.addLink(target: target, to: entry, kgService: kgService)
                }
            )
        }
        .enableInjection()
    }

    private var linkedCardStack: Binding<[VocabularyEntry]> {
        externalLinkedCardStack ?? $localLinkedCardStack
    }

    private var shouldUseLinkedOverlayStack: Bool {
        // 有外部 stack binding 時，overlay 由外部 LinkedCardOverlayStack 管理，不重複渲染
        guard externalLinkedCardStack == nil else { return false }
        return wrapInNavigation || detailRouter == nil
    }

    /// 封存後**刻意不關 sheet**：圖示翻成 `archivebox.fill`，再按一次就是解除封存。
    /// toggle 自己就是 undo，所以不需要帶動作按鈕的 undo toast（`AppToastCoordinator`
    /// 也只吃 message/style/duration，沒有 action）。失敗訊息走既有的 `actionError` banner。
    private func handleToggleArchive() {
        guard !isArchiving else { return }
        isArchiving = true
        Task { @MainActor in
            await state.setArchived(
                !entry.isArchived,
                for: entry,
                kgService: kgService,
                modelContext: modelContext
            )
            isArchiving = false
        }
    }

    /// 刪除是 local-first 軟刪（`queueDelete` 排進 outbox，離線可用），與封存的
    /// server-authoritative 語意相反 —— 所以這裡不需要回捲，但需要關掉 sheet：
    /// 讓使用者盯著一張已經不存在的卡是最糟的收尾。
    private func handleDelete() {
        entry.queueDelete()
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success(WordDetailCopy.deleted)
        }
        if let onDeleted {
            onDeleted()
        } else {
            handleClose()
        }
    }

    private func handleClose() {
        if let onInlineClose {
            onInlineClose()
        } else {
            dismiss()
        }
    }

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        guard let target = state.linkedEntry(for: link, from: entry, in: allEntries) else { return }
        if !wrapInNavigation, let detailRouter {
            detailRouter.showWordDetail(target, allEntries: allEntries)
            return
        }
        linkedCardStack.wrappedValue.append(target)
    }
}
