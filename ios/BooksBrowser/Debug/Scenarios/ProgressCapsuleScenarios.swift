#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the `ProgressCapsule` component.
/// Renders multiple progress fractions, label variants, color variants and a
/// stress stack to exercise clamping/edge fractions.
enum ProgressCapsuleScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Progress Capsule") {
            Scenario("Fraction Ladder", layout: .fill) {
                FractionLadderScene()
            }
            Scenario("Color Variants", layout: .fill) {
                ColorVariantsScene()
            }
            Scenario("No Label", layout: .fill) {
                NoLabelScene()
            }
            Scenario("Edge / Stress", layout: .fill) {
                EdgeStressScene()
            }
        }
    }
}

// MARK: - Scene harnesses

private struct FractionLadderScene: View {
    private let fractions: [Double] = [0.0, 0.25, 0.5, 0.67, 0.9, 1.0]

    var body: some View {
        AppThemeContainer {
            VStack(spacing: AppSpacing.s4) {
                ForEach(fractions, id: \.self) { value in
                    ProgressCapsule(
                        progress: value,
                        label: "\(Int(value * 100))%",
                        fillColor: .blue,
                        trackColor: .blue.opacity(0.15)
                    )
                }
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct ColorVariantsScene: View {
    var body: some View {
        AppThemeContainer {
            VStack(spacing: AppSpacing.s4) {
                ProgressCapsule(progress: 0.4, label: "40%", fillColor: .blue, trackColor: .blue.opacity(0.15))
                ProgressCapsule(progress: 0.6, label: "60%", fillColor: .green, trackColor: .green.opacity(0.15))
                ProgressCapsule(progress: 0.8, label: "80%", fillColor: .orange, trackColor: .orange.opacity(0.15))
                ProgressCapsule(progress: 0.95, label: "95%", fillColor: .red, trackColor: .red.opacity(0.15))
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct NoLabelScene: View {
    var body: some View {
        AppThemeContainer {
            VStack(spacing: AppSpacing.s4) {
                ProgressCapsule(progress: 0.3, label: nil, fillColor: .blue, trackColor: .blue.opacity(0.15))
                ProgressCapsule(progress: 0.7, label: nil, fillColor: .green, trackColor: .green.opacity(0.15), height: 10)
                ProgressCapsule(progress: 1.0, label: nil, fillColor: .orange, trackColor: .orange.opacity(0.15), height: 14)
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct EdgeStressScene: View {
    var body: some View {
        AppThemeContainer {
            VStack(spacing: AppSpacing.s4) {
                // Below-zero progress clamps to empty.
                ProgressCapsule(progress: -0.5, label: "clamp 0", fillColor: .blue, trackColor: .blue.opacity(0.15))
                // Above-one progress clamps to full.
                ProgressCapsule(progress: 1.8, label: "clamp 1", fillColor: .green, trackColor: .green.opacity(0.15))
                // Tall capsule with a long label.
                ProgressCapsule(
                    progress: 0.55,
                    label: "55% 進度",
                    fillColor: .orange,
                    trackColor: .orange.opacity(0.15),
                    height: 18
                )
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
