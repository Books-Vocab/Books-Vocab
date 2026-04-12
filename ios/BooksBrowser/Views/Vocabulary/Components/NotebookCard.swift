import SwiftUI

struct NotebookCardData {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?
    let cardCount: Int
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool
}

struct NotebookCard: View {
    @Environment(\.vocabSkin) private var skin

    let data: NotebookCardData

    private var coverColor: Color {
        NotebookPalette.color(for: data.color)
    }

    private var pattern: NotebookCoverPattern? {
        data.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) }
    }

    private var totalSynced: Int {
        data.dueCount + data.unlearnedCount + data.reviewedCount
    }

    private var reviewProgress: Double {
        guard totalSynced > 0 else { return 0 }
        return Double(data.reviewedCount) / Double(totalSynced)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            NotebookCoverView(
                color: coverColor,
                pattern: pattern,
                coverImagePath: data.coverImagePath,
                name: data.name
            )
            .aspectRatio(3 / 2, contentMode: .fill)
            .clipShape(UnevenRoundedRectangle(
                topLeadingRadius: skin.radii.card,
                topTrailingRadius: skin.radii.card
            ))
            .overlay(alignment: .topTrailing) {
                if data.isActive {
                    Text("使用中".localized)
                        .font(skin.typography.monoLabel)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(skin.palette.accent, in: Capsule(style: .continuous))
                        .padding(8)
                }
            }

            VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                HStack {
                    Label("\(data.cardCount) 個單字", systemImage: "character.book.closed")
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)

                    Spacer()

                    if data.pendingCount > 0 {
                        Label("\(data.pendingCount)", systemImage: "arrow.triangle.2.circlepath")
                            .font(skin.typography.monoLabel)
                            .foregroundStyle(skin.palette.tertiaryText)
                    }
                }

                if totalSynced > 0 {
                    ProgressCapsule(
                        progress: reviewProgress,
                        label: nil,
                        fillColor: skin.palette.accent,
                        trackColor: skin.palette.progressBarBackground,
                        height: 5
                    )
                }

                if data.dueCount > 0 || data.unlearnedCount > 0 {
                    HStack(spacing: skin.spacing.inlineGap) {
                        if data.dueCount > 0 {
                            Label("\(data.dueCount) 到期", systemImage: "clock.badge")
                                .font(skin.typography.monoLabel)
                                .foregroundStyle(skin.palette.warning)
                        }
                        if data.unlearnedCount > 0 {
                            Label("\(data.unlearnedCount) 未學", systemImage: "sparkles")
                                .font(skin.typography.monoLabel)
                                .foregroundStyle(skin.palette.secondaryText)
                        }
                    }
                }
            }
            .padding(.horizontal, skin.spacing.cardPadding)
            .padding(.vertical, skin.spacing.cardPadding * 0.8)
        }
        .background(skin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .stroke(skin.palette.cardBorder, lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
    }

    private var accessibilityDescription: String {
        var parts = [data.name, "\(data.cardCount) 個單字"]
        if data.dueCount > 0 { parts.append("\(data.dueCount) 到期") }
        if data.unlearnedCount > 0 { parts.append("\(data.unlearnedCount) 未學") }
        if data.isActive { parts.append("使用中") }
        return parts.joined(separator: "，")
    }
}

struct NotebookAddCard: View {
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            Image(systemName: "plus")
                .font(.title2)
                .foregroundStyle(skin.palette.tertiaryText)
            Text("新增單字本".localized)
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.tertiaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .aspectRatio(4 / 3, contentMode: .fit)
        .background(skin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
                .foregroundStyle(skin.palette.cardBorder)
        )
    }
}

#Preview {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 160))], spacing: 12) {
        NotebookCard(data: .init(
            name: "Self", color: "#4A90D9", coverPattern: "dots",
            coverImagePath: nil, cardCount: 42, dueCount: 5,
            unlearnedCount: 3, reviewedCount: 34, pendingCount: 0,
            lastActivity: Date().addingTimeInterval(-7200), isActive: true
        ))
        NotebookCard(data: .init(
            name: "Test", color: "#D4A843", coverPattern: nil,
            coverImagePath: nil, cardCount: 18, dueCount: 0,
            unlearnedCount: 8, reviewedCount: 2, pendingCount: 3,
            lastActivity: nil, isActive: false
        ))
        NotebookAddCard()
    }
    .padding()
}
