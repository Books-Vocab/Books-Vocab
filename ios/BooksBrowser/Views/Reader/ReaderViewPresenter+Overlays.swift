import SwiftUI

extension ReaderViewPresenter {
    var loadingOverlay: some View {
        Group {
            if state.panelMode == .vocab {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        AppSectionCard(style: .vocab(vocabSkin)) {
                            VStack(spacing: ReaderPresentationMetrics.Overlay.loadingSpacing) {
                                ProgressView()
                                    .tint(vocabSkin.palette.primaryText)
                                Text(state.loadingPhase)
                                    .font(vocabSkin.typography.body.weight(.semibold))
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                    .contentTransition(.numericText())
                                    .animation(AppMotion.loadingState, value: state.loadingPhase)
                            }
                            .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingHorizontalInset)
                            .padding(.vertical, ReaderPresentationMetrics.Overlay.loadingVerticalInset)
                        }
                        .frame(maxWidth: ReaderPresentationMetrics.Overlay.loadingMaxWidth)
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingOuterInset)
                    }
            } else {
                state.paperColor.ignoresSafeArea()
                    .overlay {
                        VStack(spacing: ReaderPresentationMetrics.Overlay.loadingSpacing) {
                            ProgressView()
                                .tint(vocabSkin.palette.primaryText)
                            Text(state.loadingPhase)
                                .font(ReaderGlassTypography.body)
                                .fontWeight(.medium)
                                .foregroundStyle(vocabSkin.palette.primaryText)
                                .contentTransition(.numericText())
                                .animation(AppMotion.loadingState, value: state.loadingPhase)
                        }
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.loadingHorizontalInset)
                        .padding(.vertical, ReaderPresentationMetrics.Overlay.loadingVerticalInset)
                        .glassEffect(
                            .regular,
                            in: .rect(cornerRadius: ReaderPresentationMetrics.Panel.cornerRadius)
                        )
                    }
            }
        }
    }

    func underlineProgressOverlay(_ progress: Double) -> some View {
        VStack {
            Group {
                if state.panelMode == .vocab {
                    AppSectionCard(style: .vocab(vocabSkin)) {
                        HStack(spacing: 10) {
                            ZStack(alignment: .leading) {
                                Capsule()
                                    .fill(vocabSkin.palette.mutedFill)
                                    .frame(
                                        width: ReaderPresentationMetrics.Overlay.progressBarWidth,
                                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                    )
                                Capsule()
                                    .fill(vocabSkin.palette.accent)
                                    .frame(
                                        width: max(
                                            ReaderPresentationMetrics.Overlay.progressBarHeight,
                                            ReaderPresentationMetrics.Overlay.progressBarWidth * progress
                                        ),
                                        height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                    )
                                    .animation(AppMotion.progressLinear, value: progress)
                            }
                            Text("\(Int(progress * 100))%")
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .frame(width: ReaderPresentationMetrics.Overlay.progressTextWidth, alignment: .trailing)
                        }
                        .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                        .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    }
                } else {
                    HStack(spacing: 10) {
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(vocabSkin.palette.divider)
                                .frame(
                                    width: ReaderPresentationMetrics.Overlay.progressBarWidth,
                                    height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                )
                            Capsule()
                                .fill(Color.accentColor)
                                .frame(
                                    width: max(
                                        ReaderPresentationMetrics.Overlay.progressBarHeight,
                                        ReaderPresentationMetrics.Overlay.progressBarWidth * progress
                                    ),
                                    height: ReaderPresentationMetrics.Overlay.progressBarHeight
                                )
                                .animation(AppMotion.progressLinear, value: progress)
                        }
                        Text("\(Int(progress * 100))%")
                            .font(ReaderGlassTypography.progressText)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .frame(width: ReaderPresentationMetrics.Overlay.progressTextWidth, alignment: .trailing)
                    }
                    .padding(.horizontal, ReaderPresentationMetrics.Overlay.progressHorizontalInset)
                    .padding(.vertical, ReaderPresentationMetrics.Overlay.progressVerticalInset)
                    .glassEffect(.regular, in: .capsule)
                }
            }
            .padding(.top, ReaderPresentationMetrics.Overlay.topInset)

            Spacer()
        }
        .allowsHitTesting(false)
        .transition(.overlayFade)
    }

    var bottomOverlay: some View {
        VStack {
            Spacer()

            if state.chrome.overlay == .translation {
                translationPanel
                    .frame(maxWidth: ReaderPresentationMetrics.Overlay.panelMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
                    .transition(.readerPanelReveal)
            } else if state.chrome.overlay == .settings && state.panelMode == .vocab {
                settingsPanel
                    .frame(maxWidth: ReaderPresentationMetrics.Overlay.panelMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal)
                    .padding(.bottom, ReaderPresentationMetrics.Overlay.bottomInset)
                    .transition(.readerPanelReveal)
            }
        }
        .animation(AppMotion.panelState, value: state.chrome.overlay)
    }
}
