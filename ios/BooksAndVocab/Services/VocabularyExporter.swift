//
//  VocabularyExporter.swift
//  Books & Vocab
//
//  匯出邏輯 — 純函式型，無狀態、無 UI 依賴
//  將 VocabularyEntry 陣列轉為 CSV / JSON / Anki TSV 並寫入暫存檔
//

import Foundation

enum VocabularyExporter {

    // MARK: - Public API

    /// 匯出為 CSV 格式
    static func exportAsCSV(entries: [VocabularyEntry]) -> URL? {
        // U+FEFF BOM：Excel 對 BOM-less UTF-8 會當 ANSI 讀，中文譯文會亂碼。
        var csv = "\u{FEFF}Word,Translation,Part of Speech,Context,Book,Chapter,Date\n"
        for entry in entries {
            let fields = [
                escapeCSV(entry.word),
                escapeCSV(entry.translation),
                escapeCSV(entry.partOfSpeech ?? ""),
                escapeCSV(entry.context),
                escapeCSV(entry.bookTitle),
                escapeCSV(entry.chapterTitle ?? ""),
                escapeCSV(entry.dateAdded.formatted(.iso8601))
            ]
            csv += fields.joined(separator: ",") + "\n"
        }
        return saveToTemp(content: csv, filename: "vocabulary.csv")
    }

    /// 匯出為 JSON 格式
    static func exportAsJSON(entries: [VocabularyEntry]) -> URL? {
        let items = entries.map { entry -> [String: String] in
            var dict: [String: String] = [
                "word": entry.word,
                "translation": entry.translation,
                "context": entry.context,
                "bookTitle": entry.bookTitle,
                "dateAdded": entry.dateAdded.formatted(.iso8601)
            ]

            if let exp = entry.explanation { dict["explanation"] = exp }
            if let pos = entry.partOfSpeech { dict["partOfSpeech"] = pos }
            if let ch = entry.chapterTitle { dict["chapterTitle"] = ch }
            return dict
        }

        guard
            let data = try? JSONSerialization.data(withJSONObject: items, options: .prettyPrinted),
            let json = String(data: data, encoding: .utf8)
        else { return nil }

        return saveToTemp(content: json, filename: "vocabulary.json")
    }

    /// 匯出為 Anki TSV 格式
    static func exportAsAnki(entries: [VocabularyEntry]) -> URL? {
        var tsv = ""
        for entry in entries {
            let front = "\(escapeHTML(entry.word))\n<small>\(escapeHTML(entry.context))</small>"
            var back = escapeHTML(entry.translation)

            if let pos = entry.partOfSpeech, !pos.isEmpty { back = "(\(escapeHTML(pos))) \(back)" }
            if let exp = entry.explanation { back += "\n\(escapeHTML(exp))" }

            tsv += "\(escapeTab(front))\t\(escapeTab(back))\n"
        }
        return saveToTemp(content: tsv, filename: "vocabulary_anki.tsv")
    }

    // MARK: - Internal Helpers

    private static func saveToTemp(content: String, filename: String) -> URL? {
        let uniqueFilename = "\(UUID().uuidString)-\(filename)"
        let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent(uniqueFilename)
        do {
            try content.write(to: tempURL, atomically: true, encoding: .utf8)
            return tempURL
        } catch {
            return nil
        }
    }

    private static func escapeCSV(_ text: String) -> String {
        // 防試算表公式注入：欄位內容來自不受信任的書籍，開頭為公式觸發字元時
        // 前置 `'` 讓 Excel/Numbers/Sheets 視為純文字（會改動資料，屬已知取捨）。
        let formulaTriggers: Set<Character> = ["=", "+", "-", "@", "\t", "\r", "\n"]
        let safe = text.first.map(formulaTriggers.contains) == true ? "'" + text : text
        let escaped = safe.replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(escaped)\""
    }

    /// Anki 欄位為 HTML；`&` 必須先轉義，否則後續實體會被二次轉義。
    private static func escapeHTML(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func escapeTab(_ text: String) -> String {
        text.replacingOccurrences(of: "\t", with: " ")
            .replacingOccurrences(of: "\n", with: "<br>")
    }
}
