import SwiftUI

struct VocabularyListPresenterState {
    let tabOptions: [VocabTabOption<Int>]
    let showsSearchField: Bool
    let searchPrompt: String
}

struct VocabularyListPresenter<Content: View>: View {
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
                .padding(.horizontal)
                .padding(.vertical, 8)

            if state.showsSearchField {
                VocabSearchField(
                    text: $searchText,
                    prompt: state.searchPrompt
                )
                .padding(.horizontal)
                .padding(.bottom, 8)
            }

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .animation(.none, value: selectedTab)
        }
        .vocabCanvasBackground()
    }
}
