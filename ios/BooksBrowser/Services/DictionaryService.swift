//
//  DictionaryService.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/25.
//

import Foundation
import os

/// 免費字典 API — 取得 IPA 音標（不消耗 LLM token）
struct DictionaryService {

    /// 取得單字的 IPA 音標
    static func fetchPronunciation(word: String) async -> String? {
        // 只處理單字，不處理片語
        let trimmed = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.contains(" ") else { return nil }

        guard let url = URL(string: "https://api.dictionaryapi.dev/api/v2/entries/en/\(trimmed.lowercased())") else {
            return nil
        }

        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                return nil
            }

            guard let entries = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]],
                  let first = entries.first else {
                return nil
            }

            // 優先取 phonetics 陣列中有 text 的項目
            if let phonetics = first["phonetics"] as? [[String: Any]] {
                for phonetic in phonetics {
                    if let text = phonetic["text"] as? String, !text.isEmpty {
                        return text
                    }
                }
            }

            // fallback: 頂層 phonetic 欄位
            if let phonetic = first["phonetic"] as? String, !phonetic.isEmpty {
                return phonetic
            }

            return nil
        } catch {
            AppLog.dictionary.warning("Dictionary API error: \(error.localizedDescription)")
            return nil
        }
    }
}
