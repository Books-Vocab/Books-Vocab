import SwiftUI

struct CardDocumentView: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let document: CardDocument
    var truncateRadius: Int? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(document.blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case .hero(let hero):
                    CardDocumentHeroBlock(hero: hero)
                        .padding(vocabSkin.metrics.cardBlockPadding)

                case .example(let paragraph):
                    CardDocumentExampleBlock(paragraph: paragraph, truncateRadius: truncateRadius)
                        .padding(vocabSkin.metrics.cardBlockPadding)

                case .divider:
                    CardSectionDivider()

                case .meaning(let meaning):
                    CardDocumentMeaningBlock(meaning: meaning)
                        .padding(vocabSkin.metrics.cardBlockPadding)

                case .source(let source):
                    CardDocumentSourceBlock(source: source)
                        .padding(vocabSkin.metrics.cardBlockPadding)
                }
            }
        }
    }
}

private struct CardDocumentHeroBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let hero: CardDocumentHero

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            HStack(alignment: .top, spacing: vocabSkin.metrics.cardBlockContentGap) {
                VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                    HStack(alignment: .firstTextBaseline, spacing: vocabSkin.spacing.heroBaselineGap) {
                        Text(hero.word)
                            .font(vocabSkin.typography.detailWord)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                            .minimumScaleFactor(0.85)

                        if let pos = hero.partOfSpeech {
                            Text(pos)
                                .font(vocabSkin.typography.body.weight(.medium))
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                    }

                    if let pronunciation = hero.pronunciation, !pronunciation.isEmpty {
                        Text("/\(pronunciation)/")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
                    }
                }

                Spacer(minLength: vocabSkin.spacing.blockGap)

                if let tier = hero.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }

        }
    }
}

private struct CardDocumentExampleBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let paragraph: CardDocumentParagraph
    var truncateRadius: Int? = nil

    var body: some View {
        if let radius = truncateRadius {
            CardRichTextRenderer.text(
                paragraph.rawMarkdown,
                style: CardRichTextStyle(
                    font: vocabSkin.typography.detailExampleSerif,
                    textColor: vocabSkin.palette.primaryText,
                    highlightColor: vocabSkin.palette.highlightMark,
                    italic: false
                ),
                truncateAroundMarkedWordRadius: radius
            )
            .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
        } else {
            CardInlineText(
                paragraph: paragraph,
                style: .example
            )
            .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
        }
    }
}

private struct CardDocumentMeaningBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let meaning: CardDocumentMeaning

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            Text(meaning.title)
                .font(vocabSkin.typography.translationTitle)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
                ForEach(meaning.paragraphs) { paragraph in
                    CardInlineText(
                        paragraph: paragraph,
                        style: .body
                    )
                    .lineSpacing(vocabSkin.metrics.detailLineSpacing)
                }
            }
        }
    }
}

private struct CardDocumentSourceBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let source: CardDocumentSource

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "來源", systemImage: "quote.opening")

            CardInlineText(
                paragraph: source.context,
                style: .source
            )
            .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)

            HStack(spacing: vocabSkin.spacing.sourceMetadataGap) {
                Image(systemName: "book.closed")
                    .font(vocabSkin.typography.iconTiny)
                Text(source.bookTitle)
                if let chapterTitle = source.chapterTitle {
                    Text("· \(chapterTitle)")
                }
            }
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
    }
}

struct CardInlineText: View {
    enum Style {
        case example
        case body
        case source
    }

    @Environment(\.vocabSkin) private var vocabSkin

    let paragraph: CardDocumentParagraph
    let style: Style

    var body: some View {
        Text(attributedText)
    }

    private var attributedText: AttributedString {
        var result = AttributedString()
        for inline in paragraph.inlines {
            result += makePart(for: inline)
        }
        return result
    }

    private func makePart(for inline: CardDocumentInline) -> AttributedString {
        switch inline {
        case .text(let value):
            return plain(value)
        case .mark(let value):
            return marked(value)
        case .code(let value):
            return code(value)
        case .emphasis(let value):
            return emphasis(value)
        }
    }

    private func plain(_ value: String) -> AttributedString {
        var part = AttributedString(value)
        part.font = baseFont
        part.foregroundColor = baseColor
        return part
    }

    private func marked(_ value: String) -> AttributedString {
        var part = AttributedString(value)
        part.font = markedFont
        part.foregroundColor = vocabSkin.palette.primaryText
        switch style {
        case .example, .source:
            part.underlineStyle = Text.LineStyle(
                pattern: .solid,
                color: vocabSkin.palette.highlightMarkSubtle
            )
        case .body:
            break
        }
        return part
    }

    private func code(_ value: String) -> AttributedString {
        var part = AttributedString(value)
        part.font = vocabSkin.typography.monoBody
        part.foregroundColor = vocabSkin.palette.secondaryText
        return part
    }

    private func emphasis(_ value: String) -> AttributedString {
        var part = AttributedString(value)
        part.font = baseFont.italic()
        part.foregroundColor = baseColor
        return part
    }

    private var baseFont: Font {
        switch style {
        case .example:
            return vocabSkin.typography.detailExampleSerif
        case .body:
            return vocabSkin.typography.body
        case .source:
            return vocabSkin.typography.body.italic()
        }
    }

    private var markedFont: Font {
        switch style {
        case .example:
            return vocabSkin.typography.detailExampleSerifStrong
        case .body:
            return vocabSkin.typography.body.weight(.medium)
        case .source:
            return vocabSkin.typography.body.weight(.medium).italic()
        }
    }

    private var baseColor: Color {
        switch style {
        case .example:
            return vocabSkin.palette.primaryText
        case .body:
            return vocabSkin.palette.secondaryText
        case .source:
            return vocabSkin.palette.secondaryText
        }
    }
}
