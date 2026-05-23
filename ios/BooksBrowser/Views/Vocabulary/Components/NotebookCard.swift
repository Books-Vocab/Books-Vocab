import SwiftUI
import Inject

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
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var skin
    @Environment(\.colorScheme) private var colorScheme

    let data: NotebookCardData
    var style: NotebookCardStyle = .grid
    var actions: NotebookCardActions = NotebookCardActions()

    private var coverColor: Color {
        let raw = NotebookPalette.color(for: data.color)
        // Dark mode 自動加深 cover — 確保 primaryText dark(#E6E6E3)對 cover ≥ AA 4.5:1。
        // 走 `NotebookPalette.darken(_, by: 0.2)` 而非 `.brightness(-0.2)` —
        // HSB scale 跟 contrast test 的計算完全對齊(避免 sRGB additive vs HSB scale 分歧)。
        return colorScheme == .dark ? NotebookPalette.darken(raw, by: 0.2) : raw
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
                .padding(.horizontal, AppSpacing.s3)
                .padding(.vertical, AppSpacing.s2)
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
        .enableInjection()
    }

    // MARK: - Subviews

    @ViewBuilder
    private var coverArea: some View {
        Group {
            switch style {
            case .grid:
                // 立體堆卡 — 層數由字數決定（0→1 / 1-50→2 / 51-200→3 / 200+→4）
                // showsName: false — editorial overlay (EditorialCoverComposition) 接管 name 渲染
                NotebookStackedCoverView(
                    color: coverColor,
                    pattern: pattern,
                    coverImagePath: data.coverImagePath,
                    name: data.name,
                    layerCount: NotebookStackMetrics.layerCount(forCardCount: data.cardCount),
                    aspectRatio: coverAspectRatio,
                    seed: NotebookStackMetrics.stableSeed(for: data.name),
                    showsName: false
                )
            case .hero:
                // hero 維持平面（單本不擬物，避免「目錄」錯位心理）
                NotebookCoverView(
                    color: coverColor,
                    pattern: pattern,
                    coverImagePath: data.coverImagePath,
                    name: data.name,
                    showsName: false
                )
                .aspectRatio(coverAspectRatio, contentMode: .fill)
                .clipShape(UnevenRoundedRectangle(
                    topLeadingRadius: skin.radii.card,
                    topTrailingRadius: skin.radii.card
                ))
            }
        }
        // D1 editorial composition overlay — serif name / rule / N 詞 / (active) spine。
        // 跟著外層 `rotationEffect` 一起旋轉,不會脫離 cover 邊界。
        .overlay {
            EditorialCoverComposition(
                name: data.name,
                cardCount: data.cardCount,
                coverColor: coverColor,
                isActive: data.isActive,
                style: style
            )
        }
        // Editorial rotation — 包 overlay 一起轉,grid 走 deterministic seedJitter。
        .rotationEffect(coverRotation, anchor: .bottom)
    }

    /// 整 coverArea 的 rotation（grid 走 seedJitter depth=0、hero 為 0）。
    private var coverRotation: Angle {
        switch style {
        case .grid:
            return .degrees(NotebookStackMetrics.seedJitter(seed: NotebookStackMetrics.stableSeed(for: data.name), depth: 0).angle)
        case .hero:
            return .zero
        }
    }

    /// D2 — Editorial metadata：ProgressCapsule (永遠 render) + 條件 due chip。
    /// cardCount 已上移至 cover D1;pendingCount / unlearnedCount 移至 notebook 內頁 + TipView。
    @ViewBuilder
    private var metadataArea: some View {
        HStack(spacing: AppSpacing.s2) {
            ProgressCapsule(
                progress: totalSynced > 0 ? reviewProgress : 0,
                label: nil,
                fillColor: coverColor,  // editorial「閱讀進度條跟書同色」族群感
                trackColor: skin.palette.progressBarBackground,
                height: 5
            )
            .frame(maxWidth: .infinity)

            if data.dueCount > 0 {
                Label(L10n.format("%@ 到期", "\(data.dueCount)"), systemImage: "clock.badge")
                    .font(skin.typography.monoLabel)
                    .monospacedDigit()
                    .foregroundStyle(skin.palette.warning)
                    .fixedSize(horizontal: true, vertical: false)
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

/// D1 editorial cover composition — serif name 左上 + hairline rule + N 詞 右下 + (active) spine。
/// 以 `.overlay` 套在既有 cover view 之上,跟著 `coverArea.rotationEffect` 一起旋轉。
/// Spine 走 `NotebookPalette.darken(coverColor, by: 0.4)` (HSB brightness ×0.6,同色族加深)。
/// Rule 走 `NotebookPalette.darken(coverColor, by: 0.3)`(brightness ×0.7),寬度 = cover 寬 × 0.25 (GeometryReader)。
private struct EditorialCoverComposition: View {
    let name: String
    let cardCount: Int
    let coverColor: Color
    let isActive: Bool
    let style: NotebookCardStyle
    @Environment(\.appSkin) private var skin

    private var nameFont: Font {
        switch style {
        case .grid: return AppFonts.serif(size: 22, bold: true)
        case .hero: return AppFonts.serif(size: 32, bold: true)
        }
    }

    private var outerPadding: CGFloat {
        switch style {
        case .grid: return AppSpacing.s3
        case .hero: return AppSpacing.s4
        }
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // D3 spine — grid only,isActive。3pt < layerInsetX(4pt) 視覺與 ghost 邊不融合。
            if style == .grid && isActive {
                HStack(spacing: 0) {
                    Rectangle()
                        .fill(NotebookPalette.darken(coverColor, by: 0.4))
                        .frame(width: 3)
                        .accessibilityHidden(true)
                    Spacer(minLength: 0)
                }
            }

            // Name + rule (top-leading)
            GeometryReader { geo in
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(name)
                        .font(nameFont)
                        .foregroundStyle(skin.palette.primaryText)
                        .lineLimit(2)
                        .truncationMode(.tail)

                    Rectangle()
                        .fill(NotebookPalette.darken(coverColor, by: 0.3))
                        .frame(width: geo.size.width * 0.25,
                               height: AppMetrics.dividerStandard)
                }
                .padding(outerPadding)
            }

            // N 詞 (bottom-trailing,僅 cardCount > 0)
            if cardCount > 0 {
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Text(L10n.format("%@ 詞", "\(cardCount)"))
                            .font(skin.typography.monoLabel)
                            .monospacedDigit()
                            .foregroundStyle(skin.palette.secondaryText)
                    }
                }
                .padding(outerPadding)
            }
        }
    }
}

/// Editorial 空 slot — 1pt 實線 hairline + cream paperLight 背景 + 36pt soft ring plus icon。
/// 與 cream ghost stack 共用視覺語言。**不旋轉**（empty slot 語意 = 等待填入，不該有手痕）、
/// **不加 shadow**（empty 不浮起）。
struct NotebookAddCard: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var skin

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            // Plus icon 包在 36pt soft ring — 將 naked glyph 轉成「等待點擊的目標」
            Image(systemName: "plus")
                .font(.system(size: 18, weight: .regular))
                .foregroundStyle(skin.palette.tertiaryText)
                .frame(width: 36, height: 36)
                .overlay(
                    Circle().strokeBorder(skin.palette.cardBorder, lineWidth: 1)
                )

            Text("新增單字本".localized)
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.tertiaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // 與 NotebookCard(.grid) 同 aspect — 修奇數本 / 偶數本 add 卡破節奏
        .aspectRatio(LayoutMode.notebookCardAspectRatio, contentMode: .fit)
        // Editorial cream — 與 ghost 紙頁同視覺族群（不再 cardBackground 純白）
        .background(AppColors.paperLight)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            // 1pt 實線 hairline 取代 1.5pt dashed — 移除「資料夾選擇器」感
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .strokeBorder(skin.palette.cardBorder, lineWidth: 1)
        )
        .enableInjection()
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
