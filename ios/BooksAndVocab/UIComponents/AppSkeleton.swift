//
//  AppSkeleton.swift
//  Books & Vocab
//
//  Loading state skeleton primitives — 取代裸 `ProgressView()`，
//  讓 list / card / row 在資料載入時有結構化骨架而非空白旋轉。
//
//  變體：
//    - AppSkeletonLine — 單行 line / label 骨架
//    - AppSkeletonCard — 卡片區塊骨架（標題+多行內文）
//
//  動畫採 opacity pulse（pulsing 0.08 ↔ 0.18），低耗能、無漸層遮罩，
//  避免在 long-lived view 持續消耗 GPU。caller 應於 .onAppear 觸發、
//  view disappear 時 SwiftUI 自動停止。
//

import SwiftUI

struct AppSkeletonLine: View {
    @Environment(\.appTheme) private var appTheme
    @State private var pulse = false

    var width: CGFloat?
    var height: CGFloat = 12

    init(width: CGFloat? = nil, height: CGFloat = 12) {
        self.width = width
        self.height = height
    }

    var body: some View {
        // 用 primaryText.opacity 直接給顯式 alpha：
        // - light mode primaryText 偏黑，0.06-0.14 在白底清楚可見
        // - dark mode primaryText 偏白，0.06-0.14 在暗底清楚可見
        // 在兩 mode 自動 invert 對比，pulse 振幅一致。
        RoundedRectangle(cornerRadius: AppRadius.xs, style: .continuous)
            .fill(appTheme.palette.primaryText.opacity(pulse ? 0.14 : 0.06))
            .frame(width: width, height: height)
            .frame(maxWidth: width == nil ? .infinity : nil, alignment: .leading)
            .animation(AppMotion.subtleBreath, value: pulse)
            .onAppear { pulse = true }
    }
}

struct AppSkeletonCard: View {
    @Environment(\.appTheme) private var appTheme

    var titleWidth: CGFloat? = 180
    var lineCount: Int = 3
    var showAvatar: Bool = false

    var body: some View {
        HStack(alignment: .top, spacing: AppSpacing.s3) {
            if showAvatar {
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .fill(appTheme.palette.mutedFill)
                    .frame(width: 44, height: 44)
            }

            VStack(alignment: .leading, spacing: AppSpacing.s2) {
                AppSkeletonLine(width: titleWidth, height: 14)
                ForEach(0..<lineCount, id: \.self) { _ in
                    AppSkeletonLine(height: 10)
                }
            }
        }
        .padding(AppSpacing.cardOuterPadding)
        .background(
            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                .fill(appTheme.palette.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                .stroke(appTheme.palette.cardBorder, lineWidth: 1)
        )
    }
}

#Preview("AppSkeleton") {
    AppThemeContainer {
        VStack(spacing: AppSpacing.s4) {
            AppSkeletonLine(width: 200)
            AppSkeletonLine()
            AppSkeletonCard()
            AppSkeletonCard(showAvatar: true)
        }
        .padding(AppSpacing.s5)
    }
    .environmentObject(AppAppearanceStore.preview)
}
