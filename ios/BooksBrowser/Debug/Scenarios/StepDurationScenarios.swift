#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

// Catalog scenarios for StepDurationView — the small timing label rendered next
// to each sync pipeline step. The view only draws when `startTime` is set:
// - completed steps (start + end) show a fixed "%.1fs" elapsed string
// - in-flight steps (start, no end) show a live-ticking duration, tinted
//   secondary normally and `palette.retry` while retrying
// PipelineStep / StepStatus are internal value types, so all fixtures are
// synthesized here with no production seam.

enum StepDurationScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Sync Step Duration") {
            Scenario("Completed · 短", layout: .fill) {
                StepDurationCatalogScene(
                    title: "完成步驟 · 2.6s",
                    step: PipelineStep(
                        id: "upload_add",
                        label: "上傳新單字",
                        status: .done,
                        current: 12,
                        total: 12,
                        detail: "10 新增, 2 已存在",
                        startTime: Date().addingTimeInterval(-9),
                        endTime: Date().addingTimeInterval(-6.4)
                    )
                )
            }

            Scenario("Completed · 長", layout: .fill) {
                StepDurationCatalogScene(
                    title: "完成步驟 · 長耗時",
                    step: PipelineStep(
                        id: "pull",
                        label: "下載單字至本地",
                        status: .done,
                        current: 1,
                        total: 1,
                        detail: "本地單字已建立完成",
                        startTime: Date().addingTimeInterval(-128.7),
                        endTime: Date()
                    )
                )
            }

            Scenario("Running · 即時計時", layout: .fill) {
                StepDurationCatalogScene(
                    title: "執行中 · 即時遞增",
                    step: PipelineStep(
                        id: "trigger",
                        label: "觸發背景 AI 處理",
                        status: .running,
                        current: 1,
                        total: 1,
                        detail: "背景管線執行中",
                        startTime: Date().addingTimeInterval(-2.2),
                        endTime: nil
                    )
                )
            }

            Scenario("Retry · 重試色", layout: .fill) {
                StepDurationCatalogScene(
                    title: "重試中 · retry 色",
                    step: PipelineStep(
                        id: "upload_delete",
                        label: "刪除 KG 單字",
                        status: .retry,
                        current: 1,
                        total: 2,
                        detail: "重試: obscure",
                        startTime: Date().addingTimeInterval(-5.4),
                        endTime: nil
                    )
                )
            }

            Scenario("Waiting · 不渲染", layout: .fill) {
                StepDurationCatalogScene(
                    title: "等待中 · 無計時(空)",
                    step: PipelineStep(
                        id: "pull_waiting",
                        label: "下載單字至本地",
                        status: .waiting,
                        current: 0,
                        total: 0,
                        detail: "",
                        startTime: nil,
                        endTime: nil
                    )
                )
            }
        }
    }
}

// MARK: - Catalog Scene

private struct StepDurationCatalogScene: View {
    let title: String
    let step: PipelineStep

    var body: some View {
        AppThemeContainer {
            VStack(alignment: .leading, spacing: 16) {
                Text(title)

                HStack(spacing: 12) {
                    Text(step.label)
                    Spacer(minLength: 24)
                    StepDurationView(step: step)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
                .frame(maxWidth: .infinity)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
