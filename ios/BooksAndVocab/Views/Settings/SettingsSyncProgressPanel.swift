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
    @Environment(\.appSkin) private var appSkin

    let steps: [PipelineStep]
    let fraction: Double

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
        .accessibilityIdentifier("settings.syncProgress.bar")
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
                .frame(width: appSkin.spacing.sectionGap, alignment: .center)

            Text(step.label)
                .font(appSkin.typography.caption)
                .foregroundStyle(step.status == .waiting
                    ? appSkin.palette.tertiaryText
                    : appSkin.palette.primaryText)
                .lineLimit(1)

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
    }
}
