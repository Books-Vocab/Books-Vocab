import SwiftUI

/// Vocabulary 場景四態
enum VocabScenePhase {
    /// 居中狀態卡片 + 小 spinner（非 list 場景，如圖譜 / 統計）
    case loading(title: String, systemImage: String)
    /// list 場景首次載入 — 以 AppSkeletonCard 骨架佔位，比裸 spinner 更貼近最終版面
    case loadingSkeleton(rowCount: Int = 6)
    case empty(title: String, systemImage: String, description: String, action: AppEmptyStateAction? = nil)
    case error(title: String, systemImage: String, retryAction: () -> Void)
    case content
}

/// 統一 Vocabulary 場景的四態容器
/// loading / empty / error → 居中狀態卡片 + vocabCanvasBackground
/// loadingSkeleton → 骨架列表 + vocabCanvasBackground
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

        case .loadingSkeleton(let rowCount):
            ScrollView {
                VStack(spacing: AppSpacing.s3) {
                    ForEach(0..<rowCount, id: \.self) { _ in
                        AppSkeletonCard(lineCount: 2)
                    }
                }
                .padding(vocabSkin.metrics.cardBlockPadding)
            }
            .vocabCanvasBackground()
            .allowsHitTesting(false)

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

#Preview("Loading Skeleton") {
    AppThemeContainer {
        VocabSceneShell(phase: .loadingSkeleton()) {
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
