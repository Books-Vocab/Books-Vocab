//
//  NotebookHeaderPillLabel.swift
//  BooksBrowser
//
//  統一的 Header pill 視覺規格 — 給 NotebookListView Today Review action bar
//  三 pill（CTA / filter / plus）共用,確保高度與 padding 完全一致,僅差別在「填色 + 長度」。
//  不含 Button — caller 自行用 Button / Menu 包裹,讓 Menu label 場景也能套用。
//  形狀：Capsule;高度 ≈ 27pt (約原 22pt × 1.2)。

import SwiftUI

struct NotebookHeaderPillLabel<Content: View>: View {
    let fillColor: Color
    let foregroundColor: Color
    @ViewBuilder let content: Content

    var body: some View {
        content
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, AppSpacing.s2 + 2)   // 10pt
            .padding(.vertical, 7)
            .frame(minWidth: 32)
            .background(Capsule(style: .continuous).fill(fillColor))
    }
}
