import SwiftUI
import SwiftData

struct WordDetailSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.kgService) private var kgService
    @Environment(\.detailRouter) private var detailRouter
    @State private var state = WordDetailSceneState()
    @State private var localLinkedCardStack: [VocabularyEntry] = []
    @State private var isEditing = false
    @State private var showAddLink = false

    @Bindable var entry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    private let wrapInNavigation: Bool
    private let showsInlineChrome: Bool
    private let onInlineClose: (() -> Void)?
    private let externalLinkedCardStack: Binding<[VocabularyEntry]>?

    init(
        entry: VocabularyEntry,
        allEntries: [VocabularyEntry] = [],
        wrapInNavigation: Bool = true,
        showsInlineChrome: Bool? = nil,
        onClose: (() -> Void)? = nil,
        linkedCardStack: Binding<[VocabularyEntry]>? = nil
    ) {
        self.entry = entry
        self.allEntries = allEntries
        self.wrapInNavigation = wrapInNavigation
        self.showsInlineChrome = showsInlineChrome ?? wrapInNavigation
        self.onInlineClose = onClose
        self.externalLinkedCardStack = linkedCardStack
    }

    var body: some View {
        Group {
            if let presenterState = state.presenterState {
                WordDetailPresenter(
                    state: presenterState,
                    isExcludedFromReader: entry.isExcludedFromReader,
                    showsChrome: showsInlineChrome,
                    onClose: showsInlineChrome ? { handleClose() } : nil,
                    onEdit: { isEditing = true },
                    onLinkTapped: handleLinkTap,
                    onToggleExcludeFromReader: { entry.isExcludedFromReader.toggle() },
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
                    if let linkError = state.linkError {
                        AppBanner(
                            message: linkError,
                            systemImage: "exclamationmark.triangle",
                            onDismiss: { state.dismissLinkError() }
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
