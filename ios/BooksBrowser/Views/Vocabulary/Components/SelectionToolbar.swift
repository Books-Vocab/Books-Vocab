import SwiftUI

struct SelectionToolbar: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

    let selectionCount: Int
    let onMove: () -> Void
    let onArchive: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            toolbarButton(
                label: "移動".localized,
                systemImage: "folder",
                tone: appTheme.palette.accent,
                action: onMove
            )
            toolbarButton(
                label: "封存".localized,
                systemImage: "archivebox",
                tone: vocabSkin.palette.quaternaryText,
                action: onArchive
            )
            toolbarButton(
                label: "刪除".localized,
                systemImage: "trash",
                tone: appTheme.palette.destructive,
                action: onDelete
            )
        }
        .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
        .padding(.vertical, AppMetrics.spacingSmall)
        .background(
            vocabSkin.palette.cardBackground
                .shadow(.drop(color: .black.opacity(0.1), radius: 8, y: -2))
        )
    }

    @ViewBuilder
    private func toolbarButton(label: String, systemImage: String, tone: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: vocabSkin.spacing.microGap) {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconMedium)
                Text(label)
                    .font(vocabSkin.typography.caption)
            }
            .foregroundStyle(selectionCount > 0 ? tone : vocabSkin.palette.quaternaryText)
            .frame(maxWidth: .infinity)
        }
        .disabled(selectionCount == 0)
    }
}

#Preview {
    AppThemeContainer {
        VStack {
            Spacer()
            SelectionToolbar(
                selectionCount: 3,
                onMove: {},
                onArchive: {},
                onDelete: {}
            )
        }
    }
}
