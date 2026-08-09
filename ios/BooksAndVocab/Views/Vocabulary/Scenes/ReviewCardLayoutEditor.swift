import SwiftUI

/// Review card layout editor — ONE view struct behind both entry points (the
/// review toolbar and Settings ▸ 偏好). Kept a top-level `View` struct and never
/// inlined back into a presenter body: the device main thread has a 1MB stack and
/// an inlined section tree overflows it under Debug `-Onone` (see the header of
/// `SettingsPresenter.swift`).
///
/// The editor writes straight through to `ReviewCardLayoutStore`, so the card
/// behind a sheet re-lays out as a toggle flips; it owns no draft copy that could
/// disagree with what the card is drawing.
///
/// 版面：與「複習節奏」「閱讀設定」同一套原生心智模型 —— `Form` + `Section`
/// (`SettingsSectionHeader` / `SettingsSectionFooter`)，選擇 = `Picker`。
/// 分隔線與列高一律由平台畫（APP-20260808-240a94 / f0770b）。
///
/// 自由度：每個方向（辨識 / 產出）只在「正常」與「精簡」之間選
/// （APP-20260808-7f0f3a）。六個欄位各自開關的舊模型連同它的正面/背面 picker
/// 一起退場 —— 那個自由度沒有人知道該怎麼用。
struct ReviewCardLayoutEditor: View {
    @ObserveInjection private var inject
    @Environment(\.reviewCardLayoutStore) private var store

    /// 從複習畫面工具列進來時是「當前那張卡」；從設定頁進來沒有當前卡，
    /// 走 `ReviewCardLayoutPreviewCard.sampleCard(for:)` 的內建範例卡。
    var previewCard: TodayReviewPresenterState.CurrentCard?

    init(previewCard: TodayReviewPresenterState.CurrentCard? = nil) {
        self.previewCard = previewCard
    }

    var body: some View {
        Form {
            ForEach(VocabularyCardMode.allCases, id: \.rawValue) { mode in
                directionSection(mode)
            }
        }
        .navigationTitle(L10n.string("reviewCardLayout.title"))
        .inlineNavigationBarTitle()
        .toolbar {
            ToolbarItem(placement: .primaryAction) { resetMenu }
        }
        .enableInjection()
    }

    // MARK: - Direction

    /// 一個方向一個 Section：上面是二選一，下面是這個選擇當下**真的**會畫成
    /// 什麼樣 —— 預覽用的是出貨複習卡的同一個 view，餵同一份 store.profile。
    private func directionSection(_ mode: VocabularyCardMode) -> some View {
        Section {
            Picker(mode.localizedTitle, selection: presetBinding(mode)) {
                ForEach(ReviewCardLayoutPreset.allCases, id: \.rawValue) { preset in
                    Text(L10n.string(preset.titleKey)).tag(preset)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityIdentifier("reviewCardLayout.preset.\(mode.rawValue)")

            previewCardView(mode)
        } header: {
            SettingsSectionHeader(title: mode.localizedTitle, icon: "rectangle.split.2x1")
        } footer: {
            if mode == VocabularyCardMode.allCases.last {
                SettingsSectionFooter(L10n.string("reviewCardLayout.footer"))
            }
        }
    }

    private func presetBinding(_ mode: VocabularyCardMode) -> Binding<ReviewCardLayoutPreset> {
        Binding(
            get: { store.profile.preset(for: mode) },
            set: { store.setPreset($0, for: mode) }
        )
    }

    /// 一張真的複習卡（翻開的樣子），不是欄位名稱清單。
    ///
    /// identifier 寫成兩個字面值而不是內插：`reviewCardLayout.preview` 是
    /// `ReviewCardLayoutEditorPage` 沿用至今的錨點，掛在主要方向（辨識）上；
    /// 產出方向另給一個後綴 id。內插寫法會讓那個歷史錨點在原始碼裡消失。
    @ViewBuilder
    private func previewCardView(_ mode: VocabularyCardMode) -> some View {
        let card = ReviewCardLayoutPreviewCard(
            currentCard: previewContent(for: mode),
            profile: store.profile
        )
        if mode == .recognition {
            card.accessibilityIdentifier("reviewCardLayout.preview")
        } else {
            card.accessibilityIdentifier("reviewCardLayout.preview.production")
        }
    }

    /// 當前那張卡只屬於它自己的方向；另一個方向一律用範例卡，否則等於拿辨識卡
    /// 去示範產出版面。
    private func previewContent(for mode: VocabularyCardMode) -> TodayReviewPresenterState.CurrentCard {
        if let previewCard, previewCard.card.reviewMode == mode {
            return previewCard
        }
        return ReviewCardLayoutPreviewCard.sampleCard(for: mode)
    }

    // MARK: - Reset

    /// 只剩「全部恢復」：一個方向只有兩個值，「只恢復這個方向」等同按另一顆。
    private var resetMenu: some View {
        Menu {
            Button(L10n.string("reviewCardLayout.reset.all"), role: .destructive) {
                store.resetAll()
            }
            .accessibilityIdentifier("reviewCardLayout.reset.all")
        } label: {
            Image(systemName: "arrow.counterclockwise")
        }
        .accessibilityLabel(L10n.string("reviewCardLayout.reset"))
        .accessibilityIdentifier("reviewCardLayout.resetMenu")
    }
}

/// Sheet shell for the review-screen entry. The editor page itself is shared with
/// Settings; only the chrome (stack + dismiss) differs.
struct ReviewCardLayoutEditorSheet: View {
    @ObserveInjection private var inject

    /// 工具列入口帶著「當前那張卡」進來，設定頁入口不帶。
    let previewCard: TodayReviewPresenterState.CurrentCard?
    let onDone: () -> Void

    var body: some View {
        NavigationStack {
            ReviewCardLayoutEditor(previewCard: previewCard)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(L10n.string("完成"), action: onDone)
                            .fontWeight(.semibold)
                            .accessibilityIdentifier("reviewCardLayout.done")
                    }
                }
        }
        .enableInjection()
    }
}

// MARK: - Preview

#Preview("預設") {
    AppThemeContainer {
        NavigationStack {
            ReviewCardLayoutEditor()
        }
    }
    .environment(\.reviewCardLayoutStore, .inMemory())
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("辨識精簡 / 產出正常") {
    AppThemeContainer {
        NavigationStack {
            ReviewCardLayoutEditor()
        }
    }
    .environment(\.reviewCardLayoutStore, .inMemory(profile: ReviewCardLayoutProfile(
        recognition: .compact,
        production: .standard
    )))
    .environmentObject(AppAppearanceStore.preview)
}
