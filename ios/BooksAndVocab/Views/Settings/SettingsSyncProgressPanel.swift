//
//  SettingsSyncProgressPanel.swift
//  Books & Vocab
//
//  同步進行中，「同步狀態」那一列底下展開的逐步清單 + 總進度條。
//
//  **獨立 View struct，不得內聯回 `SettingsOtherSection`。** 那個檔案的檔頭記載
//  它自己被抽出來的原因：iOS 主執行緒 stack 只有 1MB，Debug -Onone 下 SwiftUI 的
//  巨型泛型 frame 不會被優化掉，整棵樹內聯進單一 body 會 stack overflow
//  （EXC_BAD_ACCESS code=2，取證 dump 2026-06-11）。Simulator 主執行緒是 8MB，
//  永遠測不出這條——不要因為 sim 沒事就把它收回去。同理，底下的進度條與單列
//  也各自是 struct，不是 `@ViewBuilder` property。
//

import SwiftUI

struct SettingsSyncProgressPanel: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let steps: [PipelineStep]
    let fraction: Double

    /// The panel is mounted only after the coordinator has announced that a
    /// round is syncing *and* the store has declared its step identity. Both
    /// inputs belong to the visibility phase; observing only `isSyncing` lets
    /// the first render miss the insertion transition when `begin` arrives on
    /// the next observation pass.
    static func isVisible(isSyncing: Bool, steps: [PipelineStep]) -> Bool {
        isSyncing && !steps.isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
            SettingsSyncProgressBar(fraction: fraction)

            VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
                ForEach(steps) { step in
                    SettingsSyncStepRow(step: step)
                }
            }
        }
        .padding(.horizontal, appSkin.spacing.cardPadding)
        .padding(.bottom, appSkin.spacing.tinyGap)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.syncProgress")
        .enableInjection()
    }
}

/// 總進度條。形狀刻意照抄同 section 的 `quotaRow`（兩層 pill `AppRoundedRect`、
/// 高度 3）——設定頁只該有一種進度條長相，不為了「這是不同的進度」再發明一種。
private struct SettingsSyncProgressBar: View {
    @Environment(\.appSkin) private var appSkin

    let fraction: Double

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                AppRoundedRect(roundness: AppRoundness.pill)
                    .fill(appSkin.palette.accent.opacity(0.15))

                AppRoundedRect(roundness: AppRoundness.pill)
                    .fill(appSkin.palette.accent)
                    .frame(width: geo.size.width * min(max(fraction, 0), 1))
                    .animateSpring(fraction)
            }
        }
        .frame(height: 3)
        // `accessibilityElement()` 是必要的：GeometryReader 裡只有 Shape，沒有任何
        // 可及性元素可以掛 value——少了這行，下面兩個修飾子等於寫在空氣上。
        .accessibilityElement()
        .accessibilityIdentifier("settings.syncProgress.bar")
        .accessibilityLabel(Text(L10n.string("同步進度")))
        .accessibilityValue(Text(verbatim: "\(Int(fraction * 100))%"))
    }
}

/// 逐步清單的一列。狀態符號走共用的 `SyncStepStatusIcon`（與詞庫頁那條同步管線
/// 同一組視覺語言）；計數器用 `.numericText()` + `feedbackPulse`，與 `SyncPresenter`
/// 的做法一致——那是 `ui-design.md` 指名給「數字跳動」的 token。
private struct SettingsSyncStepRow: View {
    @Environment(\.appSkin) private var appSkin

    let step: PipelineStep

    var body: some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            SyncStepStatusIcon(status: step.status)
                .font(appSkin.typography.caption)
                // 固定欄寬讓六種符號（含寬度不一的 ProgressView）對齊同一條軸線。
                // 用 metrics 而不是 spacing token：這是尺寸不是間距。
                .frame(width: appSkin.metrics.statusIconColumn, alignment: .center)

            Text(step.label)
                .font(appSkin.typography.caption)
                .foregroundStyle(step.status == .waiting
                    ? appSkin.palette.tertiaryText
                    : appSkin.palette.primaryText)
                .lineLimit(1)
                // 長 detail（例如「此伺服器尚未提供字典卡」）會把步驟名稱擠掉，
                // 而名稱是這一列的主詞——先截 detail，別截它。
                .layoutPriority(1)

            Spacer(minLength: appSkin.spacing.inlineGap)

            if step.status == .running && step.total > 0 {
                Text(verbatim: "\(step.current)/\(step.total)")
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .contentTransition(.numericText())
                    .animation(AppMotion.feedbackPulse, value: step.current)
            } else if !step.detail.isEmpty, step.status != .waiting {
                Text(step.detail)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(step.status.detailColor(appSkin))
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
        .animation(AppMotion.phaseChange, value: step.status)
        // 六態目前只靠符號的形狀與顏色傳達——對 VoiceOver 使用者那等於什麼都沒說。
        // combine 讓整列念成一句「步驟名，狀態，細節」。
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text(step.label))
        .accessibilityValue(Text(accessibilityValue))
    }

    private var accessibilityValue: String {
        let state: String
        switch step.status {
        case .waiting:  state = L10n.string("等待中")
        case .running, .retry: state = L10n.string("進行中")
        case .done:     state = L10n.string("已完成")
        case .skipped:  state = L10n.string("已略過")
        case .error:    state = L10n.string("失敗")
        }
        if step.status == .running && step.total > 0 {
            return "\(state)，\(step.current)/\(step.total)"
        }
        return step.detail.isEmpty ? state : "\(state)，\(step.detail)"
    }
}

#if DEBUG
#Preview("同步中 / 逐步進度") {
    // catalog 凍結期（`docs/reference/catalog_scope.md` §FROZEN）不新增 catalog
    // surface，`#Preview` 是規定的替代品：要看畫面就在 Xcode 開這個。
    SettingsSyncProgressPanel(
        steps: [
            PipelineStep(id: "push", label: "送出複習紀錄", status: .done,
                         detail: "已送出 12 筆", weight: 1),
            PipelineStep(id: "pull", label: "下載單字卡", status: .running,
                         current: 340, total: 960, weight: 4),
            PipelineStep(id: "dictionary", label: "下載字典卡", status: .skipped,
                         detail: "此伺服器尚未提供字典卡", weight: 2),
            PipelineStep(id: "reviewEvents", label: "下載複習紀錄", status: .error,
                         detail: "未知錯誤", weight: 1),
            PipelineStep(id: "podcast", label: "更新 Podcast 目錄", weight: 2),
            PipelineStep(id: "status", label: "額度與連線", weight: 1)
        ],
        fraction: 0.45
    )
    .padding()
}
#endif
