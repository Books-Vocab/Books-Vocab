import SwiftUI
import Testing
@testable import BooksAndVocab

/// Pins the Settings view-tree stack budget（2026-06-11 真機 stack overflow 案）。
///
/// iOS 真機 main thread stack 只有 1MB；Debug -Onone 下 SwiftUI 未特化泛型
/// （`VStack.init` / `ScrollView.init` 等）以 content **型別尺寸**做動態 stack
/// alloca，且中間值會被複製多次。把 section 樹 inline 進 `SettingsPresenter.body`
/// 曾把單次求值撐到 ~945KB → EXC_BAD_ACCESS code=2（取證 dump
/// 20260611_164831）。Simulator main thread 是 8MB，永遠重現不了。
///
/// 防線：body 的 opaque 型別尺寸。section 拆成獨立 View struct 後的實測基線
/// （2026-06-11）：SettingsPresenter.Body=14,769B（4 個 navigationDestination
/// 會把 destination 子樹內嵌進型別，是大頭）、SettingsOtherSection.Body=8,729B、
/// SettingsDebugBackendSection.Body=10,049B。若未來有人把 section 收回
/// computed property inline 展開，presenter 型別會以 section 子樹整棵內嵌的
/// 方式暴漲（re-inline otherSection ≈ +8.6KB），先在這裡爆，不必等真機 crash。
/// 門檻被合法改動撞到時：確認新增的是獨立 struct 子樹而非 inline 展開，
/// 才准連同本註解一起上調。
@MainActor
struct SettingsStackBudgetTests {

    /// presenter 20KB：基線 14.8KB 的合理餘裕，但 re-inline 任一 section
    /// （≥ +8.6KB）必定超標。
    private static let presenterBodyBudget = 20 * 1024
    /// section 16KB：基線 8.7KB / 10KB。
    private static let sectionBodyBudget = 16 * 1024

    @Test func settingsPresenterBodyTypeStaysWithinStackBudget() {
        let size = MemoryLayout<SettingsPresenter.Body>.size
        #expect(size < Self.presenterBodyBudget, "SettingsPresenter.Body size=\(size)B — section 不得 inline 回 body")
    }

    @Test func settingsOtherSectionBodyTypeStaysWithinStackBudget() {
        let size = MemoryLayout<SettingsOtherSection.Body>.size
        #expect(size < Self.sectionBodyBudget, "SettingsOtherSection.Body size=\(size)B")
    }

    @Test func settingsDebugBackendSectionBodyTypeStaysWithinStackBudget() {
        let size = MemoryLayout<SettingsDebugBackendSection.Body>.size
        #expect(size < Self.sectionBodyBudget, "SettingsDebugBackendSection.Body size=\(size)B")
    }
}
