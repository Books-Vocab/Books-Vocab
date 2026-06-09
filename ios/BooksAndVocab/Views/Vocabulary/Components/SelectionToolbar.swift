import SwiftUI

struct SelectionToolbar: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var appSkin

    let selectionCount: Int
    let onArchive: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: appSkin.spacing.sectionGap) {
            toolbarButton(
                label: "封存".localized,
                systemImage: "archivebox",
                tone: appSkin.palette.quaternaryText,
                action: onArchive
            )
            toolbarButton(
                label: "刪除".localized,
                systemImage: "trash",
                tone: appTheme.palette.destructive,
                action: onDelete
            )
        }
        .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
        .padding(.vertical, AppSpacing.s2)
        .background(appSkin.palette.cardBackground)
        .appElevation(.z2, direction: .up)
        .enableInjection()
    }

    @ViewBuilder
    private func toolbarButton(label: String, systemImage: String, tone: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: appSkin.spacing.microGap) {
                Image(systemName: systemImage)
                    .font(appSkin.typography.iconMedium)
                Text(label)
                    .font(appSkin.typography.caption)
            }
            .foregroundStyle(selectionCount > 0 ? tone : appSkin.palette.quaternaryText)
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
                onArchive: {},
                onDelete: {}
            )
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}
