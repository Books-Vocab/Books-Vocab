//
//  TranslationPanel.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI

// MARK: - Environment Key

private struct ReaderPanelModeKey: EnvironmentKey {
    static let defaultValue: TranslationPanelMode = .glass
}

extension EnvironmentValues {
    var readerPanelMode: TranslationPanelMode {
        get { self[ReaderPanelModeKey.self] }
        set { self[ReaderPanelModeKey.self] = newValue }
    }
}

struct TranslationPanel: View {
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
    private var presenterState: TranslationPanelPresenterState {
        .init(
            word: word,
            pronunciation: pronunciation,
            partOfSpeech: result?.partOfSpeech,
            translation: result?.translation,
            isLoading: isLoading,
            isSaved: isSaved,
            isLoggedIn: isLoggedIn,
            isExpanded: isExpanded,
            explanation: explanation,
            isLoadingExplanation: isLoadingExplanation,
            statusMessage: statusMessage,
            isExplanationOnly: isExplanationOnly,
            timerText: timerText,
            isSpeaking: isSpeaking
        )
    }

    var body: some View {
        // ⚠️ TranslationPanelPresenterState 若有更動，
        //    TranslationPanelPresenter 與 TranslationVocabPresenter 需同步確認。
        panelContent
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

    // MARK: - 模式分支

    @Environment(\.readerPanelMode) private var panelMode

    @ViewBuilder
    private var panelContent: some View {
        switch panelMode {
        case .glass:
            TranslationPanelPresenter(
                state: presenterState,
                onSpeak: { SpeechService.shared.speak(word); isSpeaking.toggle() },
                onExpand: onExpand,
                onDelete: onDelete,
                onDismiss: onDismiss
            )
        case .vocab:
            TranslationVocabPresenter(
                state: presenterState,
                onSpeak: { SpeechService.shared.speak(word); isSpeaking.toggle() },
                onExpand: onExpand,
                onDelete: onDelete,
                onDismiss: onDismiss
            )
        }
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
