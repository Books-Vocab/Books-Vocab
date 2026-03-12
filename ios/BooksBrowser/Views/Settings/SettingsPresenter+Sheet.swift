import SwiftUI

// MARK: - Sheet Views

struct OptionalIntegrationInfoSheetView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    private let setupSteps: [(icon: String, text: String)] = [
        ("1.circle.fill", "登入網頁版的 app.mochi.cards".localized),
        ("2.circle.fill", "點擊右上角設定 (Settings)".localized),
        ("3.circle.fill", "選擇 API 分頁".localized),
        ("4.circle.fill", "點擊 Generate API key 並複製貼上到前面設定中".localized)
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)
                        .padding(.bottom, vocabSkin.spacing.inlineGap)

                    Text("關於 Mochi 整合（Legacy）".localized)
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text("如果你仍在使用 Mochi (mochi.cards)，Books & Vocab 可以把你查過並儲存的單字同步過去。這屬於可選的第三方整合，Books & Vocab 本身的雲端同步與複習功能不依賴 Mochi。這個 API Key 會綁定在你的帳號設定，不是伺服器全域設定。".localized)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                        SettingsSectionHeader(title: "如何取得 API Key？".localized, icon: "key")

                        SettingsFeaturePanel(borderTone: vocabSkin.palette.cardBorder) {
                            VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                                ForEach(Array(setupSteps.enumerated()), id: \.offset) { index, step in
                                    Label(step.text, systemImage: step.icon)
                                        .font(vocabSkin.typography.body)
                                        .foregroundStyle(vocabSkin.palette.secondaryText)

                                    if index < setupSteps.count - 1 {
                                        SettingsDivider()
                                    }
                                }
                            }
                        }
                    }

                    VocabStateMessageCard(
                        title: "這是保留給既有使用者的可選整合".localized,
                        systemImage: "info.circle",
                        description: "不填寫 API Key 也不影響 Books & Vocab 的主要功能。".localized
                    )
                }
                .padding(vocabSkin.spacing.sheetPadding)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                }
            }
        }
    }
}

#Preview("Optional Integration Info") {
    AppThemeContainer {
        OptionalIntegrationInfoSheetView()
    }
}
