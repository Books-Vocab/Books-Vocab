import SwiftUI

/// Vocabulary 場景四態
enum VocabScenePhase {
    case loading(title: String, systemImage: String)
    case empty(title: String, systemImage: String, description: String, action: AppEmptyStateAction? = nil)
    case error(title: String, systemImage: String, retryAction: () -> Void)
    case content
}

/// 統一 Vocabulary 場景的四態容器
/// loading / empty / error → 居中狀態卡片 + vocabCanvasBackground
/// content → 直接呈現 content()
struct VocabSceneShell<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let phase: VocabScenePhase
    @ViewBuilder let content: Content

    init(
        phase: VocabScenePhase,
        @ViewBuilder content: () -> Content
    ) {
        self.phase = phase
        self.content = content()
    }

    var body: some View {
        switch phase {
        case .loading(let title, let systemImage):
            centeredWrapper {
                VocabStateMessageCard(
                    title: title,
                    systemImage: systemImage
                ) {
                    ProgressView()
                        .controlSize(.small)
                }
            }

        case .empty(let title, let systemImage, let description, let action):
            centeredWrapper {
                VocabEmptyStateCard(
                    title: title,
                    systemImage: systemImage,
                    description: description,
                    action: action
                )
            }

        case .error(let title, let systemImage, let retryAction):
            centeredWrapper {
                VocabStateMessageCard(
                    title: title,
                    systemImage: systemImage
                ) {
                    Button("重試".localized, action: retryAction)
                        .buttonStyle(.vocabAction())
                }
            }

        case .content:
            content
        }
    }

    @ViewBuilder
    private func centeredWrapper<V: View>(@ViewBuilder card: () -> V) -> some View {
        VStack {
            Spacer()
            card()
            Spacer()
        }
        .padding(vocabSkin.metrics.cardBlockPadding)
        .vocabCanvasBackground()
    }
}

// MARK: - Preview

#Preview("Loading") {
    AppThemeContainer {
        VocabSceneShell(phase: .loading(
            title: "載入中...",
            systemImage: "arrow.clockwise"
        )) {
            EmptyView()
        }
    }
}

#Preview("Empty") {
    AppThemeContainer {
        VocabSceneShell(phase: .empty(
            title: "尚無已收錄單字",
            systemImage: "sparkles",
            description: "同步完成後，這裡會顯示你的雲端單字。"
        )) {
            EmptyView()
        }
    }
}

#Preview("Error") {
    AppThemeContainer {
        VocabSceneShell(phase: .error(
            title: "無法載入",
            systemImage: "exclamationmark.triangle",
            retryAction: {}
        )) {
            EmptyView()
        }
    }
}

#Preview("Content") {
    AppThemeContainer {
        VocabSceneShell(phase: .content) {
            Text("Content goes here")
        }
    }
}
