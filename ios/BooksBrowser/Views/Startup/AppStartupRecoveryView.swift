import SwiftUI

struct AppStartupFailure: Equatable {
    let title: String
    let message: String
    let recoverySteps: [String]
    let technicalDetails: String

    static func storageInitialization(error: Error) -> AppStartupFailure {
        AppStartupFailure(
            title: L10n.string("無法安全啟動資料庫"),
            message: L10n.string("App 已停止載入主要功能，避免在資料庫異常時覆寫或刪除既有資料。"),
            recoverySteps: [
                L10n.string("先重新啟動 App，確認是不是一次性的 migration 或 iCloud 初始化失敗。"),
                L10n.string("如果問題持續，保留裝置上的 App 資料並匯出診斷資訊，不要直接刪除 App。"),
                L10n.string("修正模型或 migration 問題後，再用新版本重新開啟 App。")
            ],
            technicalDetails: error.localizedDescription
        )
    }
}

struct AppStartupRecoveryView: View {
    @Environment(\.appTheme) private var appTheme

    let failure: AppStartupFailure

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(failure.title, systemImage: "externaldrive.badge.exclamationmark")
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(appTheme.palette.primaryText)

                        Text(failure.message)
                            .font(.body)
                            .foregroundStyle(appTheme.palette.secondaryText)
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text(L10n.string("建議處理方式"))
                            .font(.headline)
                            .foregroundStyle(appTheme.palette.primaryText)

                        ForEach(Array(failure.recoverySteps.enumerated()), id: \.offset) { index, step in
                            HStack(alignment: .top, spacing: 12) {
                                Text("\(index + 1).")
                                    .font(.body.monospacedDigit())
                                    .foregroundStyle(appTheme.palette.accent)
                                Text(step)
                                    .font(.body)
                                    .foregroundStyle(appTheme.palette.secondaryText)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text(L10n.string("技術細節"))
                            .font(.headline)
                            .foregroundStyle(appTheme.palette.primaryText)

                        Text(failure.technicalDetails)
                            .font(.footnote.monospaced())
                            .foregroundStyle(appTheme.palette.tertiaryText)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(16)
                            .background(appTheme.palette.cardBackground, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                            .overlay {
                                RoundedRectangle(cornerRadius: 18, style: .continuous)
                                    .stroke(appTheme.palette.cardBorder, lineWidth: 1)
                            }
                    }
                }
                .padding(24)
            }
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle(L10n.string("啟動保護模式"))
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
