import SwiftUI

extension Color {
    init?(hex: String) {
        var hex = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6, let int = UInt64(hex, radix: 16) else { return nil }
        self.init(
            red: Double((int >> 16) & 0xFF) / 255,
            green: Double((int >> 8) & 0xFF) / 255,
            blue: Double(int & 0xFF) / 255
        )
    }
}

/// Morandi "Clearly Brighter" 12 色卡 — 與 cream paper ghost stack 同視覺族群。
/// HSB sat 13-30% / bright 67-86%，避免高飽和封面與 cream 內頁撕裂感。
///
/// 老 notebook 的 hex 仍存舊高飽和色；`color(for:)` 套 `legacyMigration`
/// render-time 轉換，零感知遷移、不寫 DB。
enum NotebookPalette {
    static let colors: [(name: String, hex: String)] = [
        ("森林", "#B1C5AE"), ("海洋", "#AFC2D3"),
        ("琥珀", "#DEC69C"), ("紫藤", "#C5B2D0"),
        ("珊瑚", "#DCABA4"), ("石墨", "#AFB2B7"),
        ("薄荷", "#B7D2C9"), ("靛藍", "#ADABCB"),
        ("玫瑰", "#DEBAC2"), ("焦糖", "#D2B69D"),
        ("天空", "#C5DAE2"), ("薰衣草", "#C3BCCF"),
    ]

    static let defaultHex = "#AFC2D3"  // 海洋 Dusty Blue

    /// 老資料 hex → 新 Morandi hex 對照表。
    /// Render-time 套用，不寫 DB（user 下次 edit cover 時 UI 自然寫新 hex）。
    private static let legacyMigration: [String: String] = [
        "#5B8C5A": "#B1C5AE",  // 森林
        "#4A90D9": "#AFC2D3",  // 海洋
        "#D4A843": "#DEC69C",  // 琥珀
        "#A855C7": "#C5B2D0",  // 紫藤
        "#D9534F": "#DCABA4",  // 珊瑚
        "#6B7280": "#AFB2B7",  // 石墨
        "#5CC6B0": "#B7D2C9",  // 薄荷
        "#4F46E5": "#ADABCB",  // 靛藍
        "#E8789A": "#DEBAC2",  // 玫瑰
        "#B8763E": "#D2B69D",  // 焦糖
        "#7CB9E8": "#C5DAE2",  // 天空
        "#9B8EC4": "#C3BCCF",  // 薰衣草
    ]

    static func color(for hex: String?) -> Color {
        guard let raw = hex else {
            return Color(hex: defaultHex) ?? .blue
        }
        let mapped = legacyMigration[raw.uppercased()] ?? raw
        return Color(hex: mapped) ?? Color(hex: defaultHex) ?? .blue
    }
}
