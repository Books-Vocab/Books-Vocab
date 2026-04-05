import SwiftUI

struct AppFilterChipBar<ID: Hashable>: View {
    let options: [AppTabOption<ID>]
    @Binding var selection: Set<ID>
    let style: AppTabSelectorStyle

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options) { option in
                let isSelected = selection.contains(option.id)
                Button {
                    withAnimation(AppMotion.chipSelectionEaseOut) {
                        if isSelected {
                            selection.remove(option.id)
                        } else {
                            selection.insert(option.id)
                        }
                    }
                } label: {
                    HStack(spacing: 6) {
                        if let systemImage = option.systemImage {
                            Image(systemName: systemImage)
                                .font(style.iconFont)
                                .foregroundStyle(isSelected ? style.iconSelectedColor : style.iconUnselectedColor)
                                .fixedSize()
                        }

                        Text(option.title.localized)
                            .font(style.titleFont)
                            .foregroundStyle(isSelected ? style.textSelectedColor : style.textUnselectedColor)
                            .lineLimit(1)
                            .minimumScaleFactor(0.72)
                            .layoutPriority(1)

                        if let count = option.count {
                            Text("\(count)")
                                .font(style.countFont)
                                .minimumScaleFactor(0.7)
                                .monospacedDigit()
                                .lineLimit(1)
                                .fixedSize(horizontal: true, vertical: false)
                                .frame(minWidth: 26)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(
                                    Capsule(style: .continuous)
                                        .fill(isSelected ? style.countSelectedFill : style.countUnselectedFill)
                                )
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 8)
                    .background(
                        Capsule(style: .continuous)
                            .fill(isSelected ? style.selectedBackground : style.unselectedBackground)
                    )
                    .overlay(
                        Capsule(style: .continuous)
                            .stroke(isSelected ? style.selectedBorder : style.unselectedBorder, lineWidth: 1)
                    )
                    .overlay(
                        Capsule(style: .continuous)
                        .stroke(
                            isSelected ? style.selectedOuterBorder : style.unselectedOuterBorder,
                            lineWidth: 0.8
                        )
                        .padding(-style.outerBorderInset)
                    )
                }
                .buttonStyle(.plain)
                .accessibilityLabel(option.count.map { "\(option.title.localized), \($0) \("個項目".localized)" } ?? option.title.localized)
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(3)
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
}

private struct AppFilterChipBarPreview: View {
    @Environment(\.appTheme) private var appTheme
    @State private var selected: Set<Int> = []

    var body: some View {
        VStack(spacing: 20) {
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
