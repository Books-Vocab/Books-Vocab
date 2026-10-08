import Foundation

enum CardMarkdownInlineParser {
    private static let demotedLeadingMarkers: Set<String> = [
        "名詞", "動詞", "形容詞", "副詞", "介系詞", "代名詞", "連接詞", "感嘆詞",
        "片語", "短語", "縮寫", "冠詞", "數詞",
        "noun", "verb", "adjective", "adverb", "preposition", "pronoun", "conjunction",
        "interjection", "phrase", "n.", "v.", "adj.", "adv.", "prep.", "pron.", "conj.", "phr."
    ]

    static func parseParagraph(_ raw: String) -> CardDocumentParagraph {
        CardDocumentParagraph(inlines: normalizeLeadingMarker(parseInlines(raw)))
    }

    static func parseInlines(_ raw: String) -> [CardDocumentInline] {
        var result: [CardDocumentInline] = []
        var index = raw.startIndex
        var buffer = ""

        func flushBuffer() {
            guard !buffer.isEmpty else { return }
            result.append(.text(buffer))
            buffer.removeAll(keepingCapacity: true)
        }

        while index < raw.endIndex {
            if raw[index...].hasPrefix("=="), let end = raw[index...].dropFirst(2).range(of: "==") {
                flushBuffer()
                let contentStart = raw.index(index, offsetBy: 2)
                let value = String(raw[contentStart..<end.lowerBound])
                if !value.isEmpty {
                    result.append(.mark(value))
                }
                index = end.upperBound
                continue
            }

            if raw[index...].hasPrefix("**"), let end = raw[index...].dropFirst(2).range(of: "**") {
                flushBuffer()
                let contentStart = raw.index(index, offsetBy: 2)
                let value = String(raw[contentStart..<end.lowerBound])
                if !value.isEmpty {
                    result.append(.mark(value))
                }
                index = end.upperBound
                continue
            }

            if raw[index] == "`", let end = raw[raw.index(after: index)...].firstIndex(of: "`") {
                flushBuffer()
                let value = String(raw[raw.index(after: index)..<end])
                if !value.isEmpty {
                    result.append(.code(value))
                }
                index = raw.index(after: end)
                continue
            }

            if raw[index] == "_", let end = emphasisCloser(in: raw, openedAt: index) {
                flushBuffer()
                let value = String(raw[raw.index(after: index)..<end])
                if !value.isEmpty {
                    result.append(.emphasis(value))
                }
                index = raw.index(after: end)
                continue
            }

            buffer.append(raw[index])
            index = raw.index(after: index)
        }

        flushBuffer()
        return result
    }

    /// CommonMark intraword rule for `_`: the opener must follow a boundary (start, whitespace or
    /// punctuation) and precede non-whitespace; the closer is the first later `_` that follows
    /// non-whitespace and precedes a boundary. Anything else stays literal (`snake_case`).
    private static func emphasisCloser(in raw: String, openedAt opener: String.Index) -> String.Index? {
        let contentStart = raw.index(after: opener)
        guard isBoundary(opener > raw.startIndex ? raw[raw.index(before: opener)] : nil),
              contentStart < raw.endIndex,
              !isWhitespace(raw[contentStart])
        else { return nil }

        var candidate = contentStart
        while let close = raw[candidate...].firstIndex(of: "_") {
            let after = raw.index(after: close)
            if !isWhitespace(raw[raw.index(before: close)]),
               isBoundary(after < raw.endIndex ? raw[after] : nil) {
                return close
            }
            candidate = after
        }
        return nil
    }

    private static func isWhitespace(_ character: Character) -> Bool {
        character.unicodeScalars.allSatisfy { CharacterSet.whitespacesAndNewlines.contains($0) }
    }

    /// `nil` models the string edge.
    private static func isBoundary(_ character: Character?) -> Bool {
        guard let character else { return true }
        return isWhitespace(character)
            || character.unicodeScalars.allSatisfy { CharacterSet.punctuationCharacters.contains($0) }
    }

    private static func normalizeLeadingMarker(_ inlines: [CardDocumentInline]) -> [CardDocumentInline] {
        guard !inlines.isEmpty else { return inlines }

        let firstContentIndex = inlines.firstIndex { inline in
            switch inline {
            case .text(let value):
                return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .mark, .code, .emphasis:
                return true
            }
        }

        guard
            let index = firstContentIndex,
            case .mark(let value) = inlines[index],
            shouldDemoteLeadingMarker(value, following: Array(inlines.dropFirst(index + 1)))
        else {
            return inlines
        }

        var normalized = inlines
        normalized[index] = .text(value)
        return normalized
    }

    private static func shouldDemoteLeadingMarker(
        _ value: String,
        following: [CardDocumentInline]
    ) -> Bool {
        let normalizedValue = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard demotedLeadingMarkers.contains(normalizedValue) else { return false }

        guard let next = following.first else { return true }
        switch next {
        case .text(let text):
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.hasPrefix("，") || trimmed.hasPrefix(",") || trimmed.hasPrefix("：") || trimmed.hasPrefix(":")
        case .mark, .code, .emphasis:
            return false
        }
    }
}
