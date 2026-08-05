#if os(iOS)
//
//  ExploreFilterChip.swift
//  Books & Vocab
//
//  Explore 篩選膠囊。Mochi 北極星：無 border、選中只改 bg-color（accent，四軸內）、
//  非按鈕互動不動 transform。
//

import SwiftUI

/// 純視覺 label（供 chip 與 Menu label 共用）。
struct ExploreFilterChipLabel: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let title: String
    var systemImage: String?
    let isSelected: Bool

    init(title: String, systemImage: String? = nil, isSelected: Bool) {
        self.title = title
        self.systemImage = systemImage
        self.isSelected = isSelected
    }

    var body: some View {
        HStack(spacing: AppSpacing.microGap) {
            if let systemImage {
                Image(systemName: systemImage)
            }
            Text(title)
                .lineLimit(1)
        }
        .font(AppFonts.caption2(weight: .medium))
        .foregroundStyle(isSelected ? appTheme.palette.pageBackground : appTheme.palette.secondaryText)
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSpacing.s1)
        .background(
            AppRoundedRect(roundness: AppRoundness.pill)
                .fill(isSelected ? appTheme.palette.accent : appTheme.palette.mutedFill)
        )
        .enableInjection()
    }
}

struct ExploreFilterChip: View {
    @ObserveInjection private var inject
    let title: String
    var systemImage: String?
    let isSelected: Bool
    let action: () -> Void

    init(title: String, systemImage: String? = nil, isSelected: Bool, action: @escaping () -> Void) {
        self.title = title
        self.systemImage = systemImage
        self.isSelected = isSelected
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            ExploreFilterChipLabel(title: title, systemImage: systemImage, isSelected: isSelected)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
        .enableInjection()
    }
}
#endif
