import SwiftUI

extension TodayReviewPresenter {
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
                .accessibilityIdentifier("todayReview.progressLabel")

            Button {
                guard isCardInteractive else { return }
                onShuffle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(appSkin.typography.iconTiny)
                    Text(TodayReviewShortcutCatalog.shuffleLabel)
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
                label: L10n.string(state.isAutoPlaying ? "vocab.chromeIcon.todayReview.autoplay.on" : "vocab.chromeIcon.todayReview.autoplay.off"),
                action: onToggleAutoPlay
            )

            #if targetEnvironment(macCatalyst)
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
            #if targetEnvironment(macCatalyst)
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

    #if targetEnvironment(macCatalyst)
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
                Text(TodayReviewShortcutCatalog.firstRunHint)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .padding(.top, AppSpacing.s7 - AppSpacing.s1)
                    .transition(.overlayFade)
            }
        }
        .opacity(isHelpPresented ? 0.35 : 1)
    }

    var shortcutHelpOverlay: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            HStack {
                Text(TodayReviewShortcutCatalog.overlayTitle)
                    .font(appSkin.typography.sectionTitle)
                    .foregroundStyle(appSkin.palette.primaryText)
                Spacer()
                Button(TodayReviewShortcutCatalog.doneLabel, action: onToggleHelp)
                    .buttonStyle(.ghost(appSkin.palette.secondaryText))
            }

            shortcutHelpSection(
                title: TodayReviewShortcutCatalog.reviewSectionTitle,
                hints: state.isAutoPlaying ? autoplayShortcutHints : reviewShortcutHints
            )
            shortcutHelpSection(title: TodayReviewShortcutCatalog.navigationSectionTitle, hints: navigationShortcutHints)
            shortcutHelpSection(title: TodayReviewShortcutCatalog.sessionSectionTitle, hints: sessionShortcutHints)
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

    func shortcutHelpSection(title: String, hints: [TodayReviewShortcutHint]) -> some View {
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

    var activeShortcutHints: [TodayReviewShortcutHint] {
        TodayReviewShortcutCatalog.activeHints(
            hasCurrentCard: state.currentCard != nil,
            revealStage: state.revealStage,
            isAutoPlaying: state.isAutoPlaying,
            isAutoPlayPaused: state.isAutoPlayPaused
        )
    }

    var reviewShortcutHints: [TodayReviewShortcutHint] {
        TodayReviewShortcutCatalog.reviewHints(revealStage: state.revealStage)
    }

    var autoplayShortcutHints: [TodayReviewShortcutHint] {
        TodayReviewShortcutCatalog.autoplayHints(isAutoPlayPaused: state.isAutoPlayPaused)
    }

    var navigationShortcutHints: [TodayReviewShortcutHint] {
        TodayReviewShortcutCatalog.navigationHints
    }

    var sessionShortcutHints: [TodayReviewShortcutHint] {
        TodayReviewShortcutCatalog.sessionHints
    }
    #endif

    // MARK: - Autoplay Controls

    var autoplayControls: some View {
        VStack(spacing: TodayReviewMetrics.autoplayProgressBarBottomGap) {
            // Progress bar
            ProgressCapsule(
                progress: state.autoplayProgress,
                label: state.progressText,
                fillColor: appSkin.palette.accent,
                trackColor: appSkin.palette.mutedFill.opacity(0.5),
                labelFont: appSkin.typography.monoLabel,
                height: TodayReviewMetrics.autoplayProgressBarHeight
            )

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

                Button(action: onToggleAutoPlaySound) {
                    Image(systemName: state.autoplaySoundEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                        .font(appSkin.typography.iconSmall)
                        .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                        .background(
                            Circle()
                                .fill(appSkin.palette.mutedFill)
                        )
                }
                .accessibilityLabel(L10n.string(
                    state.autoplaySoundEnabled
                    ? "todayReview.autoplay.sound.off"
                    : "todayReview.autoplay.sound.on"
                ))

                // Speed pill
                Button(action: onChangeAutoPlaySpeed) {
                    Text(state.autoplaySpeed.displayName)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .padding(.horizontal, TodayReviewMetrics.autoplaySpeedPillHorizontalPadding)
                        .frame(height: TodayReviewMetrics.autoplaySpeedPillHeight)
                        .background(
                            Capsule(style: .continuous)
                                .fill(appSkin.palette.mutedFill)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityLabel(state.autoplaySpeed.displayName)
            }
            .foregroundStyle(appSkin.palette.primaryText)
            .frame(maxWidth: .infinity)
        }
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
            Button { flingCard(direction: -1, source: "button", callback: onForgot) } label: {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "xmark")
                    Text(L10n.string("忘記"))
                    if state.forgotCount > 0 {
                        Text("·\(state.forgotCount)").font(appSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: TodayReviewMetrics.actionMinWidth)
            }
            .buttonStyle(.vocabAction(.destructive))
            .accessibilityIdentifier("todayReview.feedback.forgot")
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

            Button { flingCard(direction: 1, source: "button", callback: onRemembered) } label: {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "checkmark")
                    Text(L10n.string("記得"))
                    if state.rememberedCount > 0 {
                        Text("·\(state.rememberedCount)").font(appSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: TodayReviewMetrics.actionMinWidth)
            }
            .buttonStyle(.vocabAction(.success))
            .accessibilityIdentifier("todayReview.feedback.remembered")
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

#if targetEnvironment(macCatalyst)
struct ShortcutHintChip: View {
    @Environment(\.appSkin) private var appSkin

    let hint: TodayReviewShortcutHint

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

struct ShortcutKeyCap: View {
    @Environment(\.appSkin) private var appSkin

    let key: String

    var body: some View {
        Text(key)
            .font(AppFonts.monoNumbers(size: 12))
            .foregroundStyle(appSkin.palette.primaryText)
            .padding(.horizontal, appSkin.spacing.compactChipHorizontalPadding)
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
