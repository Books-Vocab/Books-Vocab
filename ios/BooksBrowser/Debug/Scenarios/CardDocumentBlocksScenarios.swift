#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the individual document blocks defined in
/// `CardDocumentView.swift`:
/// - `CardDocumentHeroBlock` (單字 / 詞性 / 難度標籤 / 發音按鈕)
/// - `CardDocumentExampleBlock` (例句 rich text，可截斷)
/// - `CardDocumentMeaningBlock` (釋義標題 + 段落，compact 限行)
/// - `CardDocumentSourceBlock` (來源書名 / 章節)
/// - `CardDocumentCollocationsBlock` (搭配 pill flow layout)
///
/// All blocks take plain value types (`CardDocument*` models + optional
/// closures); the `@Environment(\.appSkin / .speechService / .toastCoordinator)`
/// dependencies resolve from env defaults inside `AppThemeContainer`, so each
/// block can be constructed directly inside the (nonisolated) Scenario closures.
/// Wrapped in a padded `AppThemeContainer` to give the snapshot context.
enum CardDocumentBlocksScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Hero
        playbook.addScenarios(of: "Card Document · Hero") {
            Scenario("Full (詞性 + 難度)", layout: .compressed) {
                BlockShell {
                    CardDocumentHeroBlock(
                        hero: CardDocumentBlocksFixtures.hero(
                            word: "serendipity",
                            partOfSpeech: "n.",
                            difficultyTier: "advanced"
                        )
                    )
                }
            }
            Scenario("無詞性 / 無難度", layout: .compressed) {
                BlockShell {
                    CardDocumentHeroBlock(
                        hero: CardDocumentBlocksFixtures.hero(
                            word: "go",
                            partOfSpeech: nil,
                            difficultyTier: nil
                        )
                    )
                }
            }
            Scenario("超長單字", layout: .compressed) {
                BlockShell {
                    CardDocumentHeroBlock(
                        hero: CardDocumentBlocksFixtures.hero(
                            word: "antidisestablishmentarianism",
                            partOfSpeech: "n.",
                            difficultyTier: "rare"
                        )
                    )
                }
            }
        }

        // MARK: Example
        playbook.addScenarios(of: "Card Document · Example") {
            Scenario("Default (inline rich)", layout: .compressed) {
                BlockShell {
                    CardDocumentExampleBlock(
                        paragraph: CardDocumentBlocksFixtures.richParagraph
                    )
                }
            }
            Scenario("Truncated around mark", layout: .compressed) {
                BlockShell {
                    CardDocumentExampleBlock(
                        paragraph: CardDocumentBlocksFixtures.longParagraph,
                        truncateRadius: 6,
                        targetWord: "serendipity"
                    )
                }
            }
        }

        // MARK: Meaning
        playbook.addScenarios(of: "Card Document · Meaning") {
            Scenario("標題 + 段落", layout: .compressed) {
                BlockShell {
                    CardDocumentMeaningBlock(
                        meaning: CardDocumentBlocksFixtures.meaning
                    )
                }
            }
            Scenario("無標題", layout: .compressed) {
                BlockShell {
                    CardDocumentMeaningBlock(
                        meaning: CardDocumentMeaning(
                            title: "",
                            paragraphs: [CardDocumentBlocksFixtures.richParagraph]
                        )
                    )
                }
            }
            Scenario("Compact (限 3 行)", layout: .compressed) {
                BlockShell {
                    CardDocumentMeaningBlock(
                        meaning: CardDocumentBlocksFixtures.longMeaning,
                        compact: true
                    )
                }
            }
        }

        // MARK: Source
        playbook.addScenarios(of: "Card Document · Source") {
            Scenario("書名 + 章節", layout: .compressed) {
                BlockShell {
                    CardDocumentSourceBlock(
                        source: CardDocumentSource(
                            context: CardDocumentBlocksFixtures.richParagraph,
                            bookTitle: "Pride and Prejudice",
                            chapterTitle: "Chapter 3"
                        )
                    )
                }
            }
            Scenario("僅書名", layout: .compressed) {
                BlockShell {
                    CardDocumentSourceBlock(
                        source: CardDocumentSource(
                            context: CardDocumentBlocksFixtures.richParagraph,
                            bookTitle: "The Great Gatsby",
                            chapterTitle: nil
                        )
                    )
                }
            }
        }

        // MARK: Collocations
        playbook.addScenarios(of: "Card Document · Collocations") {
            Scenario("Default", layout: .compressed) {
                BlockShell {
                    CardDocumentCollocationsBlock(
                        items: ["happy serendipity", "pure serendipity", "by serendipity"]
                    )
                }
            }
            Scenario("部分已解釋", layout: .compressed) {
                BlockShell {
                    CardDocumentCollocationsBlock(
                        items: ["happy serendipity", "pure serendipity", "by serendipity"],
                        explanations: ["pure serendipity": "純粹的機緣巧合"]
                    )
                }
            }
            Scenario("Many (overflow flow)", layout: .compressed) {
                BlockShell {
                    CardDocumentCollocationsBlock(
                        items: [
                            "happy serendipity", "pure serendipity", "by serendipity",
                            "sheer serendipity", "fortunate serendipity", "a moment of serendipity",
                            "serendipity strikes", "find by serendipity",
                        ]
                    )
                }
            }
            Scenario("Compact (限 2 行)", layout: .compressed) {
                BlockShell {
                    CardDocumentCollocationsBlock(
                        items: [
                            "happy serendipity", "pure serendipity", "by serendipity",
                            "sheer serendipity", "fortunate serendipity", "a moment of serendipity",
                        ],
                        compact: true
                    )
                }
            }
        }
    }
}

// MARK: - Fixtures

private enum CardDocumentBlocksFixtures {
    static func hero(
        word: String,
        partOfSpeech: String?,
        difficultyTier: String?
    ) -> CardDocumentHero {
        CardDocumentHero(
            word: word,
            partOfSpeech: partOfSpeech,
            difficultyTier: difficultyTier,
            reviewModeTitle: ""
        )
    }

    static var richParagraph: CardDocumentParagraph {
        CardDocumentParagraph(inlines: [
            .text("A happy "),
            .mark("serendipity"),
            .text(" brought them together — "),
            .emphasis("entirely"),
            .text(" by chance, as the "),
            .code("README"),
            .text(" predicted."),
        ])
    }

    static var longParagraph: CardDocumentParagraph {
        CardDocumentParagraph(inlines: [
            .text("After years of fruitless searching across distant libraries and forgotten archives, it was by pure "),
            .mark("serendipity"),
            .text(" that the scholar finally stumbled upon the missing manuscript tucked behind a dusty shelf."),
        ])
    }

    static var meaning: CardDocumentMeaning {
        CardDocumentMeaning(
            title: "機緣巧合",
            paragraphs: [richParagraph]
        )
    }

    static var longMeaning: CardDocumentMeaning {
        CardDocumentMeaning(
            title: "機緣巧合",
            paragraphs: [
                CardDocumentParagraph(inlines: [
                    .text("指意外發現珍貴或令人愉悅事物的能力或現象。常用於描述不經意間的好運，例如在不刻意尋找時遇見契合之人、發現靈感來源，或在偶然之中獲得突破性的進展，往往帶有命運安排般的美好意味。"),
                ]),
            ]
        )
    }
}

// MARK: - Scene harness

/// Generic themed shell. All blocks take plain value types and resolve their
/// env dependencies from defaults inside `AppThemeContainer`, so they construct
/// directly inside Scenario closures (no `@MainActor` init needed).
private struct BlockShell<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        AppThemeContainer {
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
