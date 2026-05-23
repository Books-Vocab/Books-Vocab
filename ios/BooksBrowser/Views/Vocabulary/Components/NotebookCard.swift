import SwiftUI

enum NotebookExportFormat {
    case csv, json, anki
}

struct NotebookCardActions {
    var setActive: (() -> Void)?
    var rename: (() -> Void)?
    var editCover: (() -> Void)?
    var export: ((NotebookExportFormat) -> Void)?
    var delete: (() -> Void)?
    var canDelete: Bool = true
}

/// `NotebookCard` 視覺變體。
///
/// - `.grid` (default)：3:2 封面，緊湊 metadata，給 ≥2 本 notebook 並排場景。
/// - `.hero`：寬幅 2:1 封面 + 大號名稱 + 兩列 metadata，跨整列寬度。
///   用於 NotebookListView 在 `notebooks.count == 1` 時 — grid 視覺心理暗示
///   「應該有很多」，但 99% 用戶只會建 1 本；hero 變體承認此事實，視覺心理
///   表達「這是你的單字本」而非「目錄」。
enum NotebookCardStyle {
    case grid
    case hero
}

struct NotebookCardData {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?
    let cardCount: Int
    var cardCountLabel: String = "個單字"
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool
}

struct NotebookCard: View {
    @Environment(\.appSkin) private var skin

    let data: NotebookCardData
    var style: NotebookCardStyle = .grid
    var actions: NotebookCardActions = NotebookCardActions()

    private var coverColor: Color {
        NotebookPalette.color(for: data.color)
    }

    private var pattern: NotebookCoverPattern? {
        data.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) }
    }

    private var totalSynced: Int {
        data.dueCount + data.unlearnedCount + data.reviewedCount
    }

    private var reviewProgress: Double {
        guard totalSynced > 0 else { return 0 }
        return Double(data.reviewedCount) / Double(totalSynced)
    }

    private var coverAspectRatio: CGFloat {
        switch style {
        case .grid: return 3.0 / 2.0
        case .hero: return 21.0 / 10.0   // 寬扁、視覺強調「這是首要的」
        }
    }

    /// hero 場景隱藏 `使用中` pill — 唯一存在不需此標籤。
    private var showsActivePill: Bool {
        switch style {
        case .grid: return data.isActive
        case .hero: return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            coverArea

            // Editorial hairline rule — 把 cover/metadata 之間從「色塊硬切」轉成「刻意的線」。
            // 僅 .grid 需要（hero 自有設計）。
            if style == .grid {
                Rectangle()
                    .fill(skin.palette.cardBorder)
                    .frame(height: AppMetrics.dividerStandard)
            }

            metadataArea
                .padding(.horizontal, skin.spacing.cardPadding)
                .padding(.vertical, skin.spacing.cardPadding * 0.8)
        }
        .background(skin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .stroke(skin.palette.cardBorder, lineWidth: 1)
        )
        // grid 鎖 3:4 整卡 aspect — 修左右兩本 metadata 高度不齊 / add 卡破節奏。
        // hero 不鎖（21:10 cover 已決定 hero 高度，整卡 fit content）。
        .modifier(GridAspectRatioModifier(style: style))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityAddTraits(.isButton)
        .contextMenu {
            if let setActive = actions.setActive, !data.isActive {
                Button {
                    setActive()
                } label: {
                    Label("設為使用中".localized, systemImage: "checkmark.circle")
                }
            }

            if let rename = actions.rename {
                Button {
                    rename()
                } label: {
                    Label("重新命名".localized, systemImage: "pencil")
                }
            }

            if let editCover = actions.editCover {
                Button {
                    editCover()
                } label: {
                    Label("封面設定".localized, systemImage: "paintpalette")
                }
            }

            if let export = actions.export {
                Divider()
                Menu {
                    Button {
                        export(.csv)
                    } label: {
                        Label("CSV", systemImage: "tablecells")
                    }
                    Button {
                        export(.json)
                    } label: {
                        Label("JSON", systemImage: "curlybraces")
                    }
                    Button {
                        export(.anki)
                    } label: {
                        Label("Anki TSV", systemImage: "rectangle.stack")
                    }
                } label: {
                    Label("匯出".localized, systemImage: "square.and.arrow.up")
                }
            }

            if let delete = actions.delete, actions.canDelete {
                Divider()
                Button(role: .destructive) {
                    delete()
                } label: {
                    Label("刪除".localized, systemImage: "trash")
                }
            }
        }
    }

    // MARK: - Subviews

    @ViewBuilder
    private var coverArea: some View {
        Group {
            switch style {
            case .grid:
                // 立體堆卡 — 層數由字數決定（0→1 / 1-50→2 / 51-200→3 / 200+→4）
                NotebookStackedCoverView(
                    color: coverColor,
                    pattern: pattern,
                    coverImagePath: data.coverImagePath,
                    name: data.name,
                    layerCount: NotebookStackMetrics.layerCount(forCardCount: data.cardCount),
                    aspectRatio: coverAspectRatio,
                    seed: data.name.hashValue
                )
            case .hero:
                // hero 維持平面（單本不擬物，避免「目錄」錯位心理）
                NotebookCoverView(
                    color: coverColor,
                    pattern: pattern,
                    coverImagePath: data.coverImagePath,
                    name: data.name
                )
                .aspectRatio(coverAspectRatio, contentMode: .fill)
                .clipShape(UnevenRoundedRectangle(
                    topLeadingRadius: skin.radii.card,
                    topTrailingRadius: skin.radii.card
                ))
            }
        }
        .overlay(alignment: .topTrailing) {
            if showsActivePill {
                Text("使用中".localized)
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(.white)
                    .padding(.horizontal, AppSpacing.s2)
                    .padding(.vertical, AppSpacing.tinyGap)
                    .background(skin.palette.accent, in: Capsule(style: .continuous))
                    .padding(AppSpacing.s2)
            }
        }
        // Editorial rotation — 包 pill overlay 一起轉，避免 pill 脫離卡片邊界。
        // hero 不旋轉（單本平面），grid 走 deterministic seedJitter。
        .rotationEffect(coverRotation, anchor: .bottom)
    }

    /// 整 coverArea 的 rotation（grid 走 seedJitter depth=0、hero 為 0）。
    private var coverRotation: Angle {
        switch style {
        case .grid:
            return .degrees(NotebookStackMetrics.seedJitter(seed: data.name.hashValue, depth: 0).angle)
        case .hero:
            return .zero
        }
    }

    /// Stable-height metadata：ProgressCapsule 與 chips row 永遠在版面上，
    /// 無資料時以 placeholder / opacity=0 撐位，避免 grid 兩本高度不齊。
    @ViewBuilder
    private var metadataArea: some View {
        VStack(alignment: .leading, spacing: skin.spacing.microGap) {
            HStack {
                Label("\(data.cardCount) \(data.cardCountLabel)", systemImage: "character.book.closed")
                    .font(skin.typography.caption)
                    .monospacedDigit()
                    .foregroundStyle(skin.palette.secondaryText)

                Spacer()

                if data.pendingCount > 0 {
                    Label("\(data.pendingCount)", systemImage: "arrow.triangle.2.circlepath")
                        .font(skin.typography.monoLabel)
                        .monospacedDigit()
                        .foregroundStyle(skin.palette.tertiaryText)
                }
            }

            // 永遠 render — 無資料時 progress=0 + track only（同高度）
            ProgressCapsule(
                progress: totalSynced > 0 ? reviewProgress : 0,
                label: nil,
                fillColor: skin.palette.accent,
                trackColor: skin.palette.progressBarBackground,
                height: 5
            )

            // 永遠 render — 無資料時整 row opacity=0 撐同高
            HStack(spacing: skin.spacing.inlineGap) {
                if data.dueCount > 0 {
                    Label("\(data.dueCount) 到期", systemImage: "clock.badge")
                        .font(skin.typography.monoLabel)
                        .monospacedDigit()
                        .foregroundStyle(skin.palette.warning)
                }
                if data.unlearnedCount > 0 {
                    Label("\(data.unlearnedCount) 未學", systemImage: "sparkles")
                        .font(skin.typography.monoLabel)
                        .monospacedDigit()
                        .foregroundStyle(skin.palette.secondaryText)
                }
                if data.dueCount == 0 && data.unlearnedCount == 0 {
                    // Spacer placeholder — 同 font 確保 row height 一致
                    Label("0", systemImage: "clock.badge")
                        .font(skin.typography.monoLabel)
                        .monospacedDigit()
                        .opacity(0)
                        .accessibilityHidden(true)
                }
            }
        }
    }

    private var accessibilityDescription: String {
        var parts = [data.name, "\(data.cardCount) \(data.cardCountLabel)"]
        if data.dueCount > 0 { parts.append("\(data.dueCount) 到期") }
        if data.unlearnedCount > 0 { parts.append("\(data.unlearnedCount) 未學") }
        if data.isActive { parts.append("使用中") }
        return parts.joined(separator: "，")
    }
}

/// 僅 `.grid` 樣式套整卡 aspect ratio，hero 不鎖（避免寬扁 cover 被壓縮）。
private struct GridAspectRatioModifier: ViewModifier {
    let style: NotebookCardStyle

    func body(content: Content) -> some View {
        switch style {
        case .grid:
            content.aspectRatio(LayoutMode.notebookCardAspectRatio, contentMode: .fit)
        case .hero:
            content
        }
    }
}

struct NotebookAddCard: View {
    @Environment(\.appSkin) private var skin

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            Image(systemName: "plus")
                .font(skin.typography.symbolLarge)
                .foregroundStyle(skin.palette.tertiaryText)
            Text("新增單字本".localized)
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.tertiaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // 與 NotebookCard(.grid) 同 aspect — 修奇數本 / 偶數本 add 卡破節奏
        .aspectRatio(LayoutMode.notebookCardAspectRatio, contentMode: .fit)
        .background(skin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
                .foregroundStyle(skin.palette.cardBorder)
        )
    }
}

#Preview {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 160))], spacing: AppSpacing.s3) {
        NotebookCard(data: .init(
            name: "Self", color: "#4A90D9", coverPattern: "dots",
            coverImagePath: nil, cardCount: 42, dueCount: 5,
            unlearnedCount: 3, reviewedCount: 34, pendingCount: 0,
            lastActivity: Date().addingTimeInterval(-7200), isActive: true
        ))
        NotebookCard(data: .init(
            name: "Test", color: "#D4A843", coverPattern: nil,
            coverImagePath: nil, cardCount: 18, dueCount: 0,
            unlearnedCount: 8, reviewedCount: 2, pendingCount: 3,
            lastActivity: nil, isActive: false
        ))
        NotebookAddCard()
    }
    .padding()
}
