//
//  ListSectionCard.swift
//  BooksBrowser
//
//  扁平列表的共用卡片容器（VStack(spacing:0) + cardBackground fill + cardBorder
//  stroke）。podcast 集數列表與單字列表共同骨架。divider 由 caller 在 ForEach
//  內插（兩處現況一致），不塞進容器以免改變語意。
//

import SwiftUI

struct ListSectionCard<Content: View>: View {
    @Environment(\.appSkin) private var skin
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) { content }
            .padding(.vertical, skin.spacing.microGap)
            .background(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .fill(skin.palette.cardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .stroke(skin.palette.cardBorder, lineWidth: 0.5)
            )
    }
}
