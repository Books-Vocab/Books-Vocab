import Foundation
import SwiftUI

struct CardRichTextStyle {
    let font: Font
    let textColor: Color
    let highlightColor: Color
    let italic: Bool
    var underlineHighlights: Bool = false
    var useBackgroundMark: Bool = true
    var highlightWeight: Font.Weight = .semibold
    var backgroundOpacity: Double = VocabSkin.HighlightConfig.default.backgroundOpacity
    var underlineOpacity: Double = VocabSkin.HighlightConfig.default.underlineOpacity
}

enum CardRichTextMode {
    case highlight
    case cloze
}

enum CardRichTextRenderer {
    private static func regex(_ pattern: String) -> NSRegularExpression {
        do {
            return try NSRegularExpression(pattern: pattern)
        } catch {
            preconditionFailure("Invalid regex pattern: \(pattern)")
        }
    }

    private static let inlinePattern = regex("\\*\\*(.+?)\\*\\*|`([^`]+)`")
    private static let markedWordPattern = regex("\\*\\*.+?\\*\\*")
    /// 移除所有 **word** 標記，只留詞本身（用於截斷前的清理）
    private static let stripMarkPattern = regex("\\*\\*(.+?)\\*\\*")
    private static let tokenPattern = regex("\\S+")

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

    // MARK: - Truncation Cache
    //
    // 避免每次 SwiftUI body 求值都重跑 regex 截斷。
    // 同一 (markdown, radius, targetWord) 組合的結果不變，可安全快取。
    // 使用 NSCache 取得 thread-safe 行為（SwiftUI 雖通常在 main 求值，
    // 但 AttributedString 也可能在背景組裝；NSCache 內建鎖避免 race）。

    private static let truncationCache: NSCache<NSString, NSString> = {
        let cache = NSCache<NSString, NSString>()
        cache.countLimit = 256
        return cache
    }()

    static func clearTruncationCache() {
        truncationCache.removeAllObjects()
    }

    private static func cachedTruncate(_ raw: String, radius: Int, targetWord: String?) -> String {
        // 組合單一 NSString key：用 \u{1F} (Unit Separator) 當分隔符，避免 raw 內容衝突
        let keyString = "\(raw)\u{1F}\(radius)\u{1F}\(targetWord ?? "")" as NSString
        if let cached = truncationCache.object(forKey: keyString) {
            return cached as String
        }
        let result = truncateAroundMarkedWord(raw, radiusWords: radius, targetWordFallback: targetWord)
        truncationCache.setObject(result as NSString, forKey: keyString)
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
            truncated = cachedTruncate(raw, radius: radius, targetWord: targetWord)
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
            part.backgroundColor = style.highlightColor.opacity(style.backgroundOpacity)
        }

        if style.underlineHighlights {
            part.underlineStyle = Text.LineStyle(
                pattern: .solid,
                color: style.highlightColor.opacity(style.underlineOpacity)
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

        // 當有 targetWord 時：先 strip 所有現有 ** 標記，再以 targetWord 為中心截斷。
        // 這樣可避免「例句裡有其他詞被標記但 targetWord 沒被標記」時截到錯誤的上下文。
        if let fallback = targetWordFallback, !fallback.isEmpty {
            let nsRaw = raw as NSString
            let stripped = stripMarkPattern.stringByReplacingMatches(
                in: raw,
                range: NSRange(location: 0, length: nsRaw.length),
                withTemplate: "$1"
            )
            let nsStripped = stripped as NSString
            let esc = NSRegularExpression.escapedPattern(for: fallback)
            let pattern = "(?<![\\w\\p{L}])\(esc)(?![\\w\\p{L}])"
            if let wordRegex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive),
               let wordMatch = wordRegex.firstMatch(in: stripped, range: NSRange(location: 0, length: nsStripped.length)) {
                let actualWord = nsStripped.substring(with: wordMatch.range)
                let marked = nsStripped.substring(to: wordMatch.range.location)
                    + "**\(actualWord)**"
                    + nsStripped.substring(from: wordMatch.range.location + wordMatch.range.length)
                // 以唯一的 **targetWord** 為中心截斷（不傳 targetWordFallback 避免遞迴）
                return truncateAroundMarkedWord(marked, radiusWords: radiusWords)
            }
            // Stem fallback: 取前 4-6 字元做 prefix match（處理屈折變化）
            let firstWord = fallback.components(separatedBy: " ").first ?? fallback
            if firstWord.count >= 4 {
                let stemLen = min(firstWord.count, 6)
                let stem = String(firstWord.prefix(stemLen))
                let stemEsc = NSRegularExpression.escapedPattern(for: stem)
                let stemPat = "(?<![\\w\\p{L}])\(stemEsc)\\w*(?![\\w\\p{L}])"
                if let stemRegex = try? NSRegularExpression(pattern: stemPat, options: .caseInsensitive),
                   let stemMatch = stemRegex.firstMatch(in: stripped, range: NSRange(location: 0, length: nsStripped.length)) {
                    let actualWord = nsStripped.substring(with: stemMatch.range)
                    let marked = nsStripped.substring(to: stemMatch.range.location)
                        + "**\(actualWord)**"
                        + nsStripped.substring(from: stemMatch.range.location + stemMatch.range.length)
                    return truncateAroundMarkedWord(marked, radiusWords: radiusWords)
                }
            }
            // targetWord 不在例句中：顯示前 (2*radius+1) 個詞（stripped 版本，無雜訊標記）
            return truncateLeadingWords(stripped, count: 2 * radiusWords + 1)
        }

        let nsRaw = raw as NSString
        guard
            let match = markedWordPattern.firstMatch(
                in: raw,
                range: NSRange(location: 0, length: nsRaw.length)
            )
        else {
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
            // Strip leading punctuation/whitespace after truncation
            let punctuationAndWhitespace = CharacterSet.punctuationCharacters.union(.whitespaces)
            trimmedBefore = String(trimmedBefore.drop(while: { char in
                char.unicodeScalars.allSatisfy { punctuationAndWhitespace.contains($0) }
            }))
            prefix = "…"
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
