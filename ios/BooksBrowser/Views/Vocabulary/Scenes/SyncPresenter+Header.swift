import SwiftUI

extension SyncPresenter {

    // MARK: - Header View

    @ViewBuilder
    var headerView: some View {
        if !state.isLoggedIn {
            VocabStatusHero(
                systemImage: "person.crop.circle.badge.exclamationmark",
                tone: vocabSkin.palette.tertiaryText,
                title: "尚未登入帳號".localized,
                description: "登入後即可將您的生詞庫同步至雲端知識庫。".localized
            )
        } else {
            switch state.phase {
            case .ready:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: state.pendingCount == 0
                        ? "強制同步到知識庫".localized
                        : L10n.format("%@ 個待處理動作", "\(state.pendingCount)")
                ) {
                    HStack(spacing: vocabSkin.spacing.inlineGap) {
                        if state.addCount > 0 {
                            VocabToneChip(
                                text: L10n.format("%@ 新增", "\(state.addCount)"),
                                tone: vocabSkin.palette.success
                            )
                        }
                        if state.deleteCount > 0 {
                            VocabToneChip(
                                text: L10n.format("%@ 刪除", "\(state.deleteCount)"),
                                tone: vocabSkin.palette.destructive
                            )
                        }
                    }
                }
                .transition(.blurReplace)
            case .running:
                VocabStatusHero(
                    systemImage: "arrow.triangle.2.circlepath",
                    tone: vocabSkin.palette.accent,
                    title: "同步中…".localized,
                    description: "離開後同步將繼續在背景執行，可隨時返回查看進度".localized
                ) {
                    ProgressView()
                        .controlSize(.large)
                }
                .transition(.blurReplace)
            case .completed:
                VocabStatusHero(
                    systemImage: "checkmark.circle.fill",
                    tone: vocabSkin.palette.success,
                    title: "同步完成".localized
                )
                .transition(.blurReplace)
            case .failed:
                failedHero
                .transition(.blurReplace)
            }
        }
    }

    // MARK: - Failed Hero

    @ViewBuilder
    var failedHero: some View {
        switch state.failureKind {
        case .partial:
            VocabStatusHero(
                systemImage: "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90",
                tone: vocabSkin.palette.warning,
                title: "部分同步完成".localized,
                description: "已完成的步驟會保留，失敗項目可直接重試。".localized
            )
        case .cancelled:
            VocabStatusHero(
                systemImage: "pause.circle.fill",
                tone: vocabSkin.palette.warning,
                title: "同步已取消".localized,
                description: "目前進度已停止，可在準備好後重新開始。".localized
            )
        default:
            VocabStatusHero(
                systemImage: "exclamationmark.triangle.fill",
                tone: vocabSkin.palette.destructive,
                title: "同步失敗".localized,
                description: "請檢查網路、登入狀態或伺服器健康後再試。".localized
            )
        }
    }
}
