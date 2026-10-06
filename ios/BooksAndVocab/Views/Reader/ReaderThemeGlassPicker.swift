#if os(iOS)
import SwiftUI

/// Three editorial paper previews for the Reader theme setting.
///
/// The tile owns only layout and content. Material, selection tint, corner
/// treatment, and interaction are all supplied by the existing iOS 26 glass
/// primitives so this control does not create a second surface language.
enum ReaderThemeGlassPickerMetrics {
    /// 96pt: enough room for a localized two-line label while still allowing
    /// three equal columns on the regular iPhone settings sheet.
    static let minimumTileWidth = AppSpacing.s10 + AppSpacing.s6 + AppSpacing.s2
    /// 56pt: a small paper preview, deliberately kept below the tile's text
    /// rhythm so Dynamic Type can grow the row instead of shrinking the label.
    static let previewHeight = AppSpacing.s7 + AppSpacing.s3 + AppSpacing.s2 + AppSpacing.s1
    static let minimumHitTarget = AppFloatingChromeMetrics.hitTarget
}

struct ReaderThemeGlassPicker: View {
    @ObserveInjection private var inject

    @Binding var selection: ReaderTheme
    let onSelect: (ReaderTheme) -> Void

    var body: some View {
        // Keep the semantic container outside GlassEffectContainer. The outer
        // VStack preserves the existing `reader.settings.theme` UI contract as
        // an `Other` element while the glass container remains visual/layout
        // infrastructure only.
        VStack(spacing: 0) {
            GlassEffectContainer(spacing: AppSpacing.s2) {
                LazyVGrid(
                    columns: [
                        GridItem(
                            .adaptive(minimum: ReaderThemeGlassPickerMetrics.minimumTileWidth),
                            spacing: AppSpacing.s2
                        )
                    ],
                    spacing: AppSpacing.s2
                ) {
                    ForEach(ReaderTheme.allCases) { theme in
                        let isSelected = selection == theme
                        Button {
                            onSelect(theme)
                        } label: {
                            tileContent(theme, isSelected: isSelected)
                                .frame(
                                    maxWidth: .infinity,
                                    minHeight: ReaderThemeGlassPickerMetrics.minimumHitTarget,
                                    alignment: .topLeading
                                )
                                .contentShape(Rectangle())
                                .glassEffect(
                                    .regular
                                        .tint(isSelected ? Color.accentColor : nil)
                                        .interactive(),
                                    in: AppRoundedRect(roundness: AppRoundness.control)
                                )
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("reader.settings.theme.\(theme.rawValue.lowercased())")
                        .accessibilityLabel(theme.displayName)
                        .accessibilityAddTraits(isSelected ? .isSelected : [])
                    }
                }
            }
        }
        .padding(.vertical, AppSpacing.s1)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.settings.theme")
        .enableInjection()
    }

    @ViewBuilder
    private func tileContent(_ theme: ReaderTheme, isSelected: Bool) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            paperPreview(theme)

            HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s1) {
                Image(systemName: theme.icon)
                    .font(.caption.weight(.semibold))
                    .symbolRenderingMode(.hierarchical)
                    .accessibilityHidden(true)

                Text(theme.displayName)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: AppSpacing.s1)

                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.caption.weight(.bold))
                        .accessibilityHidden(true)
                }
            }
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSpacing.s2)
    }

    private func paperPreview(_ theme: ReaderTheme) -> some View {
        ZStack(alignment: .bottomTrailing) {
            AppRoundedRect(roundness: AppRoundness.control)
                .fill(theme.paperColor)

            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                ForEach(0..<3, id: \.self) { _ in
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(theme.inkColor.opacity(0.28))
                        .frame(maxWidth: .infinity, minHeight: AppSpacing.tinyGap)
                }
            }
            .padding(AppSpacing.s2)

            Text("Aa")
                .font(.body.weight(.bold))
                .foregroundStyle(theme.inkColor.opacity(0.72))
                .padding(.trailing, AppSpacing.s2)
                .padding(.bottom, AppSpacing.s1)
                .accessibilityHidden(true)
        }
        .frame(maxWidth: .infinity, minHeight: ReaderThemeGlassPickerMetrics.previewHeight)
        .accessibilityHidden(true)
    }
}
#endif
