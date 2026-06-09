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
    var cardCountLabel: String = "個單字".localized
    let dueCount: Int
    let unlearnedCount: Int
    let reviewedCount: Int
    let pendingCount: Int
    let lastActivity: Date?
    let isActive: Bool

    /// 封面黃點數字 = 需使用者動作的卡（到期複習 + 未學新卡），
    /// 與「今日複習」入口徽章（`dueCount + unlearnedCount`）同口徑，
    /// 避免封面 587 與今日複習 597 兩數字不一致造成困惑。
    var actionableCount: Int { dueCount + unlearnedCount }
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
        // 走 `NotebookPalette.darken(_, by: 0.55)` 而非 `.brightness(-0.55)` —
        // HSB scale 跟 contrast test 的計算完全對齊(避免 sRGB additive vs HSB scale 分歧)。
        return colorScheme == .dark ? NotebookPalette.darken(raw, by: 0.55) : raw
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
        // Editorial book row — cover (~40% 寬,承載 serif name + active dot) + metadata。
        GeometryReader { geo in
            let coverWidth = geo.size.width * 0.4
            let isEmpty = data.cardCount == 0

            HStack(spacing: 0) {
                // ── 左:cover block ──
                ZStack(alignment: .topLeading) {
                    coverColor

                    // 統一 noise pattern — 所有 cover 都帶極淡紙感(opacity 0.04)
                    NotebookCoverPattern.noise.patternOverlay(size: CGSize(width: coverWidth, height: 72))
                        .opacity(0.04)
                        .clipped()
                        .allowsHitTesting(false)

                    if let pattern {
                        pattern.patternOverlay(size: CGSize(width: coverWidth, height: 72))
                            .clipped()
                    }

                    VStack(alignment: .leading, spacing: AppSpacing.s1) {
                        HStack(spacing: AppSpacing.s1) {
                            if data.isActive {
                                Circle()
                                    .fill(NotebookPalette.darken(coverColor, by: 0.5))
                                    .frame(width: 5, height: 5)
                            }
                            Text(data.name)
                                .font(AppFonts.serif(size: 17, bold: true).italic())
                                .foregroundStyle(skin.palette.primaryText)
                                .lineLimit(2)
                                .truncationMode(.tail)
                        }

                        // Editorial rule — 1pt,顯著 darken 0.5
                        Rectangle()
                            .fill(NotebookPalette.darken(coverColor, by: 0.5))
                            .frame(width: coverWidth * 0.3, height: 1)
                    }
                    .padding(.horizontal, AppSpacing.s3)
                    .padding(.vertical, AppSpacing.s2)
                }
                .frame(width: coverWidth)
                .overlay(alignment: .trailing) {
                    Rectangle()
                        .fill(skin.palette.cardBorder)
                        .frame(width: 0.5)
                }

                // ── 右:metadata 區 ──
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    if isEmpty {
                        // 空 notebook 視覺特例 — 不顯示 0% 進度條,改 placeholder 字
                        Text("尚未加入單字".localized)
                            .font(skin.typography.caption)
                            .foregroundStyle(skin.palette.tertiaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        HStack(alignment: .firstTextBaseline) {
                            Text(L10n.format("%@ 詞", "\(data.cardCount)"))
                                .font(skin.typography.monoLabel)
                                .monospacedDigit()
                                .foregroundStyle(skin.palette.secondaryText)

                            Spacer(minLength: AppSpacing.s2)

                            if data.actionableCount > 0 {
                                HStack(spacing: AppSpacing.microGap) {
                                    Circle()
                                        .fill(skin.palette.warning)
                                        .frame(width: 5, height: 5)
                                    Text("\(data.actionableCount)")
                                        .font(skin.typography.caption)
                                        .monospacedDigit()
                                        .foregroundStyle(skin.palette.secondaryText)
                                }
                                .fixedSize(horizontal: true, vertical: false)
                            }
                        }

                        ProgressCapsule(
                            progress: reviewProgress,
                            label: nil,
                            fillColor: coverColor,
                            trackColor: skin.palette.progressBarBackground,
                            height: 4
                        )
                    }
                }
                .padding(.horizontal, AppSpacing.s3)
                .padding(.vertical, AppSpacing.s3)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(height: 72)
        .background(skin.palette.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        // 北極星二:list card 預設無 border。視覺分區改靠卡片間留白
        // (editorialGridSpacing)+ cover↔metadata 內部垂直 0.5pt rule(書背隱喻,保留)。
        // 卡片底色 `cardBackground` 與 `pageBackground` 不同色,單色頁面仍可區分。
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
        .appHoverLift()
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
    ///
    /// **Stable-height guarantee**: HStack 永遠由 invisible placeholder chip 撐高,
    /// 確保 grid 中 dueCount=0 / >0 兩本卡片高度一致(原 opacity=0 占位策略延續)。
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
            } else {
                // Invisible placeholder — 同 font 撐高,grid 兩卡 height 一致
                Label("0", systemImage: "clock.badge")
                    .font(skin.typography.monoLabel)
                    .monospacedDigit()
                    .opacity(0)
                    .accessibilityHidden(true)
                    .fixedSize(horizontal: true, vertical: false)
            }
        }
    }

    private var accessibilityDescription: String {
        var parts = [data.name, "\(data.cardCount) \(data.cardCountLabel)"]
        if data.dueCount > 0 { parts.append(L10n.format("%d 到期", data.dueCount)) }
        if data.unlearnedCount > 0 { parts.append(L10n.format("%d 未學", data.unlearnedCount)) }
        if data.isActive { parts.append("使用中".localized) }
        return parts.joined(separator: "，".localized)
    }
}

/// D1 editorial cover composition — serif name 左上 + hairline rule + N 詞 右下 + (active) spine。
/// 以 `.overlay` 套在既有 cover view 之上,跟著 `coverArea.rotationEffect` 一起旋轉。
/// Spine 走 `NotebookPalette.darken(coverColor, by: 0.4)` (HSB brightness ×0.6,同色族加深)。
/// Rule 走 `NotebookPalette.darken(coverColor, by: 0.3)`(brightness ×0.7),寬度 = cover 寬 × 0.25 (GeometryReader)。
struct EditorialCoverComposition: View {
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
        case .grid: return AppSpacing.s2  // 8pt — editorial 緊版 (was s3 12pt)
        case .hero: return AppSpacing.s3  // 12pt (was s4 16pt)
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
