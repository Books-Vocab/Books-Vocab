import SwiftUI

// MARK: - Chrome Equatable 切片（settle 白工 Phase 2）
//
// topBar / toolbarControls 原本是 presenter body 的內聯子樹：presenter 任何
// @State 失效（drag 每幀、settle 窗口每次重評）都整段重建，L10n/AppFonts
// 查表跟著重跑。抽成 Equatable 子 view 後，chrome 只在「值切片」真的改變時
// 重評（counts/progressText 變的那一幀是合法工作）。
//
// 契約：所有會影響 chrome 渲染的值**必須**收進 model（synthesized == 全欄位
// 比較，無漏比可能）；child 的其他 stored property 只允許 intent 閉包
// （閉包不參與 ==；Equatable skip 時留住舊閉包是安全的——它們只呼叫
// presenter 方法/@State 寫入，State storage 跨 update 穩定）。此契約由
// ReviewChromeSliceTests 用 Mirror 驗證（非 model 欄位必須是 function）。

struct ReviewTopBarModel: Equatable {
    var progressText: String
    var canShuffle: Bool
    var canAutoplay: Bool
    var isAutoPlaying: Bool
    var isCardInteractive: Bool
}

struct ReviewToolbarModel: Equatable {
    var showsAnswer: Bool
    var isAutoPlaying: Bool
    var isAutoPlayPaused: Bool
    var autoplaySoundEnabled: Bool
    var autoplaySpeedName: String
    var autoplayProgress: Double
    var progressText: String
    var forgotCount: Int
    var rememberedCount: Int
    var canGoPrevious: Bool
    var canGoNext: Bool
    var isCardInteractive: Bool
    var swipeIntensity: Double
}

struct ReviewTopBar: View, Equatable {
    @Environment(\.appSkin) private var appSkin

    let model: ReviewTopBarModel
    let onShuffle: () -> Void
    let onToggleAutoPlay: () -> Void
    let onToggleHelp: () -> Void
    let onClose: () -> Void

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.model == rhs.model
    }

    /// 播放中永遠可按(要能停);沒在播時,只有 autoplay 還有事可做才可按。
    /// 比照同列 shuffle chip 的 `canShuffle` 前例:停用 + 變淡,而不是沉默 no-op。
    private var isAutoplayActionable: Bool { model.isAutoPlaying || model.canAutoplay }

    private var autoplayTone: Color? {
        if model.isAutoPlaying { return appSkin.palette.accent }
        return isAutoplayActionable ? nil : appSkin.palette.quaternaryText
    }

    var body: some View {
        HStack(alignment: .center, spacing: AppSpacing.s3) {
            Text(model.progressText)
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
                guard model.isCardInteractive else { return }
                onShuffle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(appSkin.typography.iconTiny)
                    Text(TodayReviewShortcutCatalog.shuffleLabel)
                        .font(appSkin.typography.caption)
                }
                .foregroundStyle(model.canShuffle ? appSkin.palette.secondaryText : appSkin.palette.quaternaryText)
                .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, appSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    Capsule(style: .continuous)
                        .fill(appSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!model.canShuffle)

            Spacer()

            VocabChromeIconButton(
                systemImage: model.isAutoPlaying ? "play.circle.fill" : "play.circle",
                tone: autoplayTone,
                label: L10n.string(model.isAutoPlaying ? "vocab.chromeIcon.todayReview.autoplay.on" : "vocab.chromeIcon.todayReview.autoplay.off"),
                action: onToggleAutoPlay
            )
            .disabled(!isAutoplayActionable)
            // 穩定 identifier:此鍵的 a11y label 會隨播放狀態在「開啟/關閉自動播放」
            // 之間翻轉,UI 測試若靠 label 選取就會在狀態切換的那一刻選不到。
            .accessibilityIdentifier("todayReview.autoplayToggle")

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
}

struct ReviewToolbarControls: View, Equatable {
    @Environment(\.appSkin) private var appSkin
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let model: ReviewToolbarModel
    let onForgotTap: () -> Void
    let onRememberedTap: () -> Void
    let onPrevious: () -> Void
    let onNext: () -> Void
    let onToggleAutoPlayPause: () -> Void
    let onToggleAutoPlaySound: () -> Void
    let onChangeAutoPlaySpeed: () -> Void

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.model == rhs.model
    }

    var body: some View {
        Group {
            if model.isAutoPlaying {
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
        .animation(AppMotion.reviewNavigationSpring, value: model.showsAnswer)
        .animateSpring(model.isAutoPlaying)
    }

    // MARK: - Autoplay Controls

    private var autoplayControls: some View {
        VStack(spacing: TodayReviewMetrics.autoplayProgressBarBottomGap) {
            // Progress bar
            ProgressCapsule(
                progress: model.autoplayProgress,
                label: model.progressText,
                fillColor: appSkin.palette.accent,
                trackColor: appSkin.palette.mutedFill.opacity(0.5),
                labelFont: appSkin.typography.monoLabel,
                height: TodayReviewMetrics.autoplayProgressBarHeight
            )

            HStack(spacing: appSkin.metrics.sectionHeaderGap * 2) {
                Button {
                    guard model.isCardInteractive else { return }
                    onPrevious()
                } label: {
                    Image(systemName: "backward.end.fill")
                        .font(AppFonts.h2())
                }
                .disabled(!model.canGoPrevious)
                .accessibilityLabel(L10n.string("todayReview.autoplay.previous"))

                Button(action: onToggleAutoPlayPause) {
                    Image(systemName: model.isAutoPlayPaused ? "play.fill" : "pause.fill")
                        .font(AppFonts.h1())
                        .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                        .background(
                            Circle()
                                .fill(appSkin.palette.mutedFill)
                        )
                }
                .accessibilityLabel(L10n.string(model.isAutoPlayPaused ? "todayReview.autoplay.playpause.play" : "todayReview.autoplay.playpause.pause"))

                Button {
                    guard model.isCardInteractive else { return }
                    onNext()
                } label: {
                    Image(systemName: "forward.end.fill")
                        .font(AppFonts.h2())
                }
                .disabled(!model.canGoNext)
                .accessibilityLabel(L10n.string("todayReview.autoplay.next"))

                Button(action: onToggleAutoPlaySound) {
                    Image(systemName: model.autoplaySoundEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                        .font(appSkin.typography.iconSmall)
                        .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                        .background(
                            Circle()
                                .fill(appSkin.palette.mutedFill)
                        )
                }
                .accessibilityLabel(L10n.string(
                    model.autoplaySoundEnabled
                    ? "todayReview.autoplay.sound.off"
                    : "todayReview.autoplay.sound.on"
                ))

                // Speed pill
                Button(action: onChangeAutoPlaySpeed) {
                    Text(model.autoplaySpeedName)
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
                .accessibilityLabel(model.autoplaySpeedName)
            }
            .foregroundStyle(appSkin.palette.primaryText)
            .frame(maxWidth: .infinity)
        }
    }

    private var navButtons: some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Button { guard model.isCardInteractive else { return }; onPrevious() } label: {
                Image(systemName: "chevron.left").font(appSkin.typography.iconNavigation)
            }
            .disabled(!model.canGoPrevious)
            .accessibilityLabel(L10n.string("todayReview.nav.previous"))

            Button { guard model.isCardInteractive else { return }; onNext() } label: {
                Image(systemName: "chevron.right").font(appSkin.typography.iconNavigation)
            }
            .disabled(!model.canGoNext)
            .accessibilityLabel(L10n.string("todayReview.nav.next"))
        }
        .foregroundStyle(appSkin.palette.secondaryText)
    }

    // MARK: - Feedback Buttons

    private var feedbackButtons: some View {
        let spring = AppMotion.feedbackButtonSpring
        let buttonsDisabled = false

        return HStack(spacing: appSkin.metrics.sectionHeaderGap) {
            Button(action: onForgotTap) {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "xmark")
                    Text(L10n.string("忘記"))
                    if model.forgotCount > 0 {
                        Text("·\(model.forgotCount)").font(appSkin.typography.monoLabel)
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
            .animation(spring, value: model.swipeIntensity)

            Button(action: onRememberedTap) {
                HStack(spacing: AppSpacing.s1) {
                    Image(systemName: "checkmark")
                    Text(L10n.string("記得"))
                    if model.rememberedCount > 0 {
                        Text("·\(model.rememberedCount)").font(appSkin.typography.monoLabel)
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
            .animation(spring, value: model.swipeIntensity)
        }
    }

    // MARK: - Swipe ↔ Button Linkage（純 swipeIntensity 推導）

    private var forgotButtonScale: CGFloat   { 1.0 + CGFloat(max(-model.swipeIntensity, 0)) * 0.12 }
    private var forgotButtonOffset: CGFloat  { CGFloat(max(-model.swipeIntensity, 0)) * -4 }
    private var forgotButtonOpacity: Double  { 1.0 - max(model.swipeIntensity, 0) * 0.45 }
    private var forgotButtonGlow: Double     { max(-model.swipeIntensity, 0) }

    private var rememberedButtonScale: CGFloat   { 1.0 + CGFloat(max(model.swipeIntensity, 0)) * 0.12 }
    private var rememberedButtonOffset: CGFloat  { CGFloat(max(model.swipeIntensity, 0)) * -4 }
    private var rememberedButtonOpacity: Double  { 1.0 - max(-model.swipeIntensity, 0) * 0.45 }
    private var rememberedButtonGlow: Double     { max(model.swipeIntensity, 0) }
}

extension TodayReviewPresenter {
    // MARK: - Top Bar

    var topBar: some View {
        ReviewTopBar(
            model: ReviewTopBarModel(
                progressText: state.progressText,
                canShuffle: state.canShuffle,
                canAutoplay: state.canAutoplay,
                isAutoPlaying: state.isAutoPlaying,
                isCardInteractive: isCardInteractive
            ),
            onShuffle: onShuffle,
            onToggleAutoPlay: onToggleAutoPlay,
            onToggleHelp: onToggleHelp,
            onClose: onClose
        )
        .equatable()
    }

    // MARK: - Bottom Toolbar

    var bottomToolbar: some View {
        VStack(spacing: 10) {
            #if targetEnvironment(macCatalyst)
            shortcutRail
            #endif
            ReviewToolbarControls(
                model: ReviewToolbarModel(
                    showsAnswer: state.revealStage.showsAnswer,
                    isAutoPlaying: state.isAutoPlaying,
                    isAutoPlayPaused: state.isAutoPlayPaused,
                    autoplaySoundEnabled: state.autoplaySoundEnabled,
                    autoplaySpeedName: state.autoplaySpeed.displayName,
                    autoplayProgress: state.autoplayProgress,
                    progressText: state.progressText,
                    forgotCount: state.forgotCount,
                    rememberedCount: state.rememberedCount,
                    canGoPrevious: state.canGoPrevious,
                    canGoNext: state.canGoNext,
                    isCardInteractive: isCardInteractive,
                    swipeIntensity: swipeIntensity
                ),
                onForgotTap: { flingCard(direction: -1, source: "button", callback: onForgot) },
                onRememberedTap: { flingCard(direction: 1, source: "button", callback: onRemembered) },
                onPrevious: onPrevious,
                onNext: onNext,
                onToggleAutoPlayPause: onToggleAutoPlayPause,
                onToggleAutoPlaySound: onToggleAutoPlaySound,
                onChangeAutoPlaySpeed: onChangeAutoPlaySpeed
            )
            .equatable()
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

    // MARK: - Swipe ↔ Button Linkage（model 供料；feedback 按鈕的推導已隨子 view 下沉）

    var swipeIntensity: Double {
        if dismissPhase == .animatingOut { return frozenSwipeIntensity }
        guard swipeEnabled else { return 0 }
        return max(-1, min(1, Double(swipeOffset / TodayReviewMetrics.swipeThreshold)))
    }
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
