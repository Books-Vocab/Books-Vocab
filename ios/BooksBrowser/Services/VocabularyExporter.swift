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
        var csv = "Word,Translation,Part of Speech,Context,Book,Chapter,Date\n"
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
            let front = "\(entry.word)\n<small>\(entry.context)</small>"
            var back = entry.translation

            if let pos = entry.partOfSpeech, !pos.isEmpty { back = "(\(pos)) \(back)" }
            if let exp = entry.explanation { back += "\n\(exp)" }

            tsv += "\(escapeTab(front))\t\(escapeTab(back))\n"
        }
        return saveToTemp(content: tsv, filename: "vocabulary_anki.tsv")
    }

    // MARK: - Internal Helpers

    private static func saveToTemp(content: String, filename: String) -> URL? {
        let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        do {
            try content.write(to: tempURL, atomically: true, encoding: .utf8)
            return tempURL
        } catch {
            return nil
        }
    }

    private static func escapeCSV(_ text: String) -> String {
        let escaped = text.replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(escaped)\""
    }

    private static func escapeTab(_ text: String) -> String {
        text.replacingOccurrences(of: "\t", with: " ")
            .replacingOccurrences(of: "\n", with: "<br>")
    }
}
