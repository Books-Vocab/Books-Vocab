#if os(iOS)
import SwiftUI

struct PodcastPlayerLockedGateView: View {
    let isGuest: Bool
    let action: () -> Void

    @Environment(\.appSkin) private var skin
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: skin.spacing.sectionGap) {
            Image(systemName: "lock.fill")
                .font(skin.typography.symbolHero)
                .foregroundStyle(skin.palette.accent)
            Text(isGuest
                 ? L10n.string("podcast.guest.locked.title")
                 : L10n.string("podcast.locked.title"))
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
            Text(isGuest
                 ? L10n.string("podcast.guest.locked.body")
                 : L10n.string("podcast.locked.body"))
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.secondaryText)
                .multilineTextAlignment(.center)
            Button(action: action) {
                Label(isGuest
                      ? L10n.string("podcast.guest.cta.signInToListen")
                      : L10n.string("podcast.locked.cta.upgrade"),
                      systemImage: isGuest ? "person.crop.circle" : "sparkles")
            }
            .buttonStyle(.appAction(.primary))
            .frame(maxWidth: 280)
            .accessibilityIdentifier(isGuest ? "podcast.player.locked.signInButton" : "podcast.player.locked.upgradeButton")
        }
        .padding(AppShellMetrics.pageHorizontalPadding)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.palette.pageBackground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .accessibilityIdentifier(isGuest ? "podcast.player.locked.loginGate" : "podcast.player.locked.paywallGate")
    }
}

struct PodcastPlayerPreviewBanner: View {
    let action: () -> Void

    @Environment(\.appSkin) private var skin

    var body: some View {
        HStack(spacing: skin.spacing.inlineGap) {
            Image(systemName: "lock.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(AppColors.onBrandHero)
            Text(L10n.string("podcast.preview.banner.message"))
                .font(skin.typography.caption)
                .foregroundStyle(AppColors.onBrandHero)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: action) {
                Text(L10n.string("podcast.locked.cta.upgrade"))
                    .font(skin.typography.caption.weight(.semibold))
            }
            .buttonStyle(.appCompactAction(.primary))
        }
        .padding(.horizontal, skin.spacing.cardPadding)
        .padding(.vertical, skin.spacing.inlineGap)
        // 單列 banner，短邊是高度（compact action 鈕 ~32pt + 上下 inlineGap 8pt ≈ 48pt），
        // 落 30–70pt 帶 → control。r 由 8 → 7.2。
        .background(skin.palette.brandHero, in: AppRoundedRect(roundness: AppRoundness.control))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("podcast.preview.banner")
    }
}

struct PodcastPlayerSettingsButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            AppToolbarGlyph(systemImage: "textformat.size")
        }
        .accessibilityLabel(L10n.string("podcast.player.subtitleSettings"))
        .accessibilityIdentifier("podcast.player.settingsButton")
    }
}
#endif
