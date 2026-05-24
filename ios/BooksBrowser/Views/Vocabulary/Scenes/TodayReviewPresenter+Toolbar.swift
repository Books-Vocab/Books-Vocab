import SwiftUI

extension TodayReviewPresenter {
    struct ShortcutHint: Identifiable {
        let id: String
        let key: String
        let label: String
        var isPrimary = false
    }

    // MARK: - Top Bar

    var topBar: some View {
        HStack(alignment: .center, spacing: AppSpacing.s3) {
            Text(state.progressText)
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, appSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    Capsule(style: .continuous)
                        .fill(appSkin.palette.mutedFill)
                )

            Button {
                guard isCardInteractive else { return }
                onShuffle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(appSkin.typography.iconTiny)
                    Text("洗牌".localized)
                        .font(appSkin.typography.caption)
                }
                .foregroundStyle(state.canShuffle ? appSkin.palette.secondaryText : appSkin.palette.quaternaryText)
                .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, appSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    Capsule(style: .continuous)
                        .fill(appSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!state.canShuffle)

            Spacer()

            VocabChromeIconButton(
                systemImage: state.isAutoPlaying ? "play.circle.fill" : "play.circle",
                tone: state.isAutoPlaying ? appSkin.palette.accent : nil,
                action: onToggleAutoPlay
            )

            #if os(macOS)
            VocabChromeIconButton(
                systemImage: "questionmark.circle",
                label: L10n.string("vocab.chromeIcon.todayReview.help"),
                action: onToggleHelp
            )
            #endif

            VocabChromeIconButton(
                systemImage: "xmark",
                label: L10n.string("vocab.chromeIcon.todayReview.close"),
                action: onClose
            )
        }
        .padding(.horizontal, TodayReviewMetrics.topBarHorizontalInset)
        .padding(.top, TodayReviewMetrics.topBarTopInset)
        .padding(.bottom, TodayReviewMetrics.topBarBottomInset)
    }

    // MARK: - Bottom Toolbar

    var bottomToolbar: some View {
        VStack(spacing: 10) {
            #if os(macOS)
            shortcutRail
            #endif
            toolbarControls
        }
        .padding(.horizontal, TodayReviewMetrics.toolbarHorizontalInset)
        .padding(.vertical, TodayReviewMetrics.toolbarVerticalInset)
        .background(
            Rectangle()
                .fill(appSkin.palette.pageBackground)
                .appElevation(.z2, direction: .up)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    @ViewBuilder
    private var toolbarControls: some View {
        Group {
            if state.isAutoPlaying {
                autoplayControls
            } else if dynamicTypeSize < .accessibility1 {
                HStack(spacing: 0) {
                    navButtons
                    Spacer()
                    feedbackButtons
                }
            } else {
                VStack(spacing: appSkin.spacing.inlineGap) {
                    feedbackButtons.frame(maxWidth: .infinity)
                    navButtons
                }
            }
        }
        .animation(AppMotion.reviewNavigationSpring, value: state.revealStage.showsAnswer)
        .animateSpring(state.isAutoPlaying)
    }

    #if os(macOS)
    var shortcutRail: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: appSkin.spacing.microGap) {
                ForEach(activeShortcutHints) { hint in
                    ShortcutHintChip(hint: hint)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottomLeading) {
            if showFirstRunHint && !isHelpPresented {
                Text("可用方向鍵評分，按 Space 展開答案".localized)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .padding(.top, 28)
                    .transition(.overlayFade)
            }
        }
        .opacity(isHelpPresented ? 0.35 : 1)
    }

    var shortcutHelpOverlay: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            HStack {
                Text("快捷鍵".localized)
                    .font(appSkin.typography.sectionTitle)
                    .foregroundStyle(appSkin.palette.primaryText)
                Spacer()
                Button("完成".localized, action: onToggleHelp)
                    .buttonStyle(.ghost(appSkin.palette.secondaryText))
            }

            shortcutHelpSection(
                title: "複習".localized,
                hints: state.isAutoPlaying ? autoplayShortcutHints : reviewShortcutHints
            )
            shortcutHelpSection(title: "導覽".localized, hints: navigationShortcutHints)
            shortcutHelpSection(title: "工作階段".localized, hints: sessionShortcutHints)
        }
        .padding(appSkin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: appSkin.radii.overlay, style: .continuous)
                .fill(appSkin.palette.overlayFill)
                .overlay(
                    RoundedRectangle(cornerRadius: appSkin.radii.overlay, style: .continuous)
                        .stroke(appSkin.palette.cardBorder.opacity(0.55), lineWidth: 1)
                )
                .appElevation(.z3)
        )
        .frame(maxWidth: 420, alignment: .topLeading)
    }

    func shortcutHelpSection(title: String, hints: [ShortcutHint]) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)

            ForEach(hints) { hint in
                HStack(alignment: .firstTextBaseline, spacing: appSkin.spacing.inlineGap) {
                    ShortcutKeyCap(key: hint.key)
                    Text(hint.label)
                        .font(appSkin.typography.body)
                        .foregroundStyle(appSkin.palette.primaryText)
                    Spacer(minLength: 0)
                }
            }
        }
    }

    var activeShortcutHints: [ShortcutHint] {
        if state.currentCard == nil {
            return [
                .init(id: "esc", key: "Esc", label: "返回".localized, isPrimary: true),
                .init(id: "help", key: "?", label: "快捷鍵".localized)
            ]
        }
        return state.isAutoPlaying ? autoplayShortcutHints : reviewShortcutHints
    }

    var reviewShortcutHints: [ShortcutHint] {
        let spaceLabel = state.revealStage == .front ? "展開".localized : "收回".localized
        return [
            .init(id: "space", key: "Space", label: spaceLabel, isPrimary: true),
            .init(id: "left", key: "←", label: "忘記".localized, isPrimary: true),
            .init(id: "right", key: "→", label: "記得".localized, isPrimary: true),
            .init(id: "detail", key: "D", label: "詳情".localized),
            .init(id: "help", key: "?", label: "快捷鍵".localized)
        ]
    }

    var autoplayShortcutHints: [ShortcutHint] {
        [
            .init(id: "pause", key: "P", label: state.isAutoPlayPaused ? "繼續".localized : "暫停".localized, isPrimary: true),
            .init(id: "left", key: "←", label: "上一張".localized, isPrimary: true),
            .init(id: "right", key: "→", label: "下一張".localized, isPrimary: true),
            .init(id: "esc", key: "Esc", label: "關閉".localized),
            .init(id: "help", key: "?", label: "快捷鍵".localized)
        ]
    }

    var navigationShortcutHints: [ShortcutHint] {
        [
            .init(id: "up", key: "↑", label: "上一張".localized),
            .init(id: "down", key: "↓", label: "下一張".localized),
            .init(id: "shuffle", key: "S", label: "洗牌".localized),
            .init(id: "detail", key: "D", label: "查看詳情".localized)
        ]
    }

    var sessionShortcutHints: [ShortcutHint] {
        [
            .init(id: "play", key: "P", label: "自動播放".localized),
            .init(id: "esc", key: "Esc", label: "關閉".localized),
            .init(id: "help", key: "?", label: "顯示快捷鍵".localized)
        ]
    }
    #endif

    // MARK: - Autoplay Controls

    var autoplayControls: some View {
        HStack(spacing: appSkin.metrics.sectionHeaderGap * 2) {
            Button {
                guard isCardInteractive else { return }
                onPrevious()
            } label: {
                Image(systemName: "backward.end.fill")
                    .font(AppFonts.h2())
            }
            .disabled(!state.canGoPrevious)
            .accessibilityLabel(L10n.string("todayReview.autoplay.previous"))

            Button(action: onToggleAutoPlayPause) {
                Image(systemName: state.isAutoPlayPaused ? "play.fill" : "pause.fill")
                    .font(AppFonts.h1())
                    .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                    .background(
                        Circle()
                            .fill(appSkin.palette.mutedFill)
                    )
            }
            .accessibilityLabel(L10n.string(state.isAutoPlayPaused ? "todayReview.autoplay.playpause.play" : "todayReview.autoplay.playpause.pause"))

            Button {
                guard isCardInteractive else { return }
                onNext()
            } label: {
                Image(systemName: "forward.end.fill")
                    .font(AppFonts.h2())
            }
            .disabled(!state.canGoNext)
            .accessibilityLabel(L10n.string("todayReview.autoplay.next"))
        }
        .foregroundStyle(appSkin.palette.primaryText)
        .frame(maxWidth: .infinity)
    }

    var navButtons: some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Button { guard isCardInteractive else { return }; onPrevious() } label: {
                Image(systemName: "chevron.left").font(appSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoPrevious)
            .accessibilityLabel(L10n.string("todayReview.nav.previous"))

            Button { guard isCardInteractive else { return }; onNext() } label: {
                Image(systemName: "chevron.right").font(appSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoNext)
            .accessibilityLabel(L10n.string("todayReview.nav.next"))
        }
        .foregroundStyle(appSkin.palette.secondaryText)
    }

    // MARK: - Feedback Buttons

    var feedbackButtons: some View {
        let spring = AppMotion.feedbackButtonSpring
        let buttonsDisabled = false

        return HStack(spacing: appSkin.metrics.sectionHeaderGap) {
            Button { flingCard(direction: -1, callback: onForgot) } label: {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "xmark")
                    Text("忘記".localized)
                    if state.forgotCount > 0 {
                        Text("·\(state.forgotCount)").font(appSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: TodayReviewMetrics.actionMinWidth)
            }
            .buttonStyle(.vocabAction(.destructive))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if forgotButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                        .fill(appSkin.palette.destructive.opacity(forgotButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(forgotButtonScale)
            .offset(y: forgotButtonOffset)
            .opacity(forgotButtonOpacity)
            .animation(spring, value: swipeIntensity)

            Button { flingCard(direction: 1, callback: onRemembered) } label: {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "checkmark")
                    Text("記得".localized)
                    if state.rememberedCount > 0 {
                        Text("·\(state.rememberedCount)").font(appSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: TodayReviewMetrics.actionMinWidth)
            }
            .buttonStyle(.vocabAction(.success))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if rememberedButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                        .fill(appSkin.palette.success.opacity(rememberedButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(rememberedButtonScale)
            .offset(y: rememberedButtonOffset)
            .opacity(rememberedButtonOpacity)
            .animation(spring, value: swipeIntensity)
        }
    }

    // MARK: - Swipe ↔ Button Linkage

    var swipeIntensity: Double {
        if dismissPhase == .animatingOut { return frozenSwipeIntensity }
        guard swipeEnabled else { return 0 }
        return max(-1, min(1, Double(swipeOffset / TodayReviewMetrics.swipeThreshold)))
    }

    var forgotButtonScale: CGFloat   { 1.0 + CGFloat(max(-swipeIntensity, 0)) * 0.12 }
    var forgotButtonOffset: CGFloat  { CGFloat(max(-swipeIntensity, 0)) * -4 }
    var forgotButtonOpacity: Double  { 1.0 - max(swipeIntensity, 0) * 0.45 }
    var forgotButtonGlow: Double     { max(-swipeIntensity, 0) }

    var rememberedButtonScale: CGFloat   { 1.0 + CGFloat(max(swipeIntensity, 0)) * 0.12 }
    var rememberedButtonOffset: CGFloat  { CGFloat(max(swipeIntensity, 0)) * -4 }
    var rememberedButtonOpacity: Double  { 1.0 - max(-swipeIntensity, 0) * 0.45 }
    var rememberedButtonGlow: Double     { max(swipeIntensity, 0) }
}

#if os(macOS)
private struct ShortcutHintChip: View {
    @Environment(\.appSkin) private var appSkin

    let hint: TodayReviewPresenter.ShortcutHint

    var body: some View {
        HStack(spacing: appSkin.spacing.microGap) {
            ShortcutKeyCap(key: hint.key)
            Text(hint.label)
                .font(appSkin.typography.caption)
                .foregroundStyle(hint.isPrimary ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
        }
        .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
        .padding(.vertical, appSkin.spacing.compactChipVerticalPadding)
        .background(
            Capsule()
                .fill(appSkin.palette.mutedFill.opacity(hint.isPrimary ? 0.95 : 0.72))
        )
        .overlay(
            Capsule()
                .stroke(appSkin.palette.cardBorder.opacity(0.4), lineWidth: 1)
        )
    }
}

private struct ShortcutKeyCap: View {
    @Environment(\.appSkin) private var appSkin

    let key: String

    var body: some View {
        Text(key)
            .font(AppFonts.monoNumbers(size: 12))
            .foregroundStyle(appSkin.palette.primaryText)
            .padding(.horizontal, 6)
            .padding(.vertical, AppSpacing.s1)
            .background(
                RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                    .fill(appSkin.palette.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                            .stroke(appSkin.palette.cardBorder.opacity(0.5), lineWidth: 1)
                    )
            )
    }
}
#endif
