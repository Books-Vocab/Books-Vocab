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
