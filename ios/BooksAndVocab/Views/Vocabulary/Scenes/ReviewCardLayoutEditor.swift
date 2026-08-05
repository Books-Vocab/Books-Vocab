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
struct ReviewCardLayoutEditor: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.reviewCardLayoutStore) private var store

    /// Opens on the mode of the card being looked at, so the first thing editable
    /// is the thing on screen.
    @State private var mode: VocabularyCardMode
    @State private var face: ReviewCardFace = .front

    init(initialMode: VocabularyCardMode = .recognition) {
        _mode = State(initialValue: initialMode)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                pickerSection
                previewSection
                fieldsSection
                SettingsSectionFooter(L10n.string("reviewCardLayout.footer"))
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle(L10n.string("reviewCardLayout.title"))
        .inlineNavigationBarTitle()
        .toolbar {
            ToolbarItem(placement: .primaryAction) { resetMenu }
        }
        .enableInjection()
    }

    // MARK: - Derived state

    private var layout: ReviewCardModeLayout { store.profile.layout(for: mode) }

    private var activeFields: [ReviewCardField] {
        switch face {
        case .front: layout.front
        case .back: layout.back
        }
    }

    /// Prompt on the front, answer on the back — mode semantics, not a profile
    /// field, which is exactly why the row cannot be switched off.
    private var lockedRowTitle: String {
        L10n.string(face == .front ? "reviewCardLayout.locked.prompt" : "reviewCardLayout.locked.answer")
    }

    // MARK: - Pickers

    private var pickerSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: L10n.string("reviewCardLayout.mode.section"),
                icon: "rectangle.split.2x1"
            )

            Picker(L10n.string("reviewCardLayout.mode.section"), selection: $mode) {
                ForEach(VocabularyCardMode.allCases, id: \.rawValue) { candidate in
                    Text(candidate.localizedTitle).tag(candidate)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("reviewCardLayout.modePicker")

            Picker(L10n.string("reviewCardLayout.preview.title"), selection: $face) {
                Text(L10n.string("reviewCardLayout.face.front")).tag(ReviewCardFace.front)
                Text(L10n.string("reviewCardLayout.face.back")).tag(ReviewCardFace.back)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("reviewCardLayout.facePicker")
        }
    }

    // MARK: - Preview

    private var previewSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("reviewCardLayout.preview.title"), icon: "eye")

            VStack(alignment: .leading, spacing: AppSpacing.s2) {
                previewRow(title: lockedRowTitle, isLocked: true)

                ForEach(activeFields, id: \.self) { field in
                    previewRow(title: L10n.string(field.titleKey), isLocked: false)
                }

                if activeFields.isEmpty {
                    Text(L10n.string("reviewCardLayout.preview.empty"))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(appSkin.spacing.cardPadding)
            .settingsCard()
            .accessibilityIdentifier("reviewCardLayout.preview")
        }
    }

    private func previewRow(title: String, isLocked: Bool) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Image(systemName: isLocked ? "lock.fill" : "circle.fill")
                .font(appSkin.typography.iconTiny)
                .foregroundStyle(isLocked ? appSkin.palette.tertiaryText : appSkin.palette.accent)
            Text(title)
                .font(isLocked ? appSkin.typography.body.weight(.semibold) : appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
            Spacer(minLength: AppSpacing.s2)
        }
    }

    // MARK: - Rows

    private var fieldsSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("reviewCardLayout.fields.section"), icon: "checklist")

            VStack(spacing: 0) {
                lockedRow

                ForEach(ReviewCardField.canonicalOrder, id: \.self) { field in
                    SettingsDivider()
                    fieldRow(field)
                }
            }
            .settingsCard()
        }
    }

    private var lockedRow: some View {
        AppKeyValueRow(icon: "lock.fill", label: lockedRowTitle, style: .settings(appSkin)) {
            Text(L10n.string("reviewCardLayout.locked.caption"))
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("reviewCardLayout.lockedRow")
    }

    private func fieldRow(_ field: ReviewCardField) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                Text(L10n.string(field.titleKey))
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.primaryText)
                Text(L10n.string(field.captionKey))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: AppSpacing.s2)

            Toggle("", isOn: binding(for: field))
                .labelsHidden()
                .tint(appSkin.palette.accent)
                .accessibilityLabel(L10n.string(field.titleKey))
                .accessibilityIdentifier("reviewCardLayout.toggle.\(field.rawValue)")
        }
        .padding(.horizontal, appSkin.spacing.cardPadding)
        .padding(.vertical, appSkin.spacing.controlVerticalPadding)
    }

    private func binding(for field: ReviewCardField) -> Binding<Bool> {
        Binding(
            get: { activeFields.contains(field) },
            set: { isOn in
                var updated = store.profile.layout(for: mode)
                switch face {
                case .front:
                    updated.front = ReviewCardField.toggling(field, in: updated.front, isOn: isOn)
                case .back:
                    updated.back = ReviewCardField.toggling(field, in: updated.back, isOn: isOn)
                }
                store.setLayout(updated, for: mode)
            }
        )
    }

    // MARK: - Reset

    private var resetMenu: some View {
        Menu {
            Button(L10n.format("reviewCardLayout.reset.currentMode", mode.localizedTitle)) {
                store.reset(mode)
            }
            .accessibilityIdentifier("reviewCardLayout.reset.currentMode")

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

    let initialMode: VocabularyCardMode
    let onDone: () -> Void

    var body: some View {
        NavigationStack {
            ReviewCardLayoutEditor(initialMode: initialMode)
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

#Preview("產出模式 / 正面全開") {
    AppThemeContainer {
        NavigationStack {
            ReviewCardLayoutEditor(initialMode: .production)
        }
    }
    .environment(\.reviewCardLayoutStore, .inMemory(profile: ReviewCardLayoutProfile(
        recognition: .init(front: [], back: []),
        production: .init(front: ReviewCardField.canonicalOrder, back: ReviewCardField.canonicalOrder)
    )))
    .environmentObject(AppAppearanceStore.preview)
}
