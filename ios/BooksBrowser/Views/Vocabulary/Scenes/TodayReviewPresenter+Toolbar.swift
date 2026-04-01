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

            #if os(macOS)
            VocabChromeIconButton(systemImage: "questionmark.circle", action: onToggleHelp)
            #endif

            VocabChromeIconButton(systemImage: "xmark", action: onClose)
        }
        .padding(.horizontal, vocabSkin.metrics.reviewTopBarHorizontalInset)
        .padding(.top, vocabSkin.metrics.reviewTopBarTopInset)
        .padding(.bottom, vocabSkin.metrics.reviewTopBarBottomInset)
    }

    // MARK: - Bottom Toolbar

    var bottomToolbar: some View {
        VStack(spacing: 10) {
            #if os(macOS)
            shortcutRail
            #endif
            toolbarControls
        }
        .padding(.horizontal, vocabSkin.metrics.reviewToolbarHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.reviewToolbarVerticalInset)
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
                VStack(spacing: vocabSkin.spacing.inlineGap) {
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
            HStack(spacing: vocabSkin.spacing.microGap) {
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
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .padding(.top, 28)
                    .transition(.overlayFade)
            }
        }
        .opacity(isHelpPresented ? 0.35 : 1)
    }

    var shortcutHelpOverlay: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            HStack {
                Text("快捷鍵".localized)
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                Spacer()
                Button("完成".localized, action: onToggleHelp)
                    .buttonStyle(.ghost(vocabSkin.palette.secondaryText))
            }

            shortcutHelpSection(
                title: "複習".localized,
                hints: state.isAutoPlaying ? autoplayShortcutHints : reviewShortcutHints
            )
            shortcutHelpSection(title: "導覽".localized, hints: navigationShortcutHints)
            shortcutHelpSection(title: "工作階段".localized, hints: sessionShortcutHints)
        }
        .padding(vocabSkin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous)
                .fill(vocabSkin.palette.overlayFill)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.overlay, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder.opacity(0.55), lineWidth: 1)
                )
                .shadow(color: vocabSkin.palette.shadow.opacity(0.18), radius: 18, y: 8)
        )
        .frame(maxWidth: 420, alignment: .topLeading)
    }

    func shortcutHelpSection(title: String, hints: [ShortcutHint]) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.secondaryText)

            ForEach(hints) { hint in
                HStack(alignment: .firstTextBaseline, spacing: vocabSkin.spacing.inlineGap) {
                    ShortcutKeyCap(key: hint.key)
                    Text(hint.label)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.primaryText)
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
                    .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
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
        let buttonsDisabled = false

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
        if dismissPhase == .animatingOut { return frozenSwipeIntensity }
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

#if os(macOS)
private struct ShortcutHintChip: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let hint: TodayReviewPresenter.ShortcutHint

    var body: some View {
        HStack(spacing: vocabSkin.spacing.microGap) {
            ShortcutKeyCap(key: hint.key)
            Text(hint.label)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(hint.isPrimary ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
        .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
        .background(
            Capsule()
                .fill(vocabSkin.palette.mutedFill.opacity(hint.isPrimary ? 0.95 : 0.72))
        )
        .overlay(
            Capsule()
                .stroke(vocabSkin.palette.cardBorder.opacity(0.4), lineWidth: 1)
        )
    }
}

private struct ShortcutKeyCap: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let key: String

    var body: some View {
        Text(key)
            .font(AppFonts.monoNumbers(size: 12))
            .foregroundStyle(vocabSkin.palette.primaryText)
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                    .fill(vocabSkin.palette.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder.opacity(0.5), lineWidth: 1)
                    )
            )
    }
}
#endif
