//
//  CatalystAppDelegate.swift
//  Books & Vocab
//
//  Catalyst 選單客製 — 整檔 Catalyst-only。
//

#if targetEnvironment(macCatalyst)
import UIKit

/// 移除 UIKit 在 Catalyst 自動注入的系統 Find 選單（Edit ▸ Find，⌘F → `find:`／「尋找⋯」）。
///
/// Why：此 app 無 find-in-text 功能，該系統 ⌘F 是死綁定；它與 `MacMenuCommands` 的
/// 「搜尋單字」⌘F（`_performMainMenuShortcutKeyCommand:`）同鍵衝突，每次 menu builder
/// 重建就拋一次 `_UIMenuBuilderError`（log 洗版），且系統 `find:` 會壓過自訂 ⌘F →
/// 主詞庫列表 ⌘F undefined behavior。
///
/// 移除後「搜尋單字」成為唯一 ⌘F。SwiftUI `.commands` 無法觸及系統 `.find` placement，
/// 故走 UIResponder.buildMenu —— Catalyst 客製選單的 documented 入口。
final class CatalystAppDelegate: UIResponder, UIApplicationDelegate {
    override func buildMenu(with builder: UIMenuBuilder) {
        super.buildMenu(with: builder)
        guard builder.system == .main else { return }
        builder.remove(menu: .find)
    }
}
#endif
