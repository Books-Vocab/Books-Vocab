//
//  ListSectionCard.swift
//  Books & Vocab
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
        let shape = AppRoundedRect(roundness: AppRoundness.card)
        VStack(spacing: 0) { content }
            .padding(.vertical, skin.spacing.microGap)
            .background(shape.fill(skin.palette.cardBackground))
            // clip 內容至圓角：caller 的 per-row 選中底色（方角矩形）在首/末列才不會
            // 溢出卡片圓角。stroke overlay 疊在 clip 之上，不受影響。
            .clipShape(shape)
            .overlay(shape.stroke(skin.palette.cardBorder, lineWidth: 0.5))
    }
}

#Preview("ListSectionCard") {
    AppThemeContainer {
        ListSectionCardPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct ListSectionCardPreview: View {
    @Environment(\.appSkin) private var skin

    var body: some View {
        ListSectionCard {
            ForEach(0..<3) { index in
                if index > 0 {
                    Rectangle()
                        .fill(skin.palette.divider)
                        .frame(height: AppMetrics.dividerStandard)
                }
                Text("項目 \(index + 1)")
                    .font(skin.typography.body)
                    .foregroundStyle(skin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, AppSpacing.s4)
                    .padding(.vertical, AppSpacing.s3)
            }
        }
        .padding()
        .background(skin.palette.pageBackground.ignoresSafeArea())
    }
}
