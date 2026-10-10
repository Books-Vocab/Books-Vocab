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

// MARK: - Accessibility（#2432）

extension PipelineStep.StepStatus {
    /// VoiceOver 用的狀態字串。六態各自獨立：retry 與 running 在畫面上是
    /// 不同符號，念出來也不能是同一句。`language` 僅供確定性測試，
    /// 正式呼叫走目前 app 語言。
    func accessibilityValue(language: AppLanguage? = nil) -> String {
        func lookup(_ key: String) -> String {
            language.map { L10n.string(key, language: $0) } ?? L10n.string(key)
        }
        switch self {
        case .waiting: return lookup("等待中")
        case .running: return lookup("進行中")
        case .retry:   return lookup("重試中")
        case .done:    return lookup("已完成")
        case .skipped: return lookup("已略過")
        case .error:   return lookup("失敗")
        }
    }
}

extension PipelineStep {
    /// 整列念成「步驟名（label），狀態，進度或細節（value）」；
    /// 詞庫頁與設定頁共用，避免兩處念法漂移。
    func accessibilityValue(language: AppLanguage? = nil) -> String {
        let state = status.accessibilityValue(language: language)
        if status == .running && total > 0 {
            return "\(state)，\(current)/\(total)"
        }
        // waiting 列畫面上不顯示 detail（SyncPresenter／設定頁皆隱藏），念出來也不該有。
        return (detail.isEmpty || status == .waiting) ? state : "\(state)，\(detail)"
    }

    /// 整列的 VoiceOver (label, value)；詞庫頁 stepRow 直接套用，測試也斷言這一組。
    /// label 經 L10n，對已本地化字串冪等。
    func accessibilitySummary(language: AppLanguage? = nil) -> (label: String, value: String) {
        let localizedLabel = language.map { L10n.string(label, language: $0) } ?? L10n.string(label)
        return (localizedLabel, accessibilityValue(language: language))
    }
}
