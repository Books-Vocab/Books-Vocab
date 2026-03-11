import Foundation
import SwiftUI

struct CardRichTextStyle {
    let font: Font
    let textColor: Color
    let highlightColor: Color
    let italic: Bool
    var underlineHighlights: Bool = true
    var useBackgroundMark: Bool = false
    var highlightWeight: Font.Weight = .semibold
}

enum CardRichTextMode {
    case highlight
    case cloze
}

enum CardRichTextRenderer {
    private static let inlinePattern = try! NSRegularExpression(
        pattern: "\\*\\*(.+?)\\*\\*|`([^`]+)`"
    )

    private static let markedWordPattern = try! NSRegularExpression(
        pattern: "\\*\\*.+?\\*\\*"
    )

    private static let tokenPattern = try! NSRegularExpression(
        pattern: "\\S+"
    )

    static func text(
        _ raw: String,
        style: CardRichTextStyle,
        mode: CardRichTextMode = .highlight,
        truncateAroundMarkedWordRadius: Int? = nil,
        targetWord: String? = nil
    ) -> Text {
        Text(
            attributedString(
                raw,
                style: style,
                mode: mode,
                truncateAroundMarkedWordRadius: truncateAroundMarkedWordRadius,
                targetWord: targetWord
            )
        )
    }

    static func attributedString(
        _ raw: String,
        style: CardRichTextStyle,
        mode: CardRichTextMode = .highlight,
        truncateAroundMarkedWordRadius: Int? = nil,
        targetWord: String? = nil
    ) -> AttributedString {
        let prepared = preparedRaw(
            from: raw,
            mode: mode,
            truncateAroundMarkedWordRadius: truncateAroundMarkedWordRadius,
            targetWord: targetWord
        )

        let nsString = prepared as NSString
        let matches = inlinePattern.matches(
            in: prepared,
            range: NSRange(location: 0, length: nsString.length)
        )

        guard !matches.isEmpty else {
            return plainAttributedString(prepared, style: style)
        }

        var result = AttributedString()
        var lastEnd = 0

        for match in matches {
            let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
            if beforeRange.length > 0 {
                result += plainAttributedString(nsString.substring(with: beforeRange), style: style)
            }

            let boldRange = match.range(at: 1)
            let codeRange = match.range(at: 2)
            let captureRange = boldRange.location != NSNotFound ? boldRange : codeRange

            if captureRange.location != NSNotFound, captureRange.length > 0 {
                result += highlightedAttributedString(
                    nsString.substring(with: captureRange),
                    style: style
                )
            }

            lastEnd = match.range.location + match.range.length
        }

        if lastEnd < nsString.length {
            result += plainAttributedString(nsString.substring(from: lastEnd), style: style)
        }

        return result
    }

    private static func preparedRaw(
        from raw: String,
        mode: CardRichTextMode,
        truncateAroundMarkedWordRadius: Int?,
        targetWord: String? = nil
    ) -> String {
        let truncated: String
        if let radius = truncateAroundMarkedWordRadius, radius >= 0 {
            truncated = truncateAroundMarkedWord(raw, radiusWords: radius, targetWordFallback: targetWord)
        } else {
            truncated = raw
        }

        switch mode {
        case .highlight:
            return truncated
        case .cloze:
            return clozeMarkedWord(in: truncated)
        }
    }

    private static func plainAttributedString(
        _ value: String,
        style: CardRichTextStyle
    ) -> AttributedString {
        var part = AttributedString(value)
        part.font = style.italic ? style.font.italic() : style.font
        part.foregroundColor = style.textColor
        return part
    }

    private static func highlightedAttributedString(
        _ value: String,
        style: CardRichTextStyle
    ) -> AttributedString {
        var part = AttributedString(value)
        let highlightFont = style.italic
            ? style.font.weight(style.highlightWeight).italic()
            : style.font.weight(style.highlightWeight)
        part.font = highlightFont
        part.foregroundColor = style.textColor

        if style.useBackgroundMark {
            part.backgroundColor = style.highlightColor.opacity(0.18)
        }

        if style.underlineHighlights {
            part.underlineStyle = Text.LineStyle(
                pattern: .solid,
                color: style.highlightColor.opacity(0.68)
            )
        }

        return part
    }

    static func clozeMarkedWord(in raw: String) -> String {
        let nsString = raw as NSString
        return markedWordPattern.stringByReplacingMatches(
            in: raw,
            range: NSRange(location: 0, length: nsString.length),
            withTemplate: "______"
        )
    }

    static func truncateAroundMarkedWord(
        _ raw: String,
        radiusWords: Int = 5,
        targetWordFallback: String? = nil
    ) -> String {
        guard radiusWords >= 0 else { return raw }

        let nsRaw = raw as NSString
        guard
            let match = markedWordPattern.firstMatch(
                in: raw,
                range: NSRange(location: 0, length: nsRaw.length)
            )
        else {
            // 無標記詞：嘗試以 targetWord 動態建立標記後截斷
            if let fallback = targetWordFallback, !fallback.isEmpty {
                let escapedFallback = NSRegularExpression.escapedPattern(for: fallback)
                let pattern = "(?<![\\w\\p{L}])\(escapedFallback)(?![\\w\\p{L}])"
                if let wordRegex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive),
                   let wordMatch = wordRegex.firstMatch(in: raw, range: NSRange(location: 0, length: nsRaw.length)) {
                    let actualWord = nsRaw.substring(with: wordMatch.range)
                    let marked = nsRaw.substring(to: wordMatch.range.location)
                        + "**\(actualWord)**"
                        + nsRaw.substring(from: wordMatch.range.location + wordMatch.range.length)
                    return truncateAroundMarkedWord(marked, radiusWords: radiusWords)
                }
            }
            // 完全找不到目標詞：顯示前 (2*radius+1) 個詞
            return truncateLeadingWords(raw, count: 2 * radiusWords + 1)
        }

        let beforeText = nsRaw.substring(to: match.range.location)
        let afterStart = match.range.location + match.range.length
        let afterText = nsRaw.substring(from: afterStart)
        let target = nsRaw.substring(with: match.range)

        if radiusWords == 0 {
            return target
        }

        let beforeTokens = tokenPattern.matches(
            in: beforeText,
            range: NSRange(location: 0, length: (beforeText as NSString).length)
        )
        let afterTokens = tokenPattern.matches(
            in: afterText,
            range: NSRange(location: 0, length: (afterText as NSString).length)
        )

        var prefix = ""
        var trimmedBefore = beforeText
        let validBefore = beforeTokens.enumerated().compactMap { index, token in
            tokenContainsWordCharacters(token, in: beforeText) ? index : nil
        }
        if validBefore.count > radiusWords {
            let fullTokenIndex = validBefore[validBefore.count - radiusWords]
            let cutStart = beforeTokens[fullTokenIndex].range.location
            trimmedBefore = (beforeText as NSString).substring(from: cutStart)
            prefix = "..."
        }

        var suffix = ""
        var trimmedAfter = afterText
        let validAfter = afterTokens.enumerated().compactMap { index, token in
            tokenContainsWordCharacters(token, in: afterText) ? index : nil
        }
        if validAfter.count > radiusWords {
            let fullTokenIndex = validAfter[radiusWords - 1]
            let cutRange = afterTokens[fullTokenIndex].range
            let cutEnd = cutRange.location + cutRange.length
            trimmedAfter = (afterText as NSString).substring(to: cutEnd)
            suffix = "..."
        }

        return prefix + trimmedBefore + target + trimmedAfter + suffix
    }

    private static func truncateLeadingWords(_ text: String, count: Int) -> String {
        let nsText = text as NSString
        let tokens = tokenPattern.matches(in: text, range: NSRange(location: 0, length: nsText.length))
        let validIndices = tokens.indices.filter { tokenContainsWordCharacters(tokens[$0], in: text) }
        guard validIndices.count > count else { return text }
        let lastTokenIndex = validIndices[count - 1]
        let lastToken = tokens[lastTokenIndex]
        let cutEnd = lastToken.range.location + lastToken.range.length
        return nsText.substring(to: cutEnd) + "..."
    }

    private static func tokenContainsWordCharacters(
        _ token: NSTextCheckingResult,
        in source: String
    ) -> Bool {
        let value = (source as NSString).substring(with: token.range)
        return value.unicodeScalars.contains { CharacterSet.alphanumerics.contains($0) }
    }
}
