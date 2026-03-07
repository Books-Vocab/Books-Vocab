import Foundation
import SwiftUI

struct CardRichTextStyle {
    let font: Font
    let textColor: Color
    let highlightColor: Color
    let italic: Bool
    var underlineHighlights: Bool = true
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
        truncateAroundMarkedWordRadius: Int? = nil
    ) -> Text {
        Text(
            attributedString(
                raw,
                style: style,
                mode: mode,
                truncateAroundMarkedWordRadius: truncateAroundMarkedWordRadius
            )
        )
    }

    static func attributedString(
        _ raw: String,
        style: CardRichTextStyle,
        mode: CardRichTextMode = .highlight,
        truncateAroundMarkedWordRadius: Int? = nil
    ) -> AttributedString {
        let prepared = preparedRaw(
            from: raw,
            mode: mode,
            truncateAroundMarkedWordRadius: truncateAroundMarkedWordRadius
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
        truncateAroundMarkedWordRadius: Int?
    ) -> String {
        let truncated: String
        if let radius = truncateAroundMarkedWordRadius, radius >= 0 {
            truncated = truncateAroundMarkedWord(raw, radiusWords: radius)
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
        part.foregroundColor = style.highlightColor.opacity(0.95)
        if style.underlineHighlights {
            part.underlineStyle = Text.LineStyle(
                pattern: .solid,
                color: style.highlightColor.opacity(0.6)
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
        radiusWords: Int = 5
    ) -> String {
        guard radiusWords >= 0 else { return raw }

        let nsRaw = raw as NSString
        guard
            let match = markedWordPattern.firstMatch(
                in: raw,
                range: NSRange(location: 0, length: nsRaw.length)
            )
        else {
            return raw
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

    private static func tokenContainsWordCharacters(
        _ token: NSTextCheckingResult,
        in source: String
    ) -> Bool {
        let value = (source as NSString).substring(with: token.range)
        return value.unicodeScalars.contains { CharacterSet.alphanumerics.contains($0) }
    }
}
