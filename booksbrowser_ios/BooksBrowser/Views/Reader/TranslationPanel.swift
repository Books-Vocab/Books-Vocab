//
//  TranslationPanel.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI

/// 毛玻璃翻譯面板 — 支援收合/展開兩階段
struct TranslationPanel: View {
    @Environment(\.colorScheme) private var colorScheme
    let word: String
    let result: TranslationResult?
    let pronunciation: String?
    let isLoading: Bool
    let isSaved: Bool
    let isLoggedIn: Bool

    // Phase 2 展開
    let isExpanded: Bool
    let explanation: String?
    let isLoadingExplanation: Bool
    let statusMessage: String?

    let isExplanationOnly: Bool
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onDismiss: () -> Void

    @State private var dragOffset: CGFloat = 0
    @State private var isSpeaking = false
    @State private var elapsedTime: Double = 0

    private let ticker = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()
    private var isActive: Bool { isLoading || isLoadingExplanation }
    private var timerText: String { String(format: "%.1fs", elapsedTime) }

    var body: some View {
        GlassEffectContainer {
            VStack(spacing: 0) {
            // 拖曳把手
            Capsule()
                .fill(.quaternary)
                .frame(width: 32, height: 4)
                .padding(.top, 8)
                .padding(.bottom, 10)

            // 內容
            VStack(alignment: .leading, spacing: 10) {
                // 第一行：單字 + 音標 + 詞性
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(word)
                        .font(.system(size: 24, weight: .bold, design: .rounded))

                    if let pron = pronunciation {
                        Text(pron)
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }

                    // 播放發音
                    Button {
                        SpeechService.shared.speak(word)
                        isSpeaking.toggle()
                    } label: {
                        Image(systemName: "speaker.wave.2.fill")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .symbolEffect(.bounce, value: isSpeaking)
                    }

                    Spacer()

                    if let pos = result?.partOfSpeech {
                        Text(pos)
                            .font(.caption)
                            .fontWeight(.medium)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(AppColors.accent(colorScheme).opacity(0.12))
                            .foregroundStyle(AppColors.accent(colorScheme))
                            .clipShape(Capsule())
                    }
                }

                if isLoading {
                    HStack(spacing: 8) {
                        ProgressView().scaleEffect(0.8)
                        Text(statusMessage ?? "翻譯中...")
                            .foregroundStyle(.secondary)
                            .font(.subheadline)
                        Spacer()
                        Text(timerText)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.vertical, 12)

                } else if !isLoggedIn {
                    // 訪客模式
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 6) {
                            Image(systemName: isSaved ? "checkmark.circle.fill" : "clock")
                                .font(.caption)
                                .foregroundStyle(isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme))
                            Text(isSaved ? "已加入待收錄" : "正在記錄…")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme))
                        }

                        Text("登入後即可獲得 AI 翻譯，並同步至知識庫。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.vertical, 8)
                    .padding(.horizontal, 10)
                    .background((isSaved ? AppColors.saved(colorScheme) : AppColors.accent(colorScheme)).opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                    panelToolbar(showChevron: false, timerValue: nil)
                    
                } else if isExplanationOnly {
                    // Flow 3: 純語境解釋，無翻譯結果
                    Divider()
                        .padding(.vertical, 2)

                    Label("語境解釋", systemImage: "text.bubble")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)

                    if isLoadingExplanation {
                        HStack(spacing: 8) {
                            ProgressView().scaleEffect(0.7)
                            Text(statusMessage ?? "載入解釋...")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(timerText)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                    } else if let explanation = explanation {
                        Text(explanation)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .lineSpacing(3)
                    }

                    panelToolbar(showChevron: false, timerValue: elapsedTime > 0 && !isLoadingExplanation ? timerText : nil)

                } else if let result = result {
                    // 翻譯結果
                    Text(result.translation)
                        .font(.title3)
                        .fontWeight(.semibold)

                    // Phase 2：展開的解釋
                    if isExpanded {
                        Divider()
                            .padding(.vertical, 2)

                        Label("語境解釋", systemImage: "text.bubble")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)

                        if isLoadingExplanation {
                            HStack(spacing: 8) {
                                ProgressView().scaleEffect(0.7)
                                Text(statusMessage ?? "載入解釋...")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(timerText)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 4)
                        } else if let explanation = explanation {
                            Text(explanation)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .lineSpacing(3)
                        }
                    }

                    panelToolbar(showChevron: isLoggedIn, timerValue: elapsedTime > 0 ? timerText : nil)
                }
            }
            .padding(.horizontal, 18)
            .padding(.bottom, 16)
        }
        .glassEffect(in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.06), radius: 12, y: -3)
        .offset(y: dragOffset)
        .gesture(
            DragGesture()
                .onChanged { value in
                    if value.translation.height > 0 {
                        dragOffset = value.translation.height
                    }
                }
                .onEnded { value in
                    if value.translation.height > 100 {
                        onDismiss()
                    }
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                        dragOffset = 0
                    }
                }
        )
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .sensoryFeedback(.success, trigger: isSaved)
        .onReceive(ticker) { _ in
            if isActive { elapsedTime += 0.1 }
        }
        .onChange(of: isLoading) { _, new in
            if new { elapsedTime = 0 }
        }
        .onChange(of: isLoadingExplanation) { _, new in
            if new { elapsedTime = 0 }
        }
        }
    }

    @ViewBuilder
    private func panelToolbar(showChevron: Bool, timerValue: String?) -> some View {
        HStack(spacing: 4) {
            // 左側：已加入標記（登入模式）/ 計時器
            if isSaved && isLoggedIn {
                Label("已加入", systemImage: "checkmark.circle.fill")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(AppColors.saved(colorScheme))
                    .symbolEffect(.bounce, value: isSaved)
                    .transition(.scale(scale: 0.8).combined(with: .opacity))
            }
            if let t = timerValue {
                Text(t)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .padding(.leading, isSaved && isLoggedIn ? 8 : 0)
            }

            Spacer()

            // 展開/收合（僅登入 + 有翻譯）
            if showChevron {
                Button(action: onExpand) {
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                        .symbolEffect(.bounce, value: isExpanded)
                        .glassEffect(.clear, in: Circle())
                }
            }

            // 刪除（已收錄）
            if isSaved {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(.callout)
                        .foregroundStyle(AppColors.destructive(colorScheme).opacity(0.65))
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                        .glassEffect(.clear, in: Circle())
                }
            }

            // 關閉
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

#Preview {
    ZStack {
        Color.gray.opacity(0.3).ignoresSafeArea()

        VStack {
            Spacer()

            TranslationPanel(
                word: "gorgeous",
                result: TranslationResult(
                    translation: "華麗的",
                    partOfSpeech: "adj.",
                    pronunciation: nil,
                    explanation: nil
                ),
                pronunciation: "/ɡɔːrˈdʒəs/",
                isLoading: false,
                isSaved: true,
                isLoggedIn: false,
                isExpanded: false,
                explanation: nil,
                isLoadingExplanation: false,
                statusMessage: nil,
                isExplanationOnly: false,
                onExpand: {},
                onDelete: {},
                onDismiss: {}
            )
            .padding(.horizontal)
        }
    }
}
