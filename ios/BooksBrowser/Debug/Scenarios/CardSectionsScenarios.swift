#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the card body sub-sections defined in
/// `CardSections.swift` + `CardDocumentView.swift`. Each section is rendered in
/// isolation with synthetic data so visual-regression snapshots can track the
/// individual slices (hero / examples / explanation / forms / source / labels /
/// dividers / inline rich text) independently from the assembled card.
enum CardSectionsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Hero
        playbook.addScenarios(of: "Card Sections · Hero") {
            Scenario("Full hero", layout: .fill) {
                CardHeroScene(word: "serendipity", pos: "n.", tier: "advanced", mode: .recognition)
            }
            Scenario("No POS / no tier", layout: .fill) {
                CardHeroScene(word: "go", pos: nil, tier: nil, mode: .production)
            }
            Scenario("Long word + long translation", layout: .fill) {
                CardHeroScene(
                    word: "antidisestablishmentarianism",
                    pos: "n.",
                    tier: "rare",
                    mode: .recognition
                )
            }
        }

        // MARK: Examples
        playbook.addScenarios(of: "Card Sections · Examples") {
            Scenario("Single example", layout: .fill) {
                CardSectionShell {
                    CardExamplesSection(
                        examples: ["It was pure **serendipity** that we met that day."],
                        colorScheme: .light
                    )
                }
            }
            Scenario("Multiple examples", layout: .fill) {
                CardSectionShell {
                    CardExamplesSection(
                        examples: [
                            "A happy **serendipity** brought the two strangers together.",
                            "She discovered the cafe by **serendipity**, not by plan.",
                            "Their meeting was **serendipity** at its finest.",
                        ],
                        colorScheme: .light
                    )
                }
            }
        }

        // MARK: Explanation
        playbook.addScenarios(of: "Card Sections · Explanation") {
            Scenario("Rich note", layout: .fill) {
                CardSectionShell {
                    CardExplanationSection(
                        explanation: "**Serendipity** describes a fortunate accident — finding something valuable without looking for it. Often used in writing and casual speech.",
                        colorScheme: .light
                    )
                }
            }
        }

        // MARK: Forms
        playbook.addScenarios(of: "Card Sections · Forms") {
            Scenario("With root highlighted", layout: .fill) {
                CardSectionShell {
                    CardFormsSection(
                        forms: ["run", "runs", "ran", "running"],
                        rootForm: "run",
                        colorScheme: .light
                    )
                }
            }
            Scenario("Many forms (overflow)", layout: .fill) {
                CardSectionShell {
                    CardFormsSection(
                        forms: ["analyse", "analyses", "analysed", "analysing", "analysis", "analyses", "analytical"],
                        rootForm: "analyse",
                        colorScheme: .light
                    )
                }
            }
        }

        // MARK: Source
        playbook.addScenarios(of: "Card Sections · Source") {
            Scenario("Book + chapter", layout: .fill) {
                CardSectionShell {
                    CardSourceSection(
                        sourceContext: "It was pure serendipity that we met.",
                        bookTitle: "Pride and Prejudice",
                        chapterTitle: "Chapter 3"
                    )
                }
            }
            Scenario("Book only", layout: .fill) {
                CardSectionShell {
                    CardSourceSection(
                        sourceContext: "It was pure serendipity that we met.",
                        bookTitle: "The Great Gatsby",
                        chapterTitle: nil
                    )
                }
            }
        }

        // MARK: Primitives
        playbook.addScenarios(of: "Card Sections · Primitives") {
            Scenario("Section label", layout: .fill) {
                CardSectionShell {
                    VStack(alignment: .leading, spacing: 16) {
                        CardSectionLabel(title: "例句", systemImage: "text.quote")
                        CardSectionLabel(title: "教學筆記", systemImage: "text.book.closed")
                        CardSectionLabel(title: "來源", systemImage: "book.closed")
                    }
                }
            }
            Scenario("Section divider", layout: .fill) {
                CardSectionShell {
                    VStack(spacing: 24) {
                        Text("Above")
                        CardSectionDivider()
                        Text("Below")
                    }
                }
            }
            Scenario("Inline rich text", layout: .fill) {
                CardSectionShell {
                    VStack(alignment: .leading, spacing: 16) {
                        CardInlineText(paragraph: CardSectionsFixtures.richParagraph, style: .example)
                        CardSectionDivider()
                        CardInlineText(paragraph: CardSectionsFixtures.richParagraph, style: .body)
                    }
                }
            }
        }

        // MARK: Assembled document (CardDocumentView)
        playbook.addScenarios(of: "Card Sections · Document") {
            Scenario("Full document", layout: .fill) {
                CardDocumentScene(compact: false)
            }
            Scenario("Compact (review back)", layout: .fill) {
                CardDocumentScene(compact: true)
            }
        }
    }
}

// MARK: - Fixtures

private enum CardSectionsFixtures {
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

    static var document: CardDocument {
        CardDocument(blocks: [
            .hero(CardDocumentHero(
                word: "serendipity",
                partOfSpeech: "n.",
                difficultyTier: "advanced",
                reviewModeTitle: VocabularyCardMode.recognition.localizedTitle
            )),
            .divider,
            .meaning(CardDocumentMeaning(
                title: "機緣巧合",
                paragraphs: [richParagraph]
            )),
            .divider,
            .example(richParagraph),
            .divider,
            .collocations(["happy serendipity", "pure serendipity", "by serendipity"]),
            .divider,
            .source(CardDocumentSource(
                context: richParagraph,
                bookTitle: "Pride and Prejudice",
                chapterTitle: "Chapter 3"
            )),
        ])
    }
}

// MARK: - Scene harnesses (@MainActor-isolated bodies)

/// Generic shell that themes a synthetic section view. Used for sections whose
/// inputs are plain value types (examples / explanation / forms / source / primitives).
private struct CardSectionShell<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        AppThemeContainer {
            ScrollView {
                content
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(24)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

/// Hero needs a `CardPresentation`, which is built from a synthetic
/// `VocabularyEntry` inside a main-actor body (entry init reads current locale).
private struct CardHeroScene: View {
    let word: String
    let pos: String?
    let tier: String?
    let mode: VocabularyCardMode

    var body: some View {
        AppThemeContainer {
            ScrollView {
                CardHeroSection(card: makePresentation(), colorScheme: .light)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(24)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private func makePresentation() -> CardPresentation {
        let entry = VocabularyEntry(
            word: word,
            translation: "機緣巧合；意外發現珍貴事物的能力",
            context: "It was pure \(word) that we met.",
            explanation: "A happy accident; finding something good without looking for it.",
            partOfSpeech: pos,
            bookTitle: "Sample Book"
        )
        entry.difficultyTier = tier
        entry.reviewModeRaw = mode.rawValue
        return CardPresentation(entry: entry)
    }
}

private struct CardDocumentScene: View {
    let compact: Bool

    var body: some View {
        AppThemeContainer {
            ScrollView {
                CardDocumentView(document: CardSectionsFixtures.document, compact: compact)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(compact ? 8 : 0)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
