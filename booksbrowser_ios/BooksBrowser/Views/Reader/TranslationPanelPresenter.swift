import SwiftUI

struct TranslationPanelPresenterState {
    let word: String
    let pronunciation: String?
    let partOfSpeech: String?
    let translation: String?
    let isLoading: Bool
    let isSaved: Bool
    let isLoggedIn: Bool
    let isExpanded: Bool
    let explanation: String?
    let isLoadingExplanation: Bool
    let statusMessage: String?
    let isExplanationOnly: Bool
    let timerText: String
    let isSpeaking: Bool
}

struct TranslationPanelPresenter: View {
    @Environment(\.colorScheme) private var colorScheme

    let state: TranslationPanelPresenterState
    let onSpeak: () -> Void
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        GlassEffectContainer {
            VStack(spacing: 0) {
                Capsule()
                    .fill(.quaternary)
                    .frame(width: 32, height: 4)
                    .padding(.top, 8)
                    .padding(.bottom, 10)

                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(state.word)
                            .font(.system(size: 24, weight: .bold, design: .rounded))

                        if let pronunciation = state.pronunciation {
                            Text(pronunciation)
                                .font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }

                        Button(action: onSpeak) {
                            Image(systemName: "speaker.wave.2.fill")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                                .symbolEffect(.bounce, value: state.isSpeaking)
                        }

                        Spacer()

                        if let partOfSpeech = state.partOfSpeech {
                            Text(partOfSpeech)
                                .font(.caption)
                                .fontWeight(.medium)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(AppColors.accent(colorScheme).opacity(0.12))
                                .foregroundStyle(AppColors.accent(colorScheme))
                                .clipShape(Capsule())
                        }
                    }

                    panelBody
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 16)
            }
        }
        .glassEffect(in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.06), radius: 12, y: -3)
    }

    @ViewBuilder
    private var panelBody: some View {
        if state.isLoading {
            HStack(spacing: 8) {
                ProgressView().scaleEffect(0.8)
                Text((state.statusMessage ?? "翻譯中...").localized)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                Spacer()
                Text(state.timerText)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }
            .padding(.vertical, 12)
        } else if !state.isLoggedIn {
            guestModeBody
        } else if state.isExplanationOnly {
            explanationOnlyBody
        } else if let translation = state.translation {
            translationBody(translation)
        }
    }

    private var guestModeBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: state.isSaved ? "checkmark.circle.fill" : "clock")
                        .font(.caption)
                        .foregroundStyle(state.isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme))
                    Text((state.isSaved ? "已加入待收錄" : "正在記錄…").localized)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(state.isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme))
                }

                Text("登入後即可獲得 AI 翻譯，並同步至知識庫。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.vertical, 8)
            .padding(.horizontal, 10)
            .background((state.isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme)).opacity(0.06))
            .clipShape(RoundedRectangle(cornerRadius: 10))

            panelToolbar(showChevron: false, timerValue: nil)
        }
    }

    private var explanationOnlyBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider()
                .padding(.vertical, 2)

            Label("語境解釋", systemImage: "text.bubble")
                .font(.caption2)
                .foregroundStyle(.tertiary)

            if state.isLoadingExplanation {
                HStack(spacing: 8) {
                    ProgressView().scaleEffect(0.7)
                    Text((state.statusMessage ?? "載入解釋...").localized)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(state.timerText)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 4)
            } else if let explanation = state.explanation {
                Text(explanation)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineSpacing(3)
            }

            panelToolbar(showChevron: false, timerValue: state.timerText.isEmpty ? nil : state.timerText)
        }
    }

    private func translationBody(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(translation)
                .font(.title3)
                .fontWeight(.semibold)

            if state.isExpanded {
                Divider()
                    .padding(.vertical, 2)

                Label("語境解釋", systemImage: "text.bubble")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)

                if state.isLoadingExplanation {
                    HStack(spacing: 8) {
                        ProgressView().scaleEffect(0.7)
                        Text((state.statusMessage ?? "載入解釋...").localized)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(state.timerText)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.vertical, 4)
                } else if let explanation = state.explanation {
                    Text(explanation)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineSpacing(3)
                }
            }

            panelToolbar(showChevron: state.isLoggedIn, timerValue: state.timerText.isEmpty ? nil : state.timerText)
        }
    }

    @ViewBuilder
    private func panelToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            if state.isSaved && state.isLoggedIn {
                Label("已加入", systemImage: "checkmark.circle.fill")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(AppColors.saved(colorScheme))
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.scale(scale: 0.8).combined(with: .opacity))
            }

            if let timerValue {
                Text(timerValue)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .padding(.leading, state.isSaved && state.isLoggedIn ? 8 : 0)
            }

            Spacer()

            if showChevron {
                Button(action: onExpand) {
                    Image(systemName: state.isExpanded ? "chevron.up" : "chevron.down")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                        .symbolEffect(.bounce, value: state.isExpanded)
                        .glassEffect(.clear, in: Circle())
                }
            }

            if state.isSaved {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(.callout)
                        .foregroundStyle(AppColors.destructive(colorScheme).opacity(0.65))
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                        .glassEffect(.clear, in: Circle())
                }
            }

            Button(action: onDismiss) {
                Image(systemName: "xmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(.tertiary)
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
                    .glassEffect(.clear, in: Circle())
            }
        }
        .padding(.top, 2)
    }
}
