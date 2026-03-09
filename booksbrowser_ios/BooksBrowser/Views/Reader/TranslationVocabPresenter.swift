//
//  TranslationVocabPresenter.swift
//  BooksBrowser
//
//  TranslationPanel 的 Vocab-style 渲染器。
//  使用與 TranslationPanelPresenter 完全相同的 State + callbacks，
//  改以 VocabSkin 組件（VocabCard、VocabChromeIconButton 等）呈現。
//
//  ⚠️  若 TranslationPanelPresenterState 有更動，
//      本檔與 TranslationPanelPresenter 需同步確認。
//

import SwiftUI

struct TranslationVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: TranslationPanelPresenterState
    let onSpeak: () -> Void
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // ── Header ──────────────────────────────────────────────────
            VocabOverlayHeader(
                title: state.word,
                systemImage: "character.book.closed",
                badgeText: state.isSaved ? "已收錄" : nil,
                onClose: onDismiss
            )

            // ── Body ────────────────────────────────────────────────────
            ScrollView {
                VocabCard(padding: AppMetrics.spacingLarge) {
                    VStack(alignment: .leading, spacing: 14) {
                        heroSection
                        if state.isLoading {
                            loadingSection
                        } else {
                            bodySection
                        }
                    }
                }
                .padding(AppMetrics.spacingLarge)
                .padding(.bottom, AppMetrics.spacingMedium)
            }
            .scrollContentBackground(.hidden)

            // ── Footer Toolbar ──────────────────────────────────────────
            footerToolbar
                .padding(.horizontal, AppMetrics.spacingLarge)
                .padding(.vertical, 12)
        }
        .vocabCanvasBackground()
    }

    // MARK: - Sections

    private var heroSection: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            // 單字
            Text(state.word)
                .font(state.word.count > 12
                      ? vocabSkin.typography.translationTitle
                      : vocabSkin.typography.detailWord)
                .foregroundStyle(vocabSkin.palette.primaryText)

            // 音標
            if let pronunciation = state.pronunciation {
                Text(pronunciation)
                    .font(vocabSkin.typography.monoBody)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

            Spacer()

            // 朗讀按鈕
            VocabChromeIconButton(systemImage: "speaker.wave.2") {
                onSpeak()
            }

            // 詞性 Chip
            if let pos = state.partOfSpeech {
                VocabToneChip(text: pos, tone: vocabSkin.palette.accent)
            }
        }
    }

    @ViewBuilder
    private var bodySection: some View {
        if !state.isLoggedIn {
            guestSection
        } else if let translation = state.translation {
            translationSection(translation)
        }
    }

    private var loadingSection: some View {
        HStack(spacing: 8) {
            ProgressView().scaleEffect(0.8)
            Text((state.statusMessage ?? "翻譯中...").localized)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
            Spacer()
            Text(state.timerText)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
    }

    private var guestSection: some View {
        HStack(spacing: 6) {
            Image(systemName: state.isSaved ? "checkmark.circle.fill" : "clock")
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(state.isSaved ? vocabSkin.palette.success : vocabSkin.palette.accent)
            Text((state.isSaved ? "已加入待收錄" : "正在記錄…").localized)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(state.isSaved ? vocabSkin.palette.success : vocabSkin.palette.accent)
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 12)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .fill((state.isSaved ? vocabSkin.palette.success : vocabSkin.palette.accent).opacity(0.08))
        )
    }

    private func translationSection(_ translation: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            // 翻譯
            Text(translation)
                .font(vocabSkin.typography.translationTitle)
                .foregroundStyle(vocabSkin.palette.translationText)
                .frame(maxWidth: .infinity, alignment: .leading)

            // 解釋（展開後 or isExplanationOnly）
            if state.isExpanded || state.isExplanationOnly {
                CardSectionDivider()

                Label("語境解釋", systemImage: "text.bubble")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)

                if state.isLoadingExplanation {
                    HStack(spacing: 8) {
                        ProgressView().scaleEffect(0.7)
                        Text((state.statusMessage ?? "載入解釋...").localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                        Spacer()
                        Text(state.timerText)
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.quaternaryText)
                    }
                } else if let explanation = state.explanation {
                    Text(explanation)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                        .lineSpacing(3)
                }
            }
        }
    }

    // MARK: - Footer Toolbar

    private var footerToolbar: some View {
        HStack(spacing: 4) {
            // 已加入標籤
            if state.isSaved && state.isLoggedIn {
                Label("已加入", systemImage: "checkmark.circle.fill")
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.success)
                    .symbolEffect(.bounce, value: state.isSaved)
                    .transition(.scale(scale: 0.8).combined(with: .opacity))
            }

            // Timer
            if !state.timerText.isEmpty && (state.isLoading || state.isLoadingExplanation) {
                Text(state.timerText)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }

            Spacer()

            // 展開按鈕（僅在翻譯存在時顯示）
            if state.isLoggedIn && state.translation != nil && !state.isExplanationOnly {
                VocabChromeIconButton(
                    systemImage: state.isExpanded ? "chevron.up" : "chevron.down",
                    action: onExpand
                )
            }

            // 刪除按鈕（已收錄時）
            if state.isSaved {
                VocabChromeIconButton(
                    systemImage: "trash",
                    tone: vocabSkin.palette.destructive,
                    action: onDelete
                )
            }
        }
    }
}
