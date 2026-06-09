//
//  CardSections.swift
//  Books & Vocab
//
//  共用卡片 Section 元件 — 渲染與業務邏輯完全分離
//  每個元件只接收「展示用資料」，無 @Query / @State / 副作用
//

import SwiftUI
import Inject

// MARK: - CardSectionDivider

/// 卡片內部的水平分隔線（統一外觀，取代散落在各 View 的重複定義）
struct CardSectionDivider: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    var horizontalPadding: CGFloat = AppSkin.baseMetrics.cardDividerHorizontalPadding

    var body: some View {
        Rectangle()
            .fill(appSkin.palette.divider)
            .frame(height: AppMetrics.dividerThin)
            .padding(.horizontal, horizontalPadding)
            .enableInjection()
    }
}

// MARK: - CardSectionLabel

/// Section 標題標籤（icon + 小字）
struct CardSectionLabel: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    let systemImage: String

    var body: some View {
        Label {
            Text(title)
                .font(appSkin.typography.caption)
        } icon: {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconTiny)
        }
        .foregroundStyle(appSkin.palette.tertiaryText)
        .enableInjection()
    }
}

// MARK: - CardFormsSection

/// 單字變化形列表
struct CardFormsSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var copyTrigger = false
    let forms: [String]
    let rootForm: String?
    let colorScheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: CardSectionsCopy.formsTitle, systemImage: "text.badge.plus")

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                    ForEach(Array(forms.enumerated()), id: \.offset) { _, form in
                        let isRoot = form == rootForm
                        Text(form)
                            .font(isRoot ? appSkin.typography.monoBodyStrong : appSkin.typography.monoBody)
                            .foregroundStyle(isRoot ? appSkin.palette.accent : appSkin.palette.secondaryText)
                    }
                }
            }
        }
        .contextMenu {
            Button(CardSectionsCopy.copyTitle, systemImage: "doc.on.doc") {
                PlatformClipboard.copy(forms.joined(separator: ", "))
                copyTrigger.toggle()
                toastCoordinator.success(CardSectionsCopy.copiedTitle)
            }
        }
        .sensoryFeedback(.success, trigger: copyTrigger)
        .enableInjection()
    }
}
