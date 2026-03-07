import SwiftUI

struct VocabSkin {
    struct Palette {
        let pageBackground: Color
        let stageBackground: Color
        let cardBackground: Color
        let cardBorder: Color
        let divider: Color
        let shadow: Color
        let primaryText: Color
        let secondaryText: Color
        let tertiaryText: Color
        let quaternaryText: Color
        let translationText: Color
        let accent: Color
        let success: Color
        let destructive: Color
        let highlightMark: Color
        let mutedFill: Color
        let link: Color
    }

    struct Typography {
        let displayTitle: Font
        let sectionTitle: Font
        let detailWord: Font
        let reviewWord: Font
        let rowWord: Font
        let translationTitle: Font
        let body: Font
        let example: Font
        let caption: Font
        let captionStrong: Font
        let monoLabel: Font
        let numericHero: Font
    }

    struct Radii {
        let stage: CGFloat
        let card: CGFloat
        let overlay: CGFloat
        let control: CGFloat
        let chip: CGFloat
        let tiny: CGFloat
    }

    struct Spacing {
        let cardPadding: CGFloat
        let sectionGap: CGFloat
        let inlineGap: CGFloat
        let rowPadding: CGFloat
    }

    let palette: Palette
    let typography: Typography
    let radii: Radii
    let spacing: Spacing

    func tierColor(for tier: String?) -> Color {
        switch tier {
        case "core":
            return palette.success
        case "intermediate":
            return Color(red: 0.72, green: 0.63, blue: 0.36)
        case "advanced":
            return Color(red: 0.84, green: 0.54, blue: 0.28)
        case "rare":
            return palette.destructive
        default:
            return palette.secondaryText
        }
    }

    func tierLabel(for tier: String?) -> String {
        switch tier {
        case "core":
            return "core"
        case "intermediate":
            return "intermediate"
        case "advanced":
            return "advanced"
        case "rare":
            return "rare"
        default:
            return tier ?? ""
        }
    }
}

extension VocabSkin {
    static let mochiNeutral = VocabSkin(
        palette: .init(
            pageBackground: Color(red: 0.953, green: 0.952, blue: 0.946),
            stageBackground: Color(red: 0.976, green: 0.975, blue: 0.970),
            cardBackground: Color(red: 0.993, green: 0.992, blue: 0.989),
            cardBorder: Color.black.opacity(0.055),
            divider: Color.black.opacity(0.055),
            shadow: Color.black.opacity(0.045),
            primaryText: Color(red: 0.14, green: 0.14, blue: 0.14),
            secondaryText: Color(red: 0.50, green: 0.50, blue: 0.50),
            tertiaryText: Color(red: 0.68, green: 0.68, blue: 0.68),
            quaternaryText: Color(red: 0.78, green: 0.78, blue: 0.78),
            translationText: Color(red: 0.60, green: 0.52, blue: 0.40),
            accent: Color(red: 0.44, green: 0.55, blue: 0.72),
            success: Color(red: 0.43, green: 0.67, blue: 0.42),
            destructive: Color(red: 0.86, green: 0.41, blue: 0.38),
            highlightMark: Color(red: 0.92, green: 0.84, blue: 0.47),
            mutedFill: Color.black.opacity(0.035),
            link: Color(red: 0.44, green: 0.55, blue: 0.72)
        ),
        typography: .init(
            displayTitle: .system(size: 30, weight: .semibold, design: .default),
            sectionTitle: .system(size: 20, weight: .semibold, design: .default),
            detailWord: .system(size: 30, weight: .semibold, design: .monospaced),
            reviewWord: .system(size: 50, weight: .semibold, design: .monospaced),
            rowWord: .system(size: 20, weight: .semibold, design: .monospaced),
            translationTitle: .system(size: 25, weight: .semibold, design: .default),
            body: .system(size: 17, weight: .regular, design: .default),
            example: .system(size: 19, weight: .regular, design: .default),
            caption: .system(size: 13, weight: .medium, design: .default),
            captionStrong: .system(size: 13, weight: .semibold, design: .default),
            monoLabel: .system(size: 11, weight: .medium, design: .monospaced),
            numericHero: .system(size: 48, weight: .semibold, design: .default)
        ),
        radii: .init(
            stage: 18,
            card: 15,
            overlay: 16,
            control: 12,
            chip: 10,
            tiny: 8
        ),
        spacing: .init(
            cardPadding: 22,
            sectionGap: 18,
            inlineGap: 10,
            rowPadding: 12
        )
    )
}

private struct VocabSkinEnvironmentKey: EnvironmentKey {
    static let defaultValue = VocabSkin.mochiNeutral
}

extension EnvironmentValues {
    var vocabSkin: VocabSkin {
        get { self[VocabSkinEnvironmentKey.self] }
        set { self[VocabSkinEnvironmentKey.self] = newValue }
    }
}

extension View {
    func vocabSkin(_ skin: VocabSkin) -> some View {
        environment(\.vocabSkin, skin)
    }
}
