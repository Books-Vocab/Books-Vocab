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

    /// 生字色帶的色相，以整數 HSL 表示。
    ///
    /// 用 HSL 而不是 RGB 是因為**權威消費者是 CSS**（`hsla()`），而閱讀器正文是
    /// 一個 WKWebView。`cssColor(for:)` 與 `color(for:)` 都從這張表推導，所以
    /// 閱讀設定的原生即時預覽與網頁端拿到的是同一個色 —— 不是「調到看起來像」。
    struct HSL: Equatable {
        let hue: Int
        let saturation: Int
        let lightness: Int

        /// HSL → HSB。SwiftUI 只給得出 HSB 建構子，而權威值是 HSL。
        ///
        /// 標準換算：`v = l + s·min(l, 1−l)`、`s_v = v == 0 ? 0 : 2(1 − l/v)`。
        /// 抽成純函式是為了讓它能被斷言 —— 直接測 `Color` 會被色彩空間轉換
        /// 汙染，測出來的東西就不是這段數學了。
        var hsb: (hue: Double, saturation: Double, brightness: Double) {
            let lightness = Double(self.lightness) / 100
            let saturation = Double(self.saturation) / 100
            let brightness = lightness + saturation * min(lightness, 1 - lightness)
            return (
                hue: Double(self.hue) / 360,
                saturation: brightness == 0 ? 0 : 2 * (1 - lightness / brightness),
                brightness: brightness
            )
        }
    }

    /// preset × theme → 色相。**這是唯一一份**；新增 preset 或 theme 時只改這裡。
    func hsl(for theme: ReaderTheme) -> HSL {
        switch (self, theme) {
        case (.paper, .light): return HSL(hue: 43, saturation: 34, lightness: 62)
        case (.paper, .sepia): return HSL(hue: 30, saturation: 32, lightness: 54)
        case (.paper, .dark): return HSL(hue: 41, saturation: 30, lightness: 66)
        case (.blue, .light): return HSL(hue: 212, saturation: 32, lightness: 47)
        case (.blue, .sepia): return HSL(hue: 212, saturation: 24, lightness: 48)
        case (.blue, .dark): return HSL(hue: 210, saturation: 32, lightness: 64)
        case (.sage, .light): return HSL(hue: 124, saturation: 22, lightness: 46)
        case (.sage, .sepia): return HSL(hue: 112, saturation: 18, lightness: 42)
        case (.sage, .dark): return HSL(hue: 120, saturation: 22, lightness: 62)
        case (.rose, .light): return HSL(hue: 350, saturation: 28, lightness: 58)
        case (.rose, .sepia): return HSL(hue: 350, saturation: 24, lightness: 50)
        case (.rose, .dark): return HSL(hue: 350, saturation: 30, lightness: 68)
        }
    }

    /// `hsla()` 的前三個分量。輸出格式受 `VocabHighlightPreferencesTests` 釘住。
    func cssColor(for theme: ReaderTheme) -> String {
        let components = hsl(for: theme)
        return "\(components.hue), \(components.saturation)%, \(components.lightness)%"
    }

    /// 原生端的同一個色 —— 給閱讀設定的即時預覽用。
    ///
    /// 與下方 `swiftUIColor(for colorScheme:)` **刻意不同**：那一組是 podcast 字幕
    /// 與行銷截圖用的手調 RGB（只分 light / dark 兩階，且比 CSS 亮），改動它會
    /// 動到那些畫面。要與閱讀器正文同色的地方一律用這個。
    func color(for theme: ReaderTheme) -> Color {
        Color(hsl: hsl(for: theme))
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

extension Color {
    /// HSL → SwiftUI。換算集中在 `HSL.hsb`，這裡只負責接上建構子。
    init(hsl: VocabHighlightColorPreset.HSL) {
        let components = hsl.hsb
        self.init(
            hue: components.hue,
            saturation: components.saturation,
            brightness: components.brightness
        )
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
