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

enum NotebookPalette {
    static let colors: [(name: String, hex: String)] = [
        ("森林", "#5B8C5A"), ("海洋", "#4A90D9"),
        ("琥珀", "#D4A843"), ("紫藤", "#A855C7"),
        ("珊瑚", "#D9534F"), ("石墨", "#6B7280"),
        ("薄荷", "#5CC6B0"), ("靛藍", "#4F46E5"),
        ("玫瑰", "#E8789A"), ("焦糖", "#B8763E"),
        ("天空", "#7CB9E8"), ("薰衣草", "#9B8EC4"),
    ]

    static let defaultHex = "#4A90D9"

    static func color(for hex: String?) -> Color {
        guard let hex, let c = Color(hex: hex) else {
            return Color(hex: defaultHex) ?? .blue
        }
        return c
    }
}
