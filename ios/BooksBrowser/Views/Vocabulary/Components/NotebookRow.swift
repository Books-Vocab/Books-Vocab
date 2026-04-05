//
//  NotebookRow.swift
//  BooksBrowser
//
//  單字本列表的行元件

import SwiftUI

extension Color {
    init?(hex: String) {
        var hex = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6, let int = UInt64(hex, radix: 16) else { return nil }
        self.init(
            red: Double((int >> 16) & 0xFF) / 255,
            green: Double((int >> 8) & 0xFF) / 255,
            blue: Double(int & 0xFF) / 255
        )
    }
}

struct NotebookRow: View {
    let name: String
    let cardCount: Int
    let dueCount: Int
    let isActive: Bool
    let color: Color?

    @Environment(\.vocabSkin) private var skin

    var body: some View {
        HStack(spacing: skin.spacing.wordRowHorizontalGap) {
            // Color indicator
            RoundedRectangle(cornerRadius: skin.radii.tiny)
                .fill(color ?? skin.palette.accent)
                .frame(width: 4, height: 36)

            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                HStack(spacing: skin.spacing.inlineGap) {
                    Text(name)
                        .font(skin.typography.rowWord)
                        .foregroundStyle(skin.palette.primaryText)

                    if isActive {
                        Text("使用中".localized)
                            .font(skin.typography.caption)
                            .foregroundStyle(skin.palette.accent)
                            .padding(.horizontal, skin.spacing.compactChipHorizontalPadding)
                            .padding(.vertical, skin.spacing.compactChipVerticalPadding)
                            .background(skin.palette.accent.opacity(0.12), in: Capsule())
                    }
                }

                HStack(spacing: skin.spacing.inlineGap) {
                    Label("\(cardCount)", systemImage: "character.book.closed")
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)

                    if dueCount > 0 {
                        Label("\(dueCount)", systemImage: "clock.badge")
                            .font(skin.typography.caption)
                            .foregroundStyle(skin.palette.warning)
                    }
                }
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.tertiaryText)
        }
        .padding(.vertical, skin.spacing.rowPadding)
        .padding(.horizontal, skin.metrics.listRowHorizontalInset)
        .contentShape(Rectangle())
    }
}
