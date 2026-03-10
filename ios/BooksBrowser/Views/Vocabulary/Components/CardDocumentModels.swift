import Foundation

struct CardDocument {
    let blocks: [CardDocumentBlock]
}

enum CardDocumentBlock: Identifiable {
    case hero(CardDocumentHero)
    case example(CardDocumentParagraph)
    case divider
    case meaning(CardDocumentMeaning)
    case source(CardDocumentSource)

    var id: String {
        switch self {
        case .hero:
            return "hero"
        case .example:
            return "example"
        case .divider:
            return "divider-\(UUID().uuidString)"
        case .meaning:
            return "meaning"
        case .source:
            return "source"
        }
    }
}

struct CardDocumentHero {
    let word: String
    let partOfSpeech: String?
    let pronunciation: String?
    let difficultyTier: String?
    let reviewModeTitle: String
}

struct CardDocumentMeaning {
    let title: String
    let paragraphs: [CardDocumentParagraph]
}

struct CardDocumentSource {
    let context: CardDocumentParagraph
    let bookTitle: String
    let chapterTitle: String?
}

struct CardDocumentParagraph: Identifiable {
    let id = UUID()
    let inlines: [CardDocumentInline]

    var rawMarkdown: String {
        inlines.map { inline in
            switch inline {
            case .text(let v): return v
            case .mark(let v): return "**\(v)**"
            case .code(let v): return "`\(v)`"
            case .emphasis(let v): return v
            }
        }.joined()
    }
}

enum CardDocumentInline: Identifiable {
    case text(String)
    case mark(String)
    case code(String)
    case emphasis(String)

    var id: String {
        switch self {
        case .text(let value):
            return "text-\(value)"
        case .mark(let value):
            return "mark-\(value)"
        case .code(let value):
            return "code-\(value)"
        case .emphasis(let value):
            return "em-\(value)"
        }
    }
}

