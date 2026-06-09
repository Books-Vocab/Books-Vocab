import SwiftUI

extension SyncPresenter {

    // MARK: - Action Area

    var actionArea: some View {
        VStack(spacing: AppSpacing.s2) {
            switch state.phase {
            case .ready:
                if state.isLoggedIn {
                    Button(action: onPrimaryAction) {
                        Label("開始同步".localized, systemImage: "arrow.triangle.2.circlepath")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.primary))
                    .disabled(!state.isConnected)

                    if !state.isConnected {
                        Text("Books & Vocab 服務未連線".localized)
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.destructive)
                    }
                } else {
                    Button(action: onShowSettings) {
                        Text("前往設定登入".localized)
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.neutral))
                }
            case .running:
                Button(role: .cancel, action: onCancel) {
                    Text("取消".localized)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
            case .completed:
                Button("完成".localized) { dismiss() }
                    .frame(maxWidth: .infinity)
                    .buttonStyle(.vocabAction(.primary))
            case .failed:
                Button(action: onPrimaryAction) {
                    Label(state.failureKind == .partial ? "重試失敗項目".localized : "重試".localized, systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(state.failureKind == .full ? .warning : .neutral))
            }
        }
    }

    // MARK: - Summary Card

    var summaryCard: some View {
        VocabStateMessageCard(
            title: summaryTitle,
            systemImage: summaryIcon,
            description: state.summaryText
        )
    }

    var summaryTitle: String {
        switch state.failureKind {
        case .partial:
            return "有些項目需要再試一次".localized
        case .cancelled:
            return "同步在中途停止".localized
        case .full:
            return "同步沒有完成".localized
        case nil:
            return state.phase == .completed ? "同步完成".localized : "同步摘要".localized
        }
    }

    var summaryIcon: String {
        switch state.failureKind {
        case .partial:
            return "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90"
        case .cancelled:
            return "pause.circle"
        case .full:
            return "exclamationmark.triangle.fill"
        case nil:
            return state.phase == .completed ? "checkmark.circle.fill" : "text.alignleft"
        }
    }
}
