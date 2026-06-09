import SwiftUI

struct AppFilterChipBar<ID: Hashable>: View {
    let options: [AppTabOption<ID>]
    @Binding var selection: Set<ID>
    let style: AppTabSelectorStyle

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            ForEach(options) { option in
                let isSelected = selection.contains(option.id)
                Button {
                    withAnimation(AppMotion.chipSelect) {
                        if isSelected {
                            selection.remove(option.id)
                        } else {
                            selection.insert(option.id)
                        }
                    }
                } label: {
                    appChipLabel(option: option, isSelected: isSelected, style: style)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(appChipAccessibilityLabel(option: option))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(AppSpacing.tinyGap)
        .background(
            RoundedRectangle(cornerRadius: style.containerRadius, style: .continuous)
                .fill(style.containerBackground)
        )
    }
}

#Preview("AppFilterChipBar") {
    AppThemeContainer {
        AppFilterChipBarPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppFilterChipBarPreview: View {
    @Environment(\.appTheme) private var appTheme
    @State private var selected: Set<Int> = []

    var body: some View {
        VStack(spacing: AppSpacing.s5) {
            AppFilterChipBar(
                options: [
                    .init(id: 0, title: "未學習", count: 12),
                    .init(id: 1, title: "待複習", count: 5),
                    .init(id: 2, title: "已複習", count: 27)
                ],
                selection: $selected,
                style: .themed(appTheme)
            )
            Text("Selected: \(selected.sorted().map(String.init).joined(separator: ", "))")
        }
        .padding()
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
