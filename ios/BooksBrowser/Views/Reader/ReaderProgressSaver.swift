#if os(iOS)
import Foundation
import ReadiumShared

/// EPUB 閱讀進度落盤器。
///
/// 背景：`ReaderView.handleLocationChange` 每次翻頁都更新 `Book` 的
/// `lastReadLocatorJSON` / `dateLastRead` / `progression`，但**從不** `save()`，
/// 仰賴 SwiftData 非確定性 autosave。crash / OOM 被殺前未 flush 則最後位置遺失，
/// 且與 PDF 路徑（`PDFReaderView` 每次 `pageDidChange` 顯式 `safeSave()`）行為不一致。
///
/// 修法：在記憶體寫入後**顯式** `save()`，但翻頁高頻 → 用 debounce 把連續翻頁
/// coalesce 成窗口尾端單次落盤，避免每頁同步 I/O 卡頓。退出 / 退背景時 `flush()`
/// 兜底，確保 debounce 窗口內未落盤的最後一次寫入不遺失。
///
/// 並發契約：mirror `CloudPreferencesSync` — 所有公開 API 設計為 main thread 呼叫
/// （`onLocationChange` / `onDisappear` / scenePhase observer 皆 main queue），
/// pending flush 的排程/取消固定走 main queue，避免 `DispatchWorkItem` cancel/
/// reschedule 競態。
@MainActor
final class ReaderProgressSaver {
    /// debounce 視窗：連續翻頁在此窗口內 coalesce 成單次落盤。
    private let flushDelay: TimeInterval
    /// pending 的 debounced flush task；nil 表示無待執行。MainActor 隔離下排程/取消，
    /// 無 `DispatchWorkItem` 跨 isolation 競態（mirror `GlobalDebouncer` 的 Task/sleep）。
    private var pendingFlush: Task<Void, Never>?
    /// 最近一次排程時帶入的落盤副作用（最新 save closure），供 `flush()` 直接執行。
    private var latestSave: (() -> Void)?

    /// 預設生產窗口 1.2s — 翻頁停止後才落盤。
    init(flushDelay: TimeInterval = ReaderMetrics.progressFlushDelay) {
        self.flushDelay = flushDelay
    }

    /// 將 `locator` 序列化為 Readium Locator JSON。
    ///
    /// 失敗回 `nil`（呼叫端據此**跳過寫入**，保留既有有效值），而非舊行為的 `"{}"`
    /// 字面值 —— `Locator(jsonString:"{}")` 可能 decode 成空 locator 污染下次還原。
    static func encodedLocatorJSON(_ locator: Locator) -> String? {
        do {
            return try locator.jsonString()
        } catch {
            // Serialization of a structured Readium Locator effectively never
            // fails — but if it does, surface it instead of silently returning
            // nil, so the skipped-persist path (ReaderView+Handlers) is diagnosable.
            AppLog.reader.warning("Locator JSON serialize failed (href=\(String(describing: locator.href), privacy: .public)): \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    /// 記錄一次翻頁：`apply` 立即執行（in-memory model 寫入，供 panel 即時讀取），
    /// 隨後排一個 debounced `save`。`save` 為最新值，窗口內多次 record 只保留尾端。
    func recordChange(apply: () -> Void, save: @escaping () -> Void) {
        apply()
        latestSave = save
        scheduleFlush()
    }

    /// 立即落盤並取消任何 pending flush。
    /// 供 `onDisappear` / scenePhase `.background` 兜底，確保 debounce 窗口未到期
    /// 即退出時最後一次寫入仍落地。無 pending 則 no-op。
    func flush() {
        guard let save = latestSave else { return }
        pendingFlush?.cancel()
        pendingFlush = nil
        latestSave = nil
        save()
    }

    // MARK: - Debounce

    private func scheduleFlush() {
        pendingFlush?.cancel()
        pendingFlush = Task { [weak self, flushDelay] in
            try? await Task.sleep(for: .seconds(flushDelay))
            guard !Task.isCancelled, let self else { return }
            self.pendingFlush = nil
            let save = self.latestSave
            self.latestSave = nil
            save?()
        }
    }
}
#endif
