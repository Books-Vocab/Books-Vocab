#if os(iOS)
//
//  ExploreFilterChip.swift
//  Books & Vocab
//
//  Explore 篩選膠囊。與 Overview / Vocabulary 共用 iOS 26 system glass，
//  不在內容層另畫 border、shadow 或第二層背景。
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
        .appFilterGlass(isSelected: isSelected, tint: appTheme.palette.accent)
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
