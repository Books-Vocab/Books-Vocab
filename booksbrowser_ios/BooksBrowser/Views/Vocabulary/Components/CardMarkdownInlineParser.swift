import Foundation

enum CardMarkdownInlineParser {
    static func parseParagraph(_ raw: String) -> CardDocumentParagraph {
        CardDocumentParagraph(inlines: parseInlines(raw))
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

            if raw[index] == "_", let end = raw[raw.index(after: index)...].firstIndex(of: "_") {
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
}

