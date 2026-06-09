//
//  MacWindowChrome.swift
//  Books & Vocab
//
//  Mac Catalyst 視窗 chrome 單一來源 — 尺寸 + title bar。
//  非 Catalyst 平台全為 no-op(modifier 直接回傳 self)。
//

import SwiftUI

enum MacWindowChrome {
    /// 最小視窗尺寸 — 須容納 regular split(sidebar + 720 內容)。
    static let minimumSize = CGSize(width: 900, height: 640)
    /// 首發視窗尺寸 — 僅冷啟動套用一次,之後尊重使用者調整。
    static let defaultSize = CGSize(width: 1100, height: 760)

    #if targetEnvironment(macCatalyst)
    /// 已套用首發 geometry 的旗標 — requestGeometryUpdate 只在冷啟動一次,
    /// 否則每次 onAppear 都會把使用者調過的視窗重設回 defaultSize。
    private static var didApplyInitialGeometry = false

    @MainActor
    private static var currentWindowScene: UIWindowScene? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first
    }

    @MainActor
    static func applyDefaults() {
        guard let scene = currentWindowScene else { return }
        // 最小尺寸每次套用安全(冪等)。
        scene.sizeRestrictions?.minimumSize = minimumSize
        // 首發尺寸只一次。
        guard !didApplyInitialGeometry else { return }
        didApplyInitialGeometry = true
        // origin 置中 best-effort — Mac systemFrame 是 AppKit 全域座標,系統常自行
        // 置中/忽略 origin;算置中值避免落在螢幕角落,實機若仍偏移再校。
        let screen = scene.screen.bounds.size
        let origin = CGPoint(
            x: max(0, (screen.width - defaultSize.width) / 2),
            y: max(0, (screen.height - defaultSize.height) / 2)
        )
        let geometry = UIWindowScene.GeometryPreferences.Mac(
            systemFrame: CGRect(origin: origin, size: defaultSize)
        )
        scene.requestGeometryUpdate(geometry)
    }

    /// Reader 沉浸:隱藏/復原 title bar。Reader 與其他 tab 共用同一 window,
    /// 故只能 per-presentation scoped 切換,不可在 App 啟動時設死。
    @MainActor
    static func setTitlebarHidden(_ hidden: Bool) {
        guard let titlebar = currentWindowScene?.titlebar else { return }
        titlebar.titleVisibility = hidden ? .hidden : .visible
        // 不碰 titlebar.toolbar — KG 從不設 mac toolbar;若 Workstream C 未來
        // 掛 toolbar,此處清空會在 Reader 進出時誤傷,故不動。
    }
    #endif
}

extension View {
    /// 套用 Mac 視窗預設尺寸 + 最小尺寸。非 Catalyst 為 no-op。
    @ViewBuilder
    func macWindowChrome() -> some View {
        #if targetEnvironment(macCatalyst)
        self.onAppear { MacWindowChrome.applyDefaults() }
        #else
        self
        #endif
    }

    /// Reader 沉浸:進入隱藏 title bar、離開復原。非 Catalyst 為 no-op。
    @ViewBuilder
    func macReaderImmersion() -> some View {
        #if targetEnvironment(macCatalyst)
        self
            .onAppear { MacWindowChrome.setTitlebarHidden(true) }
            .onDisappear { MacWindowChrome.setTitlebarHidden(false) }
        #else
        self
        #endif
    }
}
