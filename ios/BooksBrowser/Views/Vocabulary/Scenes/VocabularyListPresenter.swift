import SwiftUI
import Inject

struct VocabularyListPresenter<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @FocusState private var searchFocused: Bool

    let showsSearchField: Bool
    @Binding var searchText: String
    @ViewBuilder let content: Content

    init(
        showsSearchField: Bool,
        searchText: Binding<String>,
        @ViewBuilder content: () -> Content
    ) {
        self.showsSearchField = showsSearchField
        self._searchText = searchText
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            if showsSearchField {
                VocabSearchField(
                    text: $searchText,
                    prompt: "搜尋單字".localized,
                    isFocused: $searchFocused
                )
                .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
                .padding(.vertical, appSkin.metrics.pageSectionVerticalInset)
                .transition(.listInsert)
            }

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .animation(AppMotion.standardSpring, value: showsSearchField)
        .vocabCanvasBackground()
        .scrollDismissesKeyboard(.interactively)
        .onTapGesture {
            dismissKeyboard()
        }
        .background {
            if showsSearchField {
                Button {
                    searchFocused = true
                } label: {
                    EmptyView()
                }
                .keyboardShortcut("f", modifiers: .command)
                .frame(width: 0, height: 0)
                .hidden()
                .accessibilityHidden(true)
            }
        }
        .enableInjection()
    }
}
