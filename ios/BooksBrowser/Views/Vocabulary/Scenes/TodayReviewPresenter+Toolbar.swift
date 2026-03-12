import SwiftUI

extension TodayReviewPresenter {

    // MARK: - Top Bar

    var topBar: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(state.progressText)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )

            Button {
                guard isCardInteractive else { return }
                onShuffle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(vocabSkin.typography.iconTiny)
                    Text("洗牌".localized)
                        .font(vocabSkin.typography.captionStrong)
                }
                .foregroundStyle(state.canShuffle ? vocabSkin.palette.secondaryText : vocabSkin.palette.quaternaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!state.canShuffle)

            Spacer()

            VocabChromeIconButton(
                systemImage: state.isAutoPlaying ? "play.circle.fill" : "play.circle",
                tone: state.isAutoPlaying ? vocabSkin.palette.accent : nil,
                action: onToggleAutoPlay
            )

            VocabChromeIconButton(systemImage: "xmark", action: onClose)
        }
        .padding(.horizontal, vocabSkin.metrics.reviewTopBarHorizontalInset)
        .padding(.top, vocabSkin.metrics.reviewTopBarTopInset)
        .padding(.bottom, vocabSkin.metrics.reviewTopBarBottomInset)
    }

    // MARK: - Bottom Toolbar

    var bottomToolbar: some View {
        VStack(spacing: 10) {
            if let msg = state.persistenceErrorMessage {
                VocabStateMessageCard(
                    title: "本機儲存失敗".localized,
                    systemImage: "externaldrive.badge.exclamationmark",
                    description: msg
                )
                .transition(.overlayFade)
            }

            if state.isAutoPlaying {
                autoplayControls
            } else if dynamicTypeSize < .accessibility1 {
                HStack(spacing: 0) {
                    navButtons
                    Spacer()
                    feedbackButtons
                }
            } else {
                VStack(spacing: vocabSkin.spacing.inlineGap) {
                    feedbackButtons.frame(maxWidth: .infinity)
                    navButtons
                }
            }
        }
        .padding(.horizontal, vocabSkin.metrics.reviewToolbarHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.reviewToolbarVerticalInset)
        .animation(AppMotion.reviewNavigationSpring, value: state.revealStage.showsAnswer)
        .animation(AppMotion.phaseChange, value: state.persistenceErrorMessage)
        .animation(AppMotion.standardSpring, value: state.isAutoPlaying)
        .background(
            Rectangle()
                .fill(vocabSkin.palette.pageBackground)
                .shadow(
                    color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.reviewToolbarShadowOpacity),
                    radius: vocabSkin.metrics.reviewToolbarShadowRadius,
                    y: vocabSkin.metrics.reviewToolbarShadowY
                )
                .ignoresSafeArea(edges: .bottom)
        )
    }

    // MARK: - Autoplay Controls

    var autoplayControls: some View {
        HStack(spacing: vocabSkin.metrics.sectionHeaderGap * 2) {
            Button {
                guard isCardInteractive else { return }
                onPrevious()
            } label: {
                Image(systemName: "backward.end.fill")
                    .font(AppFonts.h2())
            }
            .disabled(!state.canGoPrevious)

            Button(action: onToggleAutoPlayPause) {
                Image(systemName: state.isAutoPlayPaused ? "play.fill" : "pause.fill")
                    .font(AppFonts.h1())
                    .frame(width: 52, height: 52)
                    .background(
                        Circle()
                            .fill(vocabSkin.palette.mutedFill)
                    )
            }

            Button {
                guard isCardInteractive else { return }
                onNext()
            } label: {
                Image(systemName: "forward.end.fill")
                    .font(AppFonts.h2())
            }
            .disabled(!state.canGoNext)
        }
        .foregroundStyle(vocabSkin.palette.primaryText)
        .frame(maxWidth: .infinity)
    }

    var navButtons: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Button { guard isCardInteractive else { return }; onPrevious() } label: {
                Image(systemName: "chevron.left").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoPrevious)

            Button { guard isCardInteractive else { return }; onNext() } label: {
                Image(systemName: "chevron.right").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoNext)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
    }

    // MARK: - Feedback Buttons

    var feedbackButtons: some View {
        let spring = AppMotion.feedbackButtonSpring
        let buttonsDisabled = !state.revealStage.showsAnswer

        return HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
            Button { flingCard(direction: -1, callback: onForgot) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "xmark")
                    Text("忘記".localized)
                    if state.forgotCount > 0 {
                        Text("·\(state.forgotCount)").font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.destructive))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if forgotButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.destructive.opacity(forgotButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(forgotButtonScale)
            .offset(y: forgotButtonOffset)
            .opacity(forgotButtonOpacity)
            .animation(spring, value: swipeIntensity)

            Button { flingCard(direction: 1, callback: onRemembered) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "checkmark")
                    Text("記得".localized)
                    if state.rememberedCount > 0 {
                        Text("·\(state.rememberedCount)").font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.success))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if rememberedButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.success.opacity(rememberedButtonGlow * 0.10))
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
        guard swipeEnabled else { return 0 }
        return max(-1, min(1, Double(swipeOffset / vocabSkin.metrics.reviewSwipeThreshold)))
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
