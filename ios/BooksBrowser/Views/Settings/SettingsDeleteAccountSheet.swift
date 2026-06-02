import SwiftUI
import Inject

/// 帳號刪除前的多步驟確認 Sheet。
///
/// 取代原本的 `.alert`（一鍵點即刪）以提供：
/// 1. 三項勾選確認（破壞性後果 explicit acknowledgement）
/// 2. 打字確認字串「DELETE」/「刪除」防誤觸
/// 3. 5 秒倒數冷卻 — 全部就緒後仍需等待，給使用者反悔機會
///
/// 業界參照：GitHub repo delete、Stripe API key revoke、Notion workspace delete。
struct SettingsDeleteAccountSheet: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.dismiss) private var dismiss

    /// 觸發實際刪除（呼叫端負責背景刪除流程）
    let onConfirm: () -> Void

    /// 預載中狀態（背景刪除進行時禁用所有控制項）
    let isDeleting: Bool

    @State private var ackDataLoss = false
    @State private var ackIrreversible = false
    @State private var ackNoSupport = false
    @State private var confirmText = ""
    @State private var countdownRemaining = SettingsDeleteAccountSheet.countdownSeconds
    @State private var countdownTask: Task<Void, Never>?

    /// 倒數秒數 — 給使用者反悔的視覺壓力
    private static let countdownSeconds = 5

    /// 必須輸入的確認字串（多語系下統一英文，降低 IME 失敗風險）
    private static let confirmationPhrase = "DELETE"

    private var allAcknowledged: Bool {
        ackDataLoss && ackIrreversible && ackNoSupport
    }

    private var confirmTextMatches: Bool {
        confirmText.trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased() == Self.confirmationPhrase
    }

    private var canDelete: Bool {
        allAcknowledged && confirmTextMatches && countdownRemaining == 0 && !isDeleting
    }

    private var deleteButtonTitle: String {
        if isDeleting {
            return "刪除中…".localized
        }
        if countdownRemaining > 0 && allAcknowledged && confirmTextMatches {
            return L10n.format("等候 %@ 秒…", "\(countdownRemaining)")
        }
        return "永久刪除帳號".localized
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: appSkin.spacing.sheetSectionSpacing) {
                    hero

                    consequencesCard

                    acknowledgementsCard

                    confirmationTypeCard

                    actionStack
                }
                .padding(appSkin.spacing.sheetPaddingCompact)
            }
            .background(appSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("確認刪除帳號".localized)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                        .disabled(isDeleting)
                }
            }
            .onChange(of: allAcknowledged && confirmTextMatches) { _, ready in
                if ready {
                    startCountdown()
                } else {
                    countdownTask?.cancel()
                    countdownTask = nil
                    countdownRemaining = Self.countdownSeconds
                }
            }
            .onDisappear {
                countdownTask?.cancel()
                countdownTask = nil
            }
            .animation(AppMotion.standardSpring, value: allAcknowledged)
            .animation(AppMotion.standardSpring, value: confirmTextMatches)
            .animation(AppMotion.contentFade, value: countdownRemaining)
        }
        .enableInjection()
    }

    // MARK: - Hero

    private var hero: some View {
        VStack(spacing: appSkin.spacing.controlGap) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(appSkin.typography.symbolHero)
                .foregroundStyle(appSkin.palette.destructive)
                .symbolEffect(.pulse, options: .repeating, value: isDeleting)

            Text("此操作不可復原".localized)
                .font(appSkin.typography.displayTitle)
                .foregroundStyle(appSkin.palette.primaryText)
                .multilineTextAlignment(.center)

            Text("刪除後將立即移除你的帳號、雲端生詞、閱讀進度、訂閱記錄。請仔細確認下列項目後才能繼續。".localized)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.secondaryText)
                .multilineTextAlignment(.center)
                .lineSpacing(4)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, appSkin.spacing.inlineGap)
    }

    // MARK: - Consequences (read-only list)

    private var consequencesCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: "將被永久刪除的資料".localized,
                icon: "trash"
            )

            VStack(alignment: .leading, spacing: appSkin.spacing.rowContentSpacing) {
                consequenceRow(icon: "person.crop.circle", text: "帳號資訊與登入記錄".localized)
                consequenceRow(icon: "books.vertical", text: "雲端生詞與筆記本".localized)
                consequenceRow(icon: "point.3.connected.trianglepath.dotted", text: "知識圖譜與關聯".localized)
                consequenceRow(icon: "book.closed", text: "閱讀進度與書架".localized)
                consequenceRow(icon: "checkmark.seal", text: "訂閱記錄（App Store 訂閱請另行至設定取消）".localized)
            }
            .padding(appSkin.spacing.cardPadding)
            .background(appSkin.palette.destructiveBg)
            .clipShape(RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous)
                    .stroke(appSkin.palette.destructive.opacity(0.22), lineWidth: 1)
            )
        }
    }

    private func consequenceRow(icon: String, text: String) -> some View {
        HStack(alignment: .top, spacing: appSkin.spacing.controlGap) {
            Image(systemName: icon)
                .font(appSkin.typography.iconMedium)
                .foregroundStyle(appSkin.palette.destructive)
                .frame(width: 22, alignment: .center)

            Text(text)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            Spacer()
        }
    }

    // MARK: - Acknowledgements (explicit toggles)

    private var acknowledgementsCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: "請確認你已知悉".localized,
                icon: "checkmark.square"
            )

            VStack(spacing: 0) {
                ackRow(
                    isOn: $ackDataLoss,
                    title: "我了解所有資料將被永久刪除".localized
                )
                SettingsDivider(leadingInset: 0)
                ackRow(
                    isOn: $ackIrreversible,
                    title: "我了解此操作無法復原".localized
                )
                SettingsDivider(leadingInset: 0)
                ackRow(
                    isOn: $ackNoSupport,
                    title: "我了解資料一旦刪除即無法經由客服救回".localized
                )
            }
            .settingsCard()
        }
    }

    private func ackRow(isOn: Binding<Bool>, title: String) -> some View {
        Toggle(isOn: isOn) {
            Text(title)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.primaryText)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .toggleStyle(SwitchToggleStyle(tint: appSkin.palette.destructive))
        .padding(.horizontal, appSkin.spacing.cardPadding)
        .padding(.vertical, appSkin.spacing.controlGap)
        .disabled(isDeleting)
    }

    // MARK: - Type-to-confirm

    private var confirmationTypeCard: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(
                title: "輸入確認字串".localized,
                icon: "keyboard"
            )

            VStack(alignment: .leading, spacing: appSkin.spacing.microGap) {
                Text(L10n.format("為避免誤觸，請輸入 %@ 後繼續：", Self.confirmationPhrase))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .fixedSize(horizontal: false, vertical: true)

                TextField(Self.confirmationPhrase, text: $confirmText)
                    .appSettingsTextInputStyle(alignment: .leading)
                    .padding(appSkin.spacing.cardPadding)
                    .background(appSkin.palette.pageBackground)
                    .clipShape(RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                            .stroke(
                                confirmTextMatches
                                    ? appSkin.palette.success
                                    : appSkin.palette.cardBorder,
                                lineWidth: 1
                            )
                    )
                    .disabled(isDeleting)
            }
            .settingsCard()
        }
    }

    // MARK: - Action stack

    private var actionStack: some View {
        VStack(spacing: appSkin.spacing.controlGap) {
            Button {
                onConfirm()
            } label: {
                HStack(spacing: appSkin.spacing.controlGap) {
                    if isDeleting {
                        ProgressView().controlSize(.small)
                    } else if countdownRemaining > 0 && allAcknowledged && confirmTextMatches {
                        Image(systemName: "hourglass")
                            .font(appSkin.typography.iconMedium)
                    } else {
                        Image(systemName: "trash.fill")
                            .font(appSkin.typography.iconMedium)
                    }

                    Text(deleteButtonTitle)
                        .font(appSkin.typography.body.weight(.semibold))
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.appAction(.destructive))
            .disabled(!canDelete)
            .opacity(canDelete || isDeleting ? 1.0 : 0.55)

            Button("取消".localized) { dismiss() }
                .buttonStyle(.appAction(.neutral))
                .disabled(isDeleting)
        }
    }

    // MARK: - Countdown

    private func startCountdown() {
        countdownTask?.cancel()
        countdownRemaining = Self.countdownSeconds
        countdownTask = Task { @MainActor in
            while countdownRemaining > 0 {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
                // 若使用者中途取消確認，allAcknowledged/confirmTextMatches 變 false → stop
                guard allAcknowledged && confirmTextMatches else {
                    countdownRemaining = Self.countdownSeconds
                    return
                }
                if countdownRemaining > 0 {
                    countdownRemaining -= 1
                }
            }
        }
    }
}

#Preview("DeleteAccount / Idle") {
    AppThemeContainer {
        SettingsDeleteAccountSheet(
            onConfirm: {},
            isDeleting: false
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("DeleteAccount / Deleting") {
    AppThemeContainer {
        SettingsDeleteAccountSheet(
            onConfirm: {},
            isDeleting: true
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
