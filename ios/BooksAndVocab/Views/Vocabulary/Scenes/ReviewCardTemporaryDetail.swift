import Foundation

/// 精簡卡的「暫時看詳細」（#2041）。
///
/// 只活在一次複習 session 的記憶體裡（`TodayReviewState`）：一次只記一張卡，離開
/// 那張卡（任何推進路徑）即忘記，再回來仍是精簡。**不寫** `ReviewCardLayoutStore`
/// ／`NotebookSettings`／iCloud —— 它不是設定，是「讓我把這張看完整」。
///
/// 渲染端不另做一套版面：詳細就是把這張卡那個方向的 preset 換成 `.standard`，
/// 交給同一個 render plan / solver。內容（例句、詳解、搭配詞）本來就在
/// `TodayReviewCardCache` 的完整 `CardPresentation` 裡，不需要再補資料。
struct ReviewCardTemporaryDetail: Equatable {
    /// 卡片 chrome 上那顆按鈕的狀態。同一顆按鈕來回切換。
    enum ToggleState: String, Equatable {
        /// 這張卡已是正常版面：不顯示按鈕。
        case unavailable
        /// 精簡中：按下暫時看詳細。
        case showDetail
        /// 暫時詳細中：按下恢復精簡。
        case restoreCompact
    }

    private(set) var detailedCardKey: String?

    func isDetailed(cardKey: String) -> Bool {
        detailedCardKey == cardKey
    }

    mutating func toggle(cardKey: String) {
        detailedCardKey = detailedCardKey == cardKey ? nil : cardKey
    }

    /// Leaving the card forgets the override. Returns `false` (and writes nothing)
    /// when there was nothing to forget, so the caller's `@Observable` storage is
    /// not invalidated on every advance.
    @discardableResult
    mutating func reset() -> Bool {
        guard detailedCardKey != nil else { return false }
        detailedCardKey = nil
        return true
    }

    static func toggleState(
        profile: ReviewCardLayoutProfile,
        mode: VocabularyCardMode,
        isDetailed: Bool
    ) -> ToggleState {
        guard profile.preset(for: mode) == .compact else { return .unavailable }
        return isDetailed ? .restoreCompact : .showDetail
    }

    /// The profile the card actually renders with. Only this card's direction is
    /// lifted to `.standard`; the persisted profile value is never modified.
    static func renderProfile(
        _ profile: ReviewCardLayoutProfile,
        mode: VocabularyCardMode,
        isDetailed: Bool
    ) -> ReviewCardLayoutProfile {
        guard isDetailed, profile.preset(for: mode) == .compact else { return profile }
        var rendered = profile
        rendered.setPreset(.standard, for: mode)
        return rendered
    }

    /// Block fields the detailed face would add on `face`, limited to fields this
    /// card actually has content for. The card measures them ahead with hidden
    /// probes while compact, so expanding animates to real heights instead of
    /// to the solver's defaults followed by a second, un-animated correction.
    static func prospectiveBlockFields(
        profile: ReviewCardLayoutProfile,
        mode: VocabularyCardMode,
        face: ReviewCardFace,
        availability: ReviewCardContentAvailability
    ) -> [ReviewCardField] {
        guard profile.preset(for: mode) == .compact else { return [] }
        let current = ReviewCardRenderPlan.make(profile: profile, mode: mode, availability: availability)
        let detailed = ReviewCardRenderPlan.make(
            profile: renderProfile(profile, mode: mode, isDetailed: true),
            mode: mode,
            availability: availability
        )
        let currentFields = face == .front ? current.front.blockFields : current.back.blockFields
        let detailedFields = face == .front ? detailed.front.blockFields : detailed.back.blockFields
        return detailedFields.filter { !currentFields.contains($0) }
    }
}
