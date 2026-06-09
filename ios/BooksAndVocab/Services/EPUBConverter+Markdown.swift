import Foundation

// MARK: - SimpleMarkdownToHTML

/// Minimal Markdown → HTML converter. No external dependencies.
///
/// Supported syntax:
/// - Headings: `# H1` through `###### H6`
/// - Bold: `**text**`
/// - Italic: `*text*`
/// - Unordered list: `- item`
/// - Ordered list: `1. item`
/// - Inline code: `` `code` ``
/// - Fenced code blocks: ```` ``` ````
/// - Blockquote: `> text`
/// - Paragraphs (blank-line separated)
/// - HTML entity escaping (`<`, `>`, `&`)
///
/// Used by `EPUBConverter.convertMD` to render Markdown source into chapter HTML.
struct SimpleMarkdownToHTML {
    func convert(_ markdown: String) -> String {
        let lines = markdown.components(separatedBy: "\n")
        var html = ""
        var i = 0

        while i < lines.count {
            let line = lines[i]

            // Fenced code block
            if line.hasPrefix("```") {
                i += 1
                var codeLines: [String] = []
                while i < lines.count, !lines[i].hasPrefix("```") {
                    codeLines.append(escapeHTML(lines[i]))
                    i += 1
                }
                if i < lines.count { i += 1 } // skip closing ```
                html += "<pre><code>\(codeLines.joined(separator: "\n"))</code></pre>\n"
                continue
            }

            // Blank line — skip
            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                i += 1
                continue
            }

            // Heading
            if let heading = parseHeading(line) {
                html += heading + "\n"
                i += 1
                continue
            }

            // Blockquote
            if line.hasPrefix("> ") || line == ">" {
                var quoteLines: [String] = []
                while i < lines.count, (lines[i].hasPrefix("> ") || lines[i] == ">") {
                    let content = lines[i].hasPrefix("> ") ? String(lines[i].dropFirst(2)) : ""
                    quoteLines.append(content)
                    i += 1
                }
                let inner = quoteLines.map { inlineFormat(escapeHTML($0)) }.joined(separator: "<br/>")
                html += "<blockquote>\(inner)</blockquote>\n"
                continue
            }

            // Unordered list
            if line.hasPrefix("- ") {
                var items: [String] = []
                while i < lines.count, lines[i].hasPrefix("- ") {
                    items.append(inlineFormat(escapeHTML(String(lines[i].dropFirst(2)))))
                    i += 1
                }
                html += "<ul>\n" + items.map { "<li>\($0)</li>" }.joined(separator: "\n") + "\n</ul>\n"
                continue
            }

            // Ordered list
            if isOrderedListItem(line) {
                var items: [String] = []
                while i < lines.count, isOrderedListItem(lines[i]) {
                    let text = stripOrderedPrefix(lines[i])
                    items.append(inlineFormat(escapeHTML(text)))
                    i += 1
                }
                html += "<ol>\n" + items.map { "<li>\($0)</li>" }.joined(separator: "\n") + "\n</ol>\n"
                continue
            }

            // Paragraph — collect consecutive non-blank, non-special lines
            var paraLines: [String] = []
            while i < lines.count {
                let l = lines[i]
                let trimmed = l.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty || l.hasPrefix("```") || l.hasPrefix("# ") ||
                    l.hasPrefix("## ") || l.hasPrefix("### ") || l.hasPrefix("#### ") ||
                    l.hasPrefix("##### ") || l.hasPrefix("###### ") ||
                    l.hasPrefix("> ") || l == ">" || l.hasPrefix("- ") || isOrderedListItem(l) {
                    break
                }
                paraLines.append(inlineFormat(escapeHTML(l)))
                i += 1
            }
            if !paraLines.isEmpty {
                html += "<p>\(paraLines.joined(separator: "\n"))</p>\n"
            }
        }

        return html
    }

    // MARK: Helpers

    private func escapeHTML(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private func inlineFormat(_ text: String) -> String {
        var result = text

        // Inline code (must be before bold/italic to avoid conflicts)
        result = replacePattern(result, pattern: "`([^`]+)`", template: "<code>$1</code>")

        // Bold
        result = replacePattern(result, pattern: "\\*\\*(.+?)\\*\\*", template: "<strong>$1</strong>")

        // Italic (single *)
        result = replacePattern(result, pattern: "\\*(.+?)\\*", template: "<em>$1</em>")

        return result
    }

    private func replacePattern(_ text: String, pattern: String, template: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        let range = NSRange(text.startIndex..., in: text)
        return regex.stringByReplacingMatches(in: text, range: range, withTemplate: template)
    }

    private func parseHeading(_ line: String) -> String? {
        var level = 0
        for ch in line {
            if ch == "#" { level += 1 } else { break }
        }
        guard level >= 1, level <= 6, line.count > level, line[line.index(line.startIndex, offsetBy: level)] == " " else {
            return nil
        }
        let text = inlineFormat(escapeHTML(String(line.dropFirst(level + 1))))
        return "<h\(level)>\(text)</h\(level)>"
    }

    private func isOrderedListItem(_ line: String) -> Bool {
        guard let dotIdx = line.firstIndex(of: ".") else { return false }
        let prefix = line[line.startIndex..<dotIdx]
        guard !prefix.isEmpty, prefix.allSatisfy(\.isNumber) else { return false }
        let afterDot = line.index(after: dotIdx)
        return afterDot < line.endIndex && line[afterDot] == " "
    }

    private func stripOrderedPrefix(_ line: String) -> String {
        guard let dotIdx = line.firstIndex(of: ".") else { return line }
        let afterDot = line.index(after: dotIdx)
        guard afterDot < line.endIndex, line[afterDot] == " " else { return line }
        return String(line[line.index(after: afterDot)...])
    }
}
