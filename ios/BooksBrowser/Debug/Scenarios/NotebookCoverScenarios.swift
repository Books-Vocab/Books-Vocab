#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `NotebookCoverView` / `NotebookCoverPattern`.
///
/// 全 6 個 pattern × 數種色票的網格快照，外加無 pattern (純色)、長名截斷、
/// showsName=false (NotebookCard editorial overlay 用法) 與 image-path fallback
/// (路徑不存在 → 降級回 pattern) 邊界。
///
/// 完全合成資料：NotebookCoverView 是 value-init View，不接 SwiftData / 網路，
/// 故 catalog 自給自足。
enum NotebookCoverScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Cover") {
            Scenario("All patterns · blue", layout: .fillH) {
                stage {
                    patternGrid(color: Self.blue)
                }
            }
            Scenario("All patterns · color swatches", layout: .fillH) {
                stage {
                    VStack(spacing: 16) {
                        ForEach(Array(Self.swatches.enumerated()), id: \.offset) { _, color in
                            patternRow(color: color)
                        }
                    }
                }
            }
            Scenario("Solid color · no pattern", layout: .fillH) {
                stage {
                    LazyVGrid(columns: Self.columns, spacing: 16) {
                        ForEach(Array(Self.swatches.enumerated()), id: \.offset) { _, color in
                            cover(color: color, pattern: nil, name: "純色")
                        }
                    }
                }
            }
            Scenario("Long name truncate", layout: .fillH) {
                stage {
                    LazyVGrid(columns: Self.columns, spacing: 16) {
                        cover(color: Self.blue, pattern: .dots, name: "我的英文單字本 — 進階學術詞彙與片語收藏夾")
                        cover(color: Self.purple, pattern: .grid, name: "Supercalifragilisticexpialidocious Notebook")
                        cover(color: Self.green, pattern: .waves, name: "短")
                    }
                }
            }
            Scenario("showsName = false (overlay use)", layout: .fillH) {
                stage {
                    patternGrid(color: Self.purple, showsName: false)
                }
            }
            Scenario("Image path fallback (missing → pattern)", layout: .fillH) {
                stage {
                    LazyVGrid(columns: Self.columns, spacing: 16) {
                        // 路徑不存在 → loadImage 回 nil → 降級渲染 pattern
                        cover(
                            color: Self.green,
                            pattern: .circles,
                            name: "Fallback",
                            coverImagePath: "/tmp/__kg_catalog_nonexistent_cover__.jpg"
                        )
                        cover(
                            color: Self.blue,
                            pattern: nil,
                            name: "純色 Fallback",
                            coverImagePath: "/tmp/__kg_catalog_nonexistent_cover__.jpg"
                        )
                    }
                }
            }
        }
    }

    // MARK: - Palette

    private static let blue = Color(hex: "#4A90D9") ?? .blue
    private static let purple = Color(hex: "#8E6FD6") ?? .purple
    private static let green = Color(hex: "#3FA77A") ?? .green
    private static let coral = Color(hex: "#E0735C") ?? .red

    private static let swatches: [Color] = [blue, purple, green, coral]

    private static let columns = [GridItem(.adaptive(minimum: 110), spacing: 16)]

    // MARK: - Builders

    private static func stage<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            ScrollView {
                content()
                    .padding(16)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func patternGrid(color: Color, showsName: Bool = true) -> some View {
        LazyVGrid(columns: columns, spacing: 16) {
            ForEach(NotebookCoverPattern.allCases) { pattern in
                cover(color: color, pattern: pattern, name: pattern.label, showsName: showsName)
            }
        }
    }

    private static func patternRow(color: Color) -> some View {
        LazyVGrid(columns: columns, spacing: 12) {
            ForEach(NotebookCoverPattern.allCases) { pattern in
                cover(color: color, pattern: pattern, name: pattern.label)
            }
        }
    }

    private static func cover(
        color: Color,
        pattern: NotebookCoverPattern?,
        name: String,
        coverImagePath: String? = nil,
        showsName: Bool = true
    ) -> some View {
        NotebookCoverView(
            color: color,
            pattern: pattern,
            coverImagePath: coverImagePath,
            name: name,
            showsName: showsName
        )
        .frame(height: 96)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
#endif
