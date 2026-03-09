//
//  BooksBrowserAppIntents.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/26.
//

import Foundation
import AppIntents
import SwiftData

/// 提供給 iOS 26 系統 (Siri / Visual Intelligence) 的意圖：加入生字庫
struct AddVocabularyIntent: AppIntent {
    static let title: LocalizedStringResource = "加入 BooksBrowser 生字庫"
    static let description: IntentDescription = IntentDescription("將選取的單字或片語直接加入 BooksBrowser 進行離線學習與翻譯。")

    // 參數：Siri 會詢問或由 Visual Intelligence 框選帶入
    @Parameter(title: "單字或片語")
    var word: String

    @Parameter(title: "上下文 (選填)")
    var context: String?

    // 意圖的核心執行邏輯
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // 1. 取得 SwiftData Context (在實際 App 中需確保可從背景正確初始化 ModelContainer)
        // 為了簡化展示，這裡直接使用預設配置
        let container = try ModelContainer(for: VocabularyEntry.self)
        let modelContext = ModelContext(container)
        
        let targetWord = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !targetWord.isEmpty else {
            return .result(dialog: IntentDialog(stringLiteral: L10n.string("請提供要加入的單字。")))
        }

        // 2. 檢查是否已存在
        let descriptor = FetchDescriptor<VocabularyEntry>(predicate: #Predicate { $0.word == targetWord })
        if let existing = try? modelContext.fetch(descriptor).first {
            if existing.syncAction == .delete {
                existing.restorePendingEntry()
                try? modelContext.save()
                return .result(dialog: IntentDialog(stringLiteral: L10n.format("已為您恢復追蹤單字「%@」。", targetWord)))
            } else {
                return .result(dialog: IntentDialog(stringLiteral: L10n.format("單字「%@」已經在您的生字庫中了。", targetWord)))
            }
        }

        // 3. 建立新單字，標記為待同步
        let entry = VocabularyEntry(
            word: targetWord,
            translation: "",       // 稍後由背景 Task 補上
            context: context ?? "",
            bookTitle: "加入自系統外"
        )
        entry.restorePendingEntry()
        modelContext.insert(entry)
        try? modelContext.save()
        
        // 4. (可選) 觸發背景非同步翻譯（使用我們剛升級的端側 Foundation Models）
        Task.detached {
            let service = TranslationService()
            if let result = try? await service.translateQuick(word: targetWord, context: context ?? "") {
                entry.translation = result.translation
                entry.partOfSpeech = result.partOfSpeech
                // 在實際架構中，還需儲存回 modelContext
            }
        }

        return .result(dialog: IntentDialog(stringLiteral: L10n.format("已成功將「%@」加入 BooksBrowser 生字庫。", targetWord)))
    }
}
