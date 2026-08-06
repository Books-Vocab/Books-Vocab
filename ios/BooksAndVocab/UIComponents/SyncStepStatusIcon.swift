//
//  SyncStepStatusIcon.swift
//  Books & Vocab
//
//  `PipelineStep.StepStatus` 的六態符號。
//
//  抽成共用元件是因為現在有兩個消費者：詞庫頁的獨立同步畫面（`SyncPresenter`）
//  與設定頁的逐步同步進度。同一個狀態在兩處長得不一樣，是使用者學兩次的成本；
//  而複製一份 switch 過去，則是下次加狀態時漏改一處的成本。
//

import SwiftUI

struct SyncStepStatusIcon: View {
    @Environment(\.appSkin) private var appSkin

    let status: PipelineStep.StepStatus

    var body: some View {
        switch status {
        case .waiting:
            Image(systemName: "circle")
                .foregroundStyle(appSkin.palette.quaternaryText)
        case .running:
            ProgressView()
                .controlSize(.small)
        case .retry:
            Image(systemName: "arrow.triangle.2.circlepath")
                .symbolEffect(.scale.up, options: .repeating)
                .foregroundStyle(appSkin.palette.retry)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(appSkin.palette.success)
                .symbolEffect(.bounce, value: true)
        case .skipped:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(appSkin.palette.secondaryText)
        case .error:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(appSkin.palette.destructive)
        }
    }
}

extension PipelineStep.StepStatus {
    /// 這個狀態下 detail 文字該用什麼色。與符號同一組語意，放在一起免得漂移。
    func detailColor(_ appSkin: AppSkin) -> Color {
        switch self {
        case .error:  return appSkin.palette.destructive
        case .retry:  return appSkin.palette.retry
        default:      return appSkin.palette.secondaryText
        }
    }
}
