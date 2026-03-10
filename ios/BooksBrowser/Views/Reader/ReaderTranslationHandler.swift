//
//  ReaderTranslationHandler.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/3/1.
//

import SwiftUI

/// 封裝閱讀器全部翻譯狀態與詞庫邏輯，由 ReaderView 持有並橋接
@MainActor
@Observable
final class ReaderTranslationHandler {

    // MARK: - 翻譯狀態
    var wordSelection: WordSelection?
    var translationResult: TranslationResult?
    var pronunciation: String?
    var isTranslating = false
    var isSaved = false
    var isExpanded = false
    var explanationText: String?
    var isLoadingExplanation = false
    var translationStatus: String?
    var explanationStatus: String?
    var translationErrorMessage: String?
    var explanationErrorMessage: String?

    // MARK: - 底線觸發信號
    var lookedUpWords: [String] = []
    var bookUniqueWords: Set<String>? = nil
    var clearHighlightTrigger = UUID()
    var removeWordTrigger: (word: String, id: UUID)? = nil

    // MARK: - 計算屬性
    var statusMessage: String? { translationStatus ?? explanationStatus }
    var isExplanationOnly: Bool { wordSelection != nil && translationResult == nil && isExpanded }

    // MARK: - 私有服務（protocol 類型，方便測試時注入 mock）
    @ObservationIgnored
    let translationService: any Translating
    @ObservationIgnored
    let authManager: any AuthManaging

    // 取消前一次未完成的翻譯 task（快速連點防覆蓋）
    @ObservationIgnored
    var currentTranslationTask: Task<Void, Never>?

    init(
        translationService: any Translating = TranslationService(),
        authManager: any AuthManaging = AuthManager.shared
    ) {
        self.translationService = translationService
        self.authManager = authManager
    }
}
