#if os(iOS)
import SwiftUI

enum VocabHighlightColorPreset: String, CaseIterable, Identifiable {
    case paper
    case blue
    case sage
    case rose

    var id: String { rawValue }

    var titleKey: String {
        "vocab.highlight.color.\(rawValue)"
    }

    func cssColor(for theme: ReaderTheme) -> String {
        switch (self, theme) {
        case (.paper, .light): return "43, 34%, 62%"
        case (.paper, .sepia): return "30, 32%, 54%"
        case (.paper, .dark): return "41, 30%, 66%"
        case (.blue, .light): return "212, 32%, 47%"
        case (.blue, .sepia): return "212, 24%, 48%"
        case (.blue, .dark): return "210, 32%, 64%"
        case (.sage, .light): return "124, 22%, 46%"
        case (.sage, .sepia): return "112, 18%, 42%"
        case (.sage, .dark): return "120, 22%, 62%"
        case (.rose, .light): return "350, 28%, 58%"
        case (.rose, .sepia): return "350, 24%, 50%"
        case (.rose, .dark): return "350, 30%, 68%"
        }
    }

    func swiftUIColor(for colorScheme: ColorScheme) -> Color {
        switch self {
        case .paper:
            switch colorScheme {
            case .light: return Color(red: 0.90, green: 0.84, blue: 0.57)
            case .dark: return Color(red: 0.73, green: 0.66, blue: 0.33)
            @unknown default: return Color(red: 0.90, green: 0.84, blue: 0.57)
            }
        case .blue:
            switch colorScheme {
            case .light: return Color(red: 0.30, green: 0.45, blue: 0.59)
            case .dark: return Color(red: 0.54, green: 0.65, blue: 0.76)
            @unknown default: return Color(red: 0.30, green: 0.45, blue: 0.59)
            }
        case .sage:
            switch colorScheme {
            case .light: return Color(red: 0.42, green: 0.57, blue: 0.41)
            case .dark: return Color(red: 0.58, green: 0.70, blue: 0.56)
            @unknown default: return Color(red: 0.42, green: 0.57, blue: 0.41)
            }
        case .rose:
            switch colorScheme {
            case .light: return Color(red: 0.70, green: 0.45, blue: 0.52)
            case .dark: return Color(red: 0.78, green: 0.58, blue: 0.64)
            @unknown default: return Color(red: 0.70, green: 0.45, blue: 0.52)
            }
        }
    }
}

struct VocabHighlightPreferences: Equatable {
    static let defaultOpacity = 0.22
    static let defaultBandFraction = 0.32
    static let `default` = VocabHighlightPreferences(
        colorPreset: .paper,
        opacity: defaultOpacity,
        bandFraction: defaultBandFraction
    )

    var colorPreset: VocabHighlightColorPreset
    var opacity: Double
    var bandFraction: Double

    var isEnabled: Bool { opacity > 0 }

    init(
        colorPreset: VocabHighlightColorPreset = .paper,
        opacity: Double = Self.defaultOpacity,
        bandFraction: Double = Self.defaultBandFraction
    ) {
        self.colorPreset = colorPreset
        self.opacity = opacity
        self.bandFraction = bandFraction
    }

    static func resolve(
        storedPresetRaw: String?,
        storedOpacity: Double?,
        legacyOpacity: Double?
    ) -> VocabHighlightPreferences {
        VocabHighlightPreferences(
            colorPreset: storedPresetRaw.flatMap(VocabHighlightColorPreset.init(rawValue:)) ?? .paper,
            opacity: storedOpacity ?? legacyOpacity ?? defaultOpacity,
            bandFraction: defaultBandFraction
        )
    }
}
#endif
