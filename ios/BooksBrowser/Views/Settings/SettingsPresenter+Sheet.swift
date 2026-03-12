import SwiftUI

// MARK: - Sheet Views

struct OptionalIntegrationInfoSheetView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

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

                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)

                    Text("如何取得 API Key？".localized)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                        Label("1. 登入網頁版的 app.mochi.cards".localized, systemImage: "1.circle.fill")
                        Label("2. 點擊右上角設定 (Settings)".localized, systemImage: "2.circle.fill")
                        Label("3. 選擇 API 分頁".localized, systemImage: "3.circle.fill")
                        Label("4. 點擊 Generate API key 並複製貼上到前面設定中".localized, systemImage: "4.circle.fill")
                    }
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)

                    Text("這是保留給既有使用者的可選整合，不填寫 API Key 也不影響 Books & Vocab 的主要功能。".localized)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                        .padding(.top, vocabSkin.spacing.actionButtonHorizontalPadding)
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
