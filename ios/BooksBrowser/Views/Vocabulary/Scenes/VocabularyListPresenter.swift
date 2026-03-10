import SwiftUI

struct VocabularyListPresenterState {
    let tabOptions: [VocabTabOption<Int>]
    let showsSearchField: Bool
    let searchPrompt: String
}

struct VocabularyListPresenter<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: VocabularyListPresenterState
    @Binding var selectedTab: Int
    @Binding var searchText: String
    @ViewBuilder let content: Content

    init(
        state: VocabularyListPresenterState,
        selectedTab: Binding<Int>,
        searchText: Binding<String>,
        @ViewBuilder content: () -> Content
    ) {
        self.state = state
        self._selectedTab = selectedTab
        self._searchText = searchText
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            VocabTabSelector(options: state.tabOptions, selection: $selectedTab)
                .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
                .padding(.vertical, vocabSkin.metrics.pageSectionVerticalInset)

            if state.showsSearchField {
                VocabSearchField(
                    text: $searchText,
                    prompt: state.searchPrompt
                )
                .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
                .padding(.bottom, vocabSkin.metrics.pageSectionVerticalInset)
            }

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .animation(.none, value: selectedTab)
        }
        .vocabCanvasBackground()
        .scrollDismissesKeyboard(.interactively)
        .onTapGesture {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        }
    }
}
