#if os(iOS)
//
//  ReaderTranslationHandler.swift
//  Books & Vocab
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
    var isTranslating = false
    var isSaved = false
    var isExpanded = false
    /// 面板高度態：true = 大卡（撐高到接近全螢幕，頂部留書本可見），false = 小卡。
    /// 與 `isExpanded` 正交：句子 explain 模式預設大卡且不動 isExpanded（避免破壞
    /// explanationOnly 模式判定）；單字模式則由 `handleExpand` 連動（展開語境解釋＝放大）。
    var isPanelLarge = false
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

    /// 最近一次成功啟動的翻譯 / 解釋 lookup metadata，用於失敗後 retry。
    /// `kind` 區分使用者觸發的是 quick-translate（word）/ phrase / explain，
    /// 以便 retry 時呼叫對應流程而不弄錯模式。
    /// 刻意**不**標 `@ObservationIgnored`：三個 view body（ReaderView+Panels /
    /// PDFReaderView / PodcastPlayerScene）拿它當 retry 按鈕的顯示條件，
    /// 投影給 view 的狀態必須在 observation 圖上。
    var lastLookup: LastLookup?

    enum LookupKind {
        case word
        case phrase
        case explain
    }

    struct LastLookup {
        let kind: LookupKind
        let text: String
        let context: String
    }

    enum StatusChannel {
        case translation
        case explanation
    }

    init(
        translationService: any Translating = TranslationService(),
        authManager: any AuthManaging = MainActor.assumeIsolated({ AuthManager.shared })
    ) {
        self.translationService = translationService
        self.authManager = authManager
    }

    func cancelCurrentTranslationTask() {
        currentTranslationTask?.cancel()
        currentTranslationTask = nil
    }

    func replaceCurrentTranslationTask(with task: Task<Void, Never>) {
        cancelCurrentTranslationTask()
        currentTranslationTask = task
    }

    func runLookupTask<Output>(
        statusChannel: StatusChannel,
        operation: @escaping @MainActor (_ onRetry: @escaping @Sendable (Int, Int) async -> Void) async throws -> Output,
        onSuccess: @escaping @MainActor (Output) async -> Void,
        onFailure: @escaping @MainActor (Error) -> Void
    ) {
        let task = Task { @MainActor in
            guard !Task.isCancelled else { return }

            do {
                let onRetry: @Sendable (Int, Int) async -> Void = { [weak self] attempt, total in
                    guard let self else { return }
                    await MainActor.run {
                        guard !Task.isCancelled else { return }
                        let message = L10n.format(
                            "正在重試 (%@/%@)...",
                            "\(attempt)",
                            "\(total)"
                        )
                        switch statusChannel {
                        case .translation:
                            self.translationStatus = message
                        case .explanation:
                            self.explanationStatus = message
                        }
                    }
                }

                let output = try await operation(onRetry)
                guard !Task.isCancelled else { return }
                await onSuccess(output)
            } catch {
                guard !(error is CancellationError), !Task.isCancelled else { return }
                onFailure(error)
            }
        }
        replaceCurrentTranslationTask(with: task)
    }
}
#endif
