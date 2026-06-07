#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Review Fold presentational pieces:
/// `ReviewFoldChevronPill`, `PaperFoldModifier`, and `ReviewFoldSurface`.
/// All pieces are pure SwiftUI views (no @MainActor init), so plain
/// closures are sufficient; we still wrap roots in `AppThemeContainer`.
enum ReviewFoldScenarios {
    static func register(in playbook: Playbook) {
        // MARK: - Chevron Pill
        playbook.addScenarios(of: "Review Fold · Chevron Pill") {
            Scenario("Collapse handle", layout: .fill) {
                AppThemeContainer {
                    ReviewFoldChevronPill(
                        action: {},
                        accessibilityLabel: "收合"
                    )
                    .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            // On a card-like backdrop so the capsule fill/border read in context.
            Scenario("On card backdrop", layout: .fill) {
                AppThemeContainer {
                    Self.sampleCard(title: "knowledge graph", subtitle: "知識圖譜")
                        .overlay(alignment: .bottom) {
                            ReviewFoldChevronPill(
                                action: {},
                                accessibilityLabel: "收合"
                            )
                            .offset(y: 10)
                        }
                        .padding(40)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: - Paper Fold (fractions)
        playbook.addScenarios(of: "Review Fold · Paper Fold") {
            Scenario("Expanded (1.0)", layout: .fill) {
                Self.foldedCard(progress: 1.0)
            }
            Scenario("Three-quarter (0.75)", layout: .fill) {
                Self.foldedCard(progress: 0.75)
            }
            Scenario("Half (0.5)", layout: .fill) {
                Self.foldedCard(progress: 0.5)
            }
            Scenario("Quarter (0.25)", layout: .fill) {
                Self.foldedCard(progress: 0.25)
            }
            Scenario("Nearly folded (0.05)", layout: .fill) {
                Self.foldedCard(progress: 0.05)
            }
        }

        // MARK: - Fold Surface (segment positions)
        playbook.addScenarios(of: "Review Fold · Segment") {
            Scenario("Single", layout: .fill) {
                Self.segmentScene(position: .single)
            }
            // Stacked group: top + middle + bottom join radii.
            Scenario("Stacked group", layout: .fill) {
                AppThemeContainer {
                    VStack(spacing: 0) {
                        ReviewFoldSurface(position: .top) {
                            Self.segmentBody(title: "serendipity", subtitle: "機緣巧合")
                        }
                        ReviewFoldSurface(position: .middle) {
                            Self.segmentBody(title: "epiphany", subtitle: "頓悟")
                        }
                        ReviewFoldSurface(position: .bottom) {
                            Self.segmentBody(title: "revelation", subtitle: "揭示")
                        }
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }

    // MARK: - Fixtures

    private static func foldedCard(progress: CGFloat) -> some View {
        AppThemeContainer {
            sampleCard(title: "serendipity", subtitle: "機緣巧合")
                .modifier(PaperFoldModifier(progress: progress))
                .padding(40)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func segmentScene(position: FoldSegmentPosition) -> some View {
        AppThemeContainer {
            ReviewFoldSurface(position: position) {
                segmentBody(title: "serendipity", subtitle: "機緣巧合")
            }
            .padding(40)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    @ViewBuilder
    private static func segmentBody(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.headline)
            Text(subtitle)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
    }

    private static func sampleCard(title: String, subtitle: String) -> some View {
        let skin = AppSkin.previewNeutral
        return VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.title3.weight(.semibold))
            Text(subtitle)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("一張用於展示摺疊效果的範例卡片。")
                .font(.footnote)
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .fill(skin.palette.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .stroke(skin.palette.cardBorder, lineWidth: 1)
        )
    }
}
#endif
