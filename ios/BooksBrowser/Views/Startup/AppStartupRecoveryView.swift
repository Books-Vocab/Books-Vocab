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
                VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                    VStack(alignment: .leading, spacing: AppMetrics.spacingCompact) {
                        Label(failure.title, systemImage: "externaldrive.badge.exclamationmark")
                            .font(AppFonts.h2(weight: .semibold))
                            .foregroundStyle(appTheme.palette.primaryText)

                        Text(failure.message)
                            .font(AppFonts.body())
                            .foregroundStyle(appTheme.palette.secondaryText)
                    }

                    VStack(alignment: .leading, spacing: AppMetrics.spacingCompact) {
                        Text(L10n.string("建議處理方式"))
                            .font(AppFonts.subhead(weight: .semibold))
                            .foregroundStyle(appTheme.palette.primaryText)

                        ForEach(Array(failure.recoverySteps.enumerated()), id: \.offset) { index, step in
                            HStack(alignment: .top, spacing: AppMetrics.spacingCompact) {
                                Text("\(index + 1).")
                                    .font(AppFonts.monoNumbers(size: 17))
                                    .foregroundStyle(appTheme.palette.accent)
                                Text(step)
                                    .font(AppFonts.body())
                                    .foregroundStyle(appTheme.palette.secondaryText)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                        Text(L10n.string("技術細節"))
                            .font(AppFonts.subhead(weight: .semibold))
                            .foregroundStyle(appTheme.palette.primaryText)

                        Text(failure.technicalDetails)
                            .font(AppFonts.monoNumbers(size: 12))
                            .foregroundStyle(appTheme.palette.tertiaryText)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(AppMetrics.spacingMedium)
                            .background(appTheme.palette.cardBackground, in: RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusXLarge, style: .continuous))
                            .overlay {
                                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusXLarge, style: .continuous)
                                    .stroke(appTheme.palette.cardBorder, lineWidth: 1)
                            }
                    }
                }
                .padding(AppMetrics.spacingLarge)
            }
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle(L10n.string("啟動保護模式"))
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
