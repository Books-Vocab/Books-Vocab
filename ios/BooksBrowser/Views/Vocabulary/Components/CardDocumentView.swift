import SwiftUI

struct CardDocumentView: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let document: CardDocument
    var truncateRadius: Int? = nil
    var targetWord: String? = nil
    var compact: Bool = false

    private var blockPadding: CGFloat { compact ? 0 : vocabSkin.metrics.cardBlockPadding }
    private var blockSpacing: CGFloat { compact ? vocabSkin.metrics.reviewFoldSectionSpacing : 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: blockSpacing) {
            ForEach(Array(document.blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case .hero(let hero):
                    CardDocumentHeroBlock(hero: hero)
                        .padding(blockPadding)

                case .example(let paragraph):
                    CardDocumentExampleBlock(paragraph: paragraph, truncateRadius: truncateRadius, targetWord: targetWord)
                        .padding(blockPadding)

                case .divider:
                    if compact {
                        CardSectionDivider(horizontalPadding: 0)
                    } else {
                        CardSectionDivider()
                    }

                case .meaning(let meaning):
                    CardDocumentMeaningBlock(meaning: meaning, compact: compact)
                        .padding(blockPadding)

                case .collocations(let items):
                    CardDocumentCollocationsBlock(items: items)
                        .padding(blockPadding)

                case .source(let source):
                    CardDocumentSourceBlock(source: source)
                        .padding(blockPadding)
                }
            }
        }
    }
}

private struct CardDocumentHeroBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.speechService) private var speechService
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
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

                    HStack(spacing: vocabSkin.spacing.heroBaselineGap) {
                        Button {
                            speechService.speak(hero.word)
                            copyTrigger.toggle()
                        } label: {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(vocabSkin.typography.iconSmall)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .symbolEffect(.bounce, value: copyTrigger)
                                .frame(width: 36, height: 36)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }

                Spacer(minLength: vocabSkin.spacing.blockGap)

                if let tier = hero.difficultyTier {
                    VocabTierLabel(tier: tier)
                }
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = hero.word
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

private struct CardDocumentExampleBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let paragraph: CardDocumentParagraph
    var truncateRadius: Int? = nil
    var targetWord: String? = nil

    var body: some View {
        Group {
            if let radius = truncateRadius {
                CardRichTextRenderer.text(
                    paragraph.rawMarkdown,
                    style: CardRichTextStyle(
                        font: vocabSkin.typography.detailExampleSerif,
                        textColor: vocabSkin.palette.primaryText,
                        highlightColor: vocabSkin.palette.highlightMark,
                        italic: false,
                        underlineHighlights: vocabSkin.highlight.showUnderline,
                        useBackgroundMark: vocabSkin.highlight.showBackground,
                        highlightWeight: vocabSkin.highlight.fontWeight,
                        backgroundOpacity: vocabSkin.highlight.backgroundOpacity,
                        underlineOpacity: vocabSkin.highlight.underlineOpacity
                    ),
                    truncateAroundMarkedWordRadius: radius,
                    targetWord: targetWord
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
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = paragraph.plainText
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

private struct CardDocumentMeaningBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let meaning: CardDocumentMeaning
    var compact: Bool = false

    private var copyText: String {
        let parts = [meaning.title] + meaning.paragraphs.map(\.plainText)
        return parts.joined(separator: "\n")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
            if !meaning.title.isEmpty {
                Text(meaning.title)
                    .font(vocabSkin.typography.translationTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
                ForEach(meaning.paragraphs) { paragraph in
                    CardInlineText(
                        paragraph: paragraph,
                        style: .body
                    )
                    .lineSpacing(compact ? 5 : vocabSkin.metrics.detailLineSpacing)
                    .lineLimit(compact ? 3 : nil)
                }
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = copyText
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

private struct CardDocumentSourceBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let source: CardDocumentSource

    private var copyText: String {
        var parts = [source.bookTitle]
        if let chapter = source.chapterTitle {
            parts.append(chapter)
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "來源".localized, systemImage: "book.closed")

            HStack(spacing: vocabSkin.spacing.sourceMetadataGap) {
                Text(source.bookTitle)
                if let chapterTitle = source.chapterTitle {
                    Text("· \(chapterTitle)")
                }
            }
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.secondaryText)
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = copyText
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

private struct CardDocumentCollocationsBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "搭配".localized, systemImage: "text.word.spacing")

            CollocationFlowLayout(spacing: vocabSkin.metrics.cardBlockInnerGap) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    Text(item)
                        .font(vocabSkin.typography.monoBody)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 6)
                                .fill(vocabSkin.palette.divider.opacity(0.5))
                        )
                }
            }
        }
        .contextMenu {
            Button("複製".localized, systemImage: "doc.on.doc") {
                UIPasteboard.general.string = items.joined(separator: ", ")
                copyTrigger.toggle()
                toastCoordinator.success("已複製")
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
    }
}

// MARK: - Flow Layout

/// 自動折行佈局 — 子視圖超出容器寬度時換行
private struct CollocationFlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        guard !rows.isEmpty else { return .zero }
        let height = rows.reduce(CGFloat(0)) { sum, row in
            sum + row.height
        } + CGFloat(max(rows.count - 1, 0)) * spacing
        return CGSize(width: proposal.width ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        var y = bounds.minY
        var subviewIndex = 0
        for row in rows {
            var x = bounds.minX
            for _ in 0..<row.count {
                let size = subviews[subviewIndex].sizeThatFits(.unspecified)
                subviews[subviewIndex].place(at: CGPoint(x: x, y: y), proposal: .unspecified)
                x += size.width + spacing
                subviewIndex += 1
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var count: Int
        var height: CGFloat
    }

    private func computeRows(proposal: ProposedViewSize, subviews: Subviews) -> [Row] {
        let maxWidth = proposal.width ?? .infinity
        var rows: [Row] = []
        var currentRowWidth: CGFloat = 0
        var currentRowHeight: CGFloat = 0
        var currentRowCount = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            let needed = currentRowCount > 0 ? size.width + spacing : size.width
            if currentRowCount > 0 && currentRowWidth + needed > maxWidth {
                rows.append(Row(count: currentRowCount, height: currentRowHeight))
                currentRowWidth = size.width
                currentRowHeight = size.height
                currentRowCount = 1
            } else {
                currentRowWidth += needed
                currentRowHeight = max(currentRowHeight, size.height)
                currentRowCount += 1
            }
        }
        if currentRowCount > 0 {
            rows.append(Row(count: currentRowCount, height: currentRowHeight))
        }
        return rows
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
        let hl = vocabSkin.highlight
        var part = AttributedString(value)
        part.font = markedFont
        part.foregroundColor = vocabSkin.palette.primaryText
        switch style {
        case .example, .source:
            if hl.showBackground {
                part.backgroundColor = vocabSkin.palette.highlightMark.opacity(hl.backgroundOpacity)
            }
            if hl.showUnderline {
                part.underlineStyle = Text.LineStyle(
                    pattern: .solid,
                    color: vocabSkin.palette.highlightMark.opacity(hl.underlineOpacity)
                )
            }
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
