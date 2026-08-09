import SwiftUI

/// 版面設定頁的即時預覽（APP-20260808-d4a707）。
///
/// **它不是「長得像卡片的東西」，它就是卡片**：內部唯一畫東西的是
/// `ReviewCardView` —— 出貨複習卡的同一個 view（IMP-20260808-ee7ca4 從
/// `TodayReviewPresenter` 抽出的純輸入版本）。「像素級不飄移」靠的是這個結構
/// 事實，不是靠紀律：這裡**不得**出現第二份手刻的卡片版面，否則本型別存在的
/// 理由就沒了。
///
/// 姿態固定是「翻開的樣子」（`showsAnswer: true` + `mountsBack: true`），
/// 因為使用者要看的正是翻開後兩面各有什麼。`interactive: false` 讓它不吃手勢、
/// 不搶 `todayReview.card.front` 這個 a11y 契約。`measuresSections: true` 才會
/// 跑與真卡同一組隱藏量測 probe，精簡階梯（例句 radius／解釋行數／搭配詞列數）
/// 才會逐像素一致。
///
/// 頂層 struct、不 inline 進 editor 的 body：Debug `-Onone` 下主執行緒 1MB
/// stack 會被 inline 的 section tree 撐爆（見 `SettingsPresenter.swift` 檔頭）。
struct ReviewCardLayoutPreviewCard: View {
    @ObserveInjection private var inject

    let currentCard: TodayReviewPresenterState.CurrentCard
    let profile: ReviewCardLayoutProfile

    /// 預覽容器高度。給 `ReviewCardViewport` 一個明確的預算 —— 卡片自己決定
    /// 實際高度，這裡只界定它有多少空間可用（不可用 `.frame(height:)` 夾卡片，
    /// 夾了就回到「畫面高度 ≠ solver 記帳高度」那一族缺陷）。
    static let viewportHeight: CGFloat = 420

    var body: some View {
        GeometryReader { proxy in
            ReviewCardView(
                content: currentCard,
                profile: profile,
                viewport: ReviewCardViewport(containerHeight: proxy.size.height),
                showsAnswer: true,
                mountsBack: true,
                interactive: false,
                measuresSections: true,
                actions: .none
            )
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .frame(height: Self.viewportHeight)
        .enableInjection()
    }
}

// MARK: - 內建範例卡

extension ReviewCardLayoutPreviewCard {
    /// 從設定頁進來時沒有「當前那張卡」，用這張程式內常數。
    ///
    /// **絕不可改用 `TodayReviewFixtures` / `TodayReviewPresenterPreviewData`**：
    /// 它們走 `FixtureDatasetStore`，只認 `KG_FIXTURE_DATASET_*` 環境變數，正式
    /// App 兩者皆無 → `requireTodayReviewSeed` 會 `preconditionFailure` 當場崩。
    ///
    /// 六個可選欄位**全部備齊**（詞性 / 難度 / 例句 / 解釋 / 搭配 / 圖譜連結）：
    /// `ReviewCardContentAvailability.forReviewCard` 會濾掉缺席的欄位，缺一個
    /// 就會讓使用者切換 preset 時預覽紋風不動，看起來像壞掉。
    static func sampleCard(for mode: VocabularyCardMode) -> TodayReviewPresenterState.CurrentCard {
        let entry = VocabularyEntry(
            word: "serendipity",
            translation: L10n.string("reviewCardLayout.sample.translation"),
            // i18n-allow: 例句與原文語境是英文學習素材本身，不隨介面語言翻譯
            context: "It was pure serendipity that led her to the little bookshop on the corner.",
            explanation: L10n.string("reviewCardLayout.sample.explanation"),
            // i18n-allow: 詞性縮寫是語言學技術標記
            partOfSpeech: "n.",
            bookTitle: L10n.string("reviewCardLayout.sample.book"),
            chapterTitle: L10n.string("reviewCardLayout.sample.chapter")
        )
        entry.dateAdded = Date(timeIntervalSince1970: 1_700_000_000)
        // i18n-allow: difficultyTier 是 ASCII 技術代碼，渲染端自行本地化
        entry.difficultyTier = "intermediate"
        entry.reviewMode = mode
        entry.reviewExamples = [
            // i18n-allow: 例句是英文學習素材本身
            "A serendipity of timing put the two researchers on the same train.",
        ]
        entry.collocations = [
            // i18n-allow: 搭配詞是英文學習素材本身
            "happy serendipity",
            "by serendipity",
        ]
        entry.graphLinksByKind = [
            "shares_usage": [
                KGCardLinkSummary(
                    id: "sample-link-1",
                    cardId: "sample-card-1",
                    // i18n-allow: 相關單字是英文學習素材本身
                    word: "fortuitous",
                    kind: "shares_usage",
                    label: "",
                    confidence: 0.82,
                    reason: "",
                    hidden: false
                ),
            ],
        ]

        let card = entry.cardPresentation
        let linkGroups = card.linkGroups.map { group in
            TodayReviewPresenterState.LinkGroup(
                id: group.id,
                label: group.label,
                items: group.items,
                overflowCount: 0
            )
        }
        return .init(
            card: card,
            linkGroups: linkGroups,
            backDocument: card.document.reviewBackSubset()
        )
    }
}
