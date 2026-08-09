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
    @Environment(\.appSkin) private var appSkin
    @Environment(\.reviewCardLayoutStore) private var store

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

    /// 一個方向一個 Section：上面是二選一，下面是這個選擇當下會畫成什麼樣。
    /// 預覽直接讀 `store.profile.layout(for:)`，所以它不可能與卡片說法不同。
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

            VStack(alignment: .leading, spacing: AppSpacing.s2) {
                previewRow(
                    title: L10n.string("reviewCardLayout.locked.prompt"),
                    isLocked: true,
                    identifier: "reviewCardLayout.lockedRow.\(mode.rawValue).prompt"
                )
                ForEach(store.profile.layout(for: mode).front, id: \.self) { field in
                    previewRow(
                        title: L10n.string(field.titleKey),
                        isLocked: false,
                        identifier: "reviewCardLayout.previewField.\(mode.rawValue).front.\(field.rawValue)"
                    )
                }

                previewRow(
                    title: L10n.string("reviewCardLayout.locked.answer"),
                    isLocked: true,
                    identifier: "reviewCardLayout.lockedRow.\(mode.rawValue).answer"
                )
                ForEach(store.profile.layout(for: mode).back, id: \.self) { field in
                    previewRow(
                        title: L10n.string(field.titleKey),
                        isLocked: false,
                        identifier: "reviewCardLayout.previewField.\(mode.rawValue).back.\(field.rawValue)"
                    )
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
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

    /// 每一列都掛 identifier：preset 的結果是這一頁**唯一**可斷言的東西
    /// （segmented picker 的當選段不可靠），UI test 靠列的存在與否判定 preset。
    private func previewRow(title: String, isLocked: Bool, identifier: String) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Image(systemName: isLocked ? "lock.fill" : "circle.fill")
                .font(appSkin.typography.iconTiny)
                .foregroundStyle(isLocked ? appSkin.palette.tertiaryText : appSkin.palette.accent)
            Text(title)
                .font(isLocked ? appSkin.typography.body.weight(.semibold) : appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
            Spacer(minLength: AppSpacing.s2)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(identifier)
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

    let onDone: () -> Void

    var body: some View {
        NavigationStack {
            ReviewCardLayoutEditor()
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
