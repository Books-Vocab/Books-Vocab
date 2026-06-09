//
//  AppCommandCoordinator.swift
//  Books & Vocab
//
//  App-global menu command intent。Catalyst menu(scene 層)無法 reference per-view
//  coordinator,故恆定動作的 intent flag 集中此處,由 root view 消費。
//  比照 SyncCoordinator / AppToastCoordinator 注入 environment。
//

import SwiftUI

@Observable @MainActor
final class AppCommandCoordinator {
    /// ⌘, 觸發 — root view 觀察並以 sheet 呈現 SettingsView。
    var presentingSettings = false
}

extension View {
    /// 由 ⌘, menu command 驅動的 app-level 設定 sheet(Catalyst-only)。
    /// 與 per-view toolbar gear 設定 sheet 為兩條獨立路徑;SwiftUI 同時只呈現一個 sheet,
    /// 第二個 presentation 於已有 sheet 時被忽略,故無需跨-view 協調。
    @ViewBuilder
    func macSettingsCommandSheet() -> some View {
        #if targetEnvironment(macCatalyst)
        modifier(MacSettingsCommandSheet())
        #else
        self
        #endif
    }
}

#if targetEnvironment(macCatalyst)
private struct MacSettingsCommandSheet: ViewModifier {
    @Environment(\.appCommandCoordinator) private var coordinator

    func body(content: Content) -> some View {
        @Bindable var coordinator = coordinator
        content.settingsSheet(isPresented: $coordinator.presentingSettings)
    }
}
#endif
