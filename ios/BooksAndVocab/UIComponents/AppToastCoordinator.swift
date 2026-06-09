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

@Observable @MainActor
final class AppToastCoordinator {
    private(set) var current: AppToastItem?
    private var dismissTask: Task<Void, Never>?

    func show(_ item: AppToastItem) {
        dismissTask?.cancel()
        withAnimation(AppMotion.panelState) {
            current = item
        }
        // Announce for VoiceOver (side effect only). The auto-dismiss MUST still
        // be scheduled regardless — otherwise the toast never clears when
        // VoiceOver is on, leaving `current` stuck forever.
        _ = PlatformAccessibility.announceIfVoiceOver(item.message)
        dismissTask = Task {
            try? await Task.sleep(for: .seconds(item.duration))
            guard !Task.isCancelled else { return }
            dismiss()
        }
    }

    func dismiss() {
        dismissTask?.cancel()
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
