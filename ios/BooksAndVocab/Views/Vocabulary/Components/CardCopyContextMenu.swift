//
//  CardCopyContextMenu.swift
//  Books & Vocab
//
//  卡片區塊「長按 → 複製」的共用互動。Example / Meaning / Source 三個
//  CardDocument*Block 原本各自重複「@State copyTrigger + contextMenu 複製按鈕 +
//  success toast + .sensoryFeedback」一整組;收斂成單一 modifier,複製文字以參數傳入。
//  (Hero 的 copyTrigger 另兼 speak-bounce、Collocations 的選單結構不同,皆不套用。)
//

import SwiftUI

private struct CardCopyContextMenu: ViewModifier {
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let text: String

    func body(content: Content) -> some View {
        content
            .contextMenu {
                Button("複製".localized, systemImage: "doc.on.doc") {
                    PlatformClipboard.copy(text)
                    copyTrigger.toggle()
                    toastCoordinator.success("已複製".localized)
                }
            }
            .appFeedback(.success, trigger: copyTrigger)
    }
}

extension View {
    /// 套用卡片區塊統一的「長按複製」contextMenu + 成功 toast + 觸覺回饋。
    func cardCopyContextMenu(_ text: String) -> some View {
        modifier(CardCopyContextMenu(text: text))
    }
}
