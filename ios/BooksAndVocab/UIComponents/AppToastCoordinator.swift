import SwiftUI

struct AppToastItem: Identifiable, Equatable {
    let id = UUID()
    let message: String
    let systemImage: String
    let style: Style

    enum Style {
        case success, info, warning, error

        var defaultImage: String {
            switch self {
            case .success: "checkmark"
            case .info: "info.circle"
            case .warning: "exclamationmark.triangle"
            case .error: "xmark.circle"
            }
        }
    }

    var duration: TimeInterval {
        switch style {
        case .success, .info: 2.5
        case .warning, .error: 4.0
        }
    }

    init(message: String, systemImage: String? = nil, style: Style) {
        self.message = message
        self.systemImage = systemImage ?? style.defaultImage
        self.style = style
    }
}

/// `AppToastCoordinator` 的計時 seam：`delay` 後在 main actor 執行 `action`。
/// 生產走 `AppToastTaskScheduler`（`Task.sleep`）；測試注入手動推進的假時間，
/// 不必真的等待計時器。
protocol AppToastScheduler {
    /// 回傳的 handle 被 `cancel()` 後，`action` 不再執行。
    @MainActor
    func schedule(
        after delay: Duration,
        _ action: @escaping @MainActor () -> Void
    ) -> AppToastScheduledAction
}

/// 已排程的動作。`cancel()` 對已執行或已取消的動作是 no-op。
@MainActor
struct AppToastScheduledAction {
    private let cancelAction: @MainActor () -> Void

    init(cancel: @escaping @MainActor () -> Void) {
        cancelAction = cancel
    }

    func cancel() {
        cancelAction()
    }
}

/// 生產用計時：每個動作一個 `Task`，取消即取消該 `Task`。
struct AppToastTaskScheduler: AppToastScheduler {
    func schedule(
        after delay: Duration,
        _ action: @escaping @MainActor () -> Void
    ) -> AppToastScheduledAction {
        let task = Task { @MainActor in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            action()
        }
        return AppToastScheduledAction { task.cancel() }
    }
}

@Observable @MainActor
final class AppToastCoordinator {
    private(set) var current: AppToastItem?
    private let scheduler: any AppToastScheduler
    @ObservationIgnored private var pendingDismiss: AppToastScheduledAction?

    init(scheduler: any AppToastScheduler = AppToastTaskScheduler()) {
        self.scheduler = scheduler
    }

    func show(_ item: AppToastItem) {
        pendingDismiss?.cancel()
        withAnimation(AppMotion.panelState) {
            current = item
        }
        // Announce for VoiceOver (side effect only). The auto-dismiss MUST still
        // be scheduled regardless — otherwise the toast never clears when
        // VoiceOver is on, leaving `current` stuck forever.
        _ = PlatformAccessibility.announceIfVoiceOver(item.message)
        pendingDismiss = scheduler.schedule(after: .seconds(item.duration)) { [weak self] in
            self?.dismiss()
        }
    }

    func dismiss() {
        pendingDismiss?.cancel()
        pendingDismiss = nil
        withAnimation(AppMotion.panelState) {
            current = nil
        }
    }

    func success(_ message: String) {
        show(AppToastItem(message: message, style: .success))
    }

    func info(_ message: String) {
        show(AppToastItem(message: message, style: .info))
    }

    func warning(_ message: String) {
        show(AppToastItem(message: message, style: .warning))
    }

    func error(_ message: String) {
        show(AppToastItem(message: message, style: .error))
    }
}
