import SwiftUI

struct StyleDemoView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var selectedTab = 1
    @State private var searchText = ""
    private let sampleEntry = StyleDemoSamples.primaryEntry
    private let samplePendingEntry = StyleDemoSamples.pendingEntry
    private let sampleReviewedEntry = StyleDemoSamples.reviewedEntry

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    shellSection
                    rowsSection
                    detailCardSection
                    chromeSection
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 120)
            }
            .navigationTitle("Demo")
            .navigationBarTitleDisplayMode(.inline)
            .vocabCanvasBackground()
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    VocabChromePill(title: "Review", systemImage: "tray.full", count: 47, emphasized: true)
                }
            }
            }
    }

    private var shellSection: some View {
        DemoShowroomSection("Shell") {
            VocabCard {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Skinnable Vocabulary Shell")
                        .font(.system(size: 24, weight: .semibold, design: .default))

                    Text("這頁現在展示的是生詞庫可共用的真實語法層，不是另一套私有 demo theme。之後要換皮，先改 `VocabSkin`，再微調 component。")
                        .font(.system(size: 16, weight: .regular))
                        .foregroundStyle(.secondary)
                        .lineSpacing(4)

                    VocabTabSelector(
                        options: [
                            .init(id: 0, title: "待收錄", count: 12, systemImage: "tray"),
                            .init(id: 1, title: "知識庫", count: 248, systemImage: "books.vertical"),
                            .init(id: 2, title: "關聯圖", systemImage: "point.3.connected.trianglepath.dotted")
                        ],
                        selection: $selectedTab
                    )

                    VocabSearchField(text: $searchText, prompt: "搜尋生詞庫")

                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) {
                            VocabChromePill(title: "Sync", systemImage: "arrow.triangle.2.circlepath")
                            VocabChromePill(title: "Filters", systemImage: "slider.horizontal.3")
                            VocabChromePill(title: "Search", systemImage: "magnifyingglass")
                            VocabChromePill(title: "Review", systemImage: "tray.full", count: 47, emphasized: true)
                        }

                        VStack(alignment: .leading, spacing: 10) {
                            HStack(spacing: 10) {
                                VocabChromePill(title: "Sync", systemImage: "arrow.triangle.2.circlepath")
                                VocabChromePill(title: "Filters", systemImage: "slider.horizontal.3")
                            }
                            HStack(spacing: 10) {
                                VocabChromePill(title: "Search", systemImage: "magnifyingglass")
                                VocabChromePill(title: "Review", systemImage: "tray.full", count: 47, emphasized: true)
                            }
                        }
                    }
                }
            }
        }
    }

    private var rowsSection: some View {
        DemoShowroomSection("Rows") {
            VocabCard {
                VStack(spacing: 0) {
                    WordRow(viewData: samplePendingEntry.wordRowViewData())

                    CardSectionDivider(horizontalPadding: 0)

                    WordRow(
                        viewData: sampleReviewedEntry.wordRowViewData(
                            showsSourceContext: false
                        )
                    )
                }
            }
        }
    }

    private var detailCardSection: some View {
        let card = sampleEntry.cardPresentation

        return DemoShowroomSection("Card Blocks") {
            VocabCard(padding: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    CardDocumentView(document: card.document)

                    if !card.forms.isEmpty {
                        CardSectionDivider()
                        CardFormsSection(forms: card.forms, rootForm: sampleEntry.rootForm, colorScheme: .light)
                            .padding(AppMetrics.spacingLarge)
                    }

                    if let links = card.linkGroups.first {
                        CardSectionDivider()

                        VStack(alignment: .leading, spacing: 10) {
                            CardSectionLabel(title: "知識連結", systemImage: "link")

                            Text(links.label)
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            ForEach(links.items) { link in
                                WordDetailGraphLinkRow(link: link, onTap: nil)
                            }
                        }
                        .padding(AppMetrics.spacingLarge)
                    }
                }
            }
        }
    }

    private var chromeSection: some View {
        DemoShowroomSection("Tone Chips") {
            VocabCard {
                HStack(spacing: 10) {
                    VocabToneChip(text: "core", tone: vocabSkin.palette.success)
                    VocabToneChip(text: "intermediate", tone: vocabSkin.tierColor(for: "intermediate"))
                    VocabToneChip(text: "advanced", tone: vocabSkin.tierColor(for: "advanced"))
                    VocabToneChip(text: "rare", tone: vocabSkin.palette.destructive)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

private struct DemoShowroomSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased())
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.tertiary)
                .tracking(1.8)

            content
        }
    }
}

private enum StyleDemoSamples {
    static let primaryEntry: VocabularyEntry = {
        let entry = VocabularyEntry(
            word: "unravel",
            translation: "解開",
            context: "...knot within him, started to **unravel** and he began to feel...",
            explanation: "解開，闡明。常用於解開謎團、複雜情況或情緒。例：unravel a mystery、unravel the truth。與 untangle 相似，但 unravel 更偏重於理解或梳理。",
            partOfSpeech: "v.",
            pronunciation: "ʌnˈrævəl",
            bookTitle: "Warbreaker",
            chapterTitle: "Chapter 18"
        )
        entry.difficultyTier = "intermediate"
        entry.reviewMode = .recognition
        entry.reviewExamples = [
            "...knot within him, started to **unravel** and he began to feel..."
        ]
        entry.rootForm = "unravel"
        entry.inflections = ["unravel", "unravels", "unraveled", "unraveling"]
        entry.graphLinksByKind = [
            "contrasts_with": [
                .init(
                    id: "1",
                    cardId: "snarls",
                    word: "snarls",
                    kind: "contrasts_with",
                    label: "對比",
                    confidence: 0.88,
                    reason: "情緒釋放方向相反"
                )
            ],
            "confusable": [
                .init(
                    id: "2",
                    cardId: "rile",
                    word: "rile",
                    kind: "confusable",
                    label: "易混",
                    confidence: 0.79,
                    reason: "都可能出現在情緒變化語境"
                )
            ]
        ]
        entry.syncStatus = 1
        return entry
    }()

    static let pendingEntry: VocabularyEntry = {
        let entry = VocabularyEntry(
            word: "audacity",
            translation: "厚顏、大膽",
            context: "...barely dared consider for its **audacity**.",
            explanation: nil,
            partOfSpeech: "n.",
            pronunciation: nil,
            bookTitle: "Warbreaker",
            chapterTitle: "Chapter 12"
        )
        entry.difficultyTier = "intermediate"
        entry.syncStatus = 0
        return entry
    }()

    static let reviewedEntry: VocabularyEntry = {
        let entry = VocabularyEntry(
            word: "croaked",
            translation: "沙啞地說",
            context: "...Shezler **croaked** a final attempt at breath...",
            explanation: nil,
            partOfSpeech: "v.",
            pronunciation: nil,
            bookTitle: "Knowledge Graph",
            chapterTitle: nil
        )
        entry.difficultyTier = "rare"
        entry.syncStatus = 1
        entry.reviewMode = .recognition
        entry.lastReviewedAt = Date()
        entry.reviewIntervalHours = 24
        entry.nextReviewAt = Date().addingTimeInterval(3600 * 18)
        entry.reviewCount = 3
        return entry
    }()
}

#Preview {
    StyleDemoView()
        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
}
