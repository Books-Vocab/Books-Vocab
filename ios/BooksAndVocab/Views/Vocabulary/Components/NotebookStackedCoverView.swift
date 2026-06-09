//
//  NotebookStackedCoverView.swift
//  Books & Vocab
//
//  Editorial 立體堆卡 — 彩色封面 + cream 紙頁內頁的 notebook 隱喻。
//  下層 ghost 用 `AppColors.paperLight/Sepia/SepiaDeep` 三階 cream 紙頁，
//  每層套 deterministic 微 rotation + edge jitter（per-notebook seed），
//  與全層 hairline border 共同帶入「桌上隨手疊」的 editorial 手感。
//
//  本檔只負責「視覺堆疊」；metadata、使用中 pill、context menu、整體 rotation
//  （含 pill 隨轉）由外層 `NotebookCard` 持有。
//

import SwiftUI

// MARK: - Stacked cover view

struct NotebookStackedCoverView: View {
    @ObserveInjection private var inject
    let color: Color
    let pattern: NotebookCoverPattern?
    let coverImagePath: String?
    let name: String
    /// 1 / 2 / 3 / 4 — 由 `NotebookStackMetrics.layerCount(forCardCount:)` 決定
    let layerCount: Int
    let aspectRatio: CGFloat
    /// Per-notebook deterministic seed（由 `NotebookCard` 傳 `data.name.hashValue` 等）。
    /// 同 seed × 同 depth 永遠回傳同一 (angle, dx)；render 不會閃爍。
    /// 預設 0 為了 Phase 3 build 自包：Phase 4 wire 後實際每張卡會傳不同 seed。
    var seed: Int = 0
    /// 是否在頂層 cover 中央渲染白色 name(透傳至內層 `NotebookCoverView`)。
    /// 預設 true 保留既有行為;NotebookCard 套 editorial overlay 時傳 false。
    var showsName: Bool = true

    @Environment(\.appSkin) private var skin
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        // ghost 數 = layerCount - 1（頂層另外處理）
        let ghostDepths = Array((1..<max(layerCount, 1)).reversed())  // e.g. [3,2,1]
        // 預留底部空間給最深 ghost 的 peek，避免 peek 蓋到 metadata 區
        let maxGhostDy = NotebookStackMetrics.layerOffsetY * CGFloat(max(layerCount - 1, 0))

        ZStack(alignment: .top) {
            // ── 下層 ghost：由深到淺由下而上 render ──
            ForEach(ghostDepths, id: \.self) { depth in
                ghostLayer(depth: depth)
            }

            // ── 頂層 L0：實體封面 ──
            // 只圓上半 — 與下方 metadata 黏合，避免「兩塊獨立物件」感
            NotebookCoverView(
                color: color,
                pattern: pattern,
                coverImagePath: coverImagePath,
                name: name,
                showsName: showsName
            )
            .clipShape(UnevenRoundedRectangle(
                topLeadingRadius: AppRadius.md,
                bottomLeadingRadius: 0,
                bottomTrailingRadius: 0,
                topTrailingRadius: AppRadius.md,
                style: .continuous
            ))
            // Editorial hairline — 與 ghost 同 hairline 語言，撞 cream 背景時邊界不糊
            .overlay(
                UnevenRoundedRectangle(
                    topLeadingRadius: AppRadius.md,
                    bottomLeadingRadius: 0,
                    bottomTrailingRadius: 0,
                    topTrailingRadius: AppRadius.md,
                    style: .continuous
                )
                .stroke(skin.palette.cardBorder, lineWidth: AppMetrics.dividerThin)
            )
            .appElevation(.z2)
            // ⚠️ Top cover 不在這裡套 rotation —
            // rotation 在 `NotebookCard.coverArea` 外層套，包 pill overlay 一起轉
            // （避免 pill 脫離卡片邊界）。
        }
        // ⚠️ aspectRatio 必須套在 ZStack 而非個別 layer —
        // 套在 layer 上會被 .padding(.horizontal, dx) 反向壓縮高度，
        // 使 ghost 底邊比 top 底邊還高，peek 永遠不會出現。
        .aspectRatio(aspectRatio, contentMode: .fit)
        // 為 ghost peek + rotation overhang 預留空間
        .padding(.bottom, maxGhostDy + NotebookStackMetrics.rotationOverhang)
        .padding(.horizontal, NotebookStackMetrics.rotationOverhang)
        .enableInjection()
    }

    /// Cream 紙頁 ghost 一層 — 不 render pattern / image / text，避免下層雜訊。
    /// 不套自己的 aspectRatio：交由父 ZStack 的 aspectRatio 統一決定 frame。
    @ViewBuilder
    private func ghostLayer(depth: Int) -> some View {
        let baseInset = NotebookStackMetrics.layerInsetX * CGFloat(depth)
        let baseDy = NotebookStackMetrics.layerOffsetY * CGFloat(depth)
        let jitter = NotebookStackMetrics.seedJitter(seed: seed, depth: depth)

        RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
            .fill(NotebookStackMetrics.ghostPaperColor(depth: depth, scheme: colorScheme))
            // Editorial hairline — cream-on-cream 無邊讀不出層次
            .overlay(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .stroke(skin.palette.cardBorder, lineWidth: AppMetrics.dividerThin)
            )
            .padding(.horizontal, baseInset + jitter.dx)
            .offset(y: baseDy)
            // 從 .bottom 錨點旋轉：底部錨定、頂部微張，模擬桌上隨手疊
            .rotationEffect(.degrees(jitter.angle), anchor: .bottom)
            .appElevation(.z1)
            .accessibilityHidden(true)
    }
}

#Preview("NotebookStackedCoverView") {
    AppThemeContainer {
        HStack(alignment: .top, spacing: AppSpacing.s4) {
            ForEach([1, 2, 4], id: \.self) { layers in
                NotebookStackedCoverView(
                    color: AppColors.accentLight,
                    pattern: .dots,
                    coverImagePath: nil,
                    name: "Field Notes",
                    layerCount: layers,
                    aspectRatio: 0.72,
                    seed: layers * 7,
                    showsName: true
                )
                .frame(width: 96)
            }
        }
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
