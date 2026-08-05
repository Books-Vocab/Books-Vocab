//
//  AppSidebarRow.swift
//  Books & Vocab
//
//  Catalyst 側邊欄列 — 整列可點、走 app 設計語言,取代系統 .listStyle(.sidebar) 預設樣式
//  (系統半透明材質 + 系統藍選取色與 app Notion 風割裂)。
//  選取 / 未選靠灰階配色 + 背景填充區分;selection 由呼叫端自管 @State,不用 List(selection:)
//  (後者會讓 .listStyle(.sidebar) 自繪系統 selection chrome,與此處自繪背景雙重高亮)。
//

import SwiftUI

struct AppSidebarRow: View {
    @Environment(\.appSkin) private var appSkin

    let systemImage: String
    let title: String
    let isSelected: Bool
    let action: () -> Void

    // hover tint 與 selection 背景共用同一圓度,避免疊起時雙圓角錯位。
    private let roundness = AppRoundness.control

    var body: some View {
        Button(action: action) {
            HStack(spacing: appSkin.spacing.controlGap) {
                Image(systemName: systemImage)
                    .font(appSkin.typography.iconMedium)
                    .foregroundStyle(rowForeground)
                    .frame(width: 22, alignment: .center)
                    // 裝飾性 icon — 交給 .accessibilityLabel 朗讀,避免 VoiceOver 冗讀 symbol 名。
                    .accessibilityHidden(true)

                Text(title)
                    .font(appSkin.typography.body)
                    .foregroundStyle(rowForeground)

                Spacer(minLength: 0)
            }
            .padding(.horizontal, appSkin.spacing.controlHorizontalPadding)
            .padding(.vertical, appSkin.spacing.controlVerticalPadding)
            // 整列 hit-test:Spacer 撐滿 row 寬,contentShape 把撐開後的整個矩形納入點擊區。
            .contentShape(Rectangle())
            .background(
                AppRoundedRect(roundness: roundness)
                    .fill(appSkin.palette.primaryText.opacity(isSelected ? 0.08 : 0))
            )
            .appHoverRowTint(roundness: roundness)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    // 自訂字體(ElmsSans)不響應 .fontWeight,故選取狀態以配色而非字重表達。
    private var rowForeground: Color {
        isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText
    }
}

#Preview("AppSidebarRow") {
    AppThemeContainer {
        AppSidebarRowPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppSidebarRowPreview: View {
    @Environment(\.appSkin) private var appSkin
    @State private var selected = "book"

    var body: some View {
        VStack(spacing: 0) {
            AppSidebarRow(systemImage: "book", title: "書架", isSelected: selected == "book") {
                selected = "book"
            }
            AppSidebarRow(systemImage: "list.bullet.rectangle", title: "詞庫", isSelected: selected == "vocab") {
                selected = "vocab"
            }
            AppSidebarRow(systemImage: "gearshape", title: "設定", isSelected: selected == "settings") {
                selected = "settings"
            }
        }
        .padding(AppSpacing.s3)
        .frame(width: 260)
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}
