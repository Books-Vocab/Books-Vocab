//
//  GraphWebView+JSEscape.swift
//  Books & Vocab
//
//  Graph WKWebView 注入 JSON 至單引號 JS 字串字面值前的跳脫。
//  集中為單一定義，避免各 Coordinator 各寫一份導致跳脫順序 drift（injection-safety）。
//

import Foundation

extension String {
    /// 跳脫後可安全嵌入單引號 JS 字串字面值（`'...'`）。
    /// 順序必須先跳脫反斜線、再跳脫單引號。
    var jsSingleQuoteEscaped: String {
        replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
    }
}
