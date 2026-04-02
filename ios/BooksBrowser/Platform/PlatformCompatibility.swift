//
//  PlatformCompatibility.swift
//  BooksBrowser
//
//  iOS-only SwiftUI modifier 的跨平台 wrapper
//

import SwiftUI
import StoreKit
#if os(macOS)
import AppKit
#endif

enum MacKeyPress {
    case space
    case leftArrow
    case rightArrow
    case upArrow
    case downArrow
    case escape
    case character(String)
}

extension View {
    @ViewBuilder
    func inlineNavigationBarTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }

    @ViewBuilder
    func largeNavigationBarTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.large)
        #else
        self
        #endif
    }

    @ViewBuilder
    func platformFullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        #if os(iOS)
        self.fullScreenCover(isPresented: isPresented, onDismiss: onDismiss, content: content)
        #else
        self.sheet(isPresented: isPresented, onDismiss: onDismiss, content: content)
        #endif
    }

    @ViewBuilder
    func platformFullScreenCover<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        #if os(iOS)
        self.fullScreenCover(item: item, onDismiss: onDismiss, content: content)
        #else
        self.sheet(item: item, onDismiss: onDismiss, content: content)
        #endif
    }

    func dismissKeyboard() {
        #if os(iOS)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
        #endif
    }

    @ViewBuilder
    func macKeyResponder(
        active: Bool = true,
        onKeyPress: @escaping (MacKeyPress) -> Bool
    ) -> some View {
        #if os(macOS)
        background(
            MacKeyResponderRepresentable(active: active, onKeyPress: onKeyPress)
                .frame(width: 0, height: 0)
        )
        #else
        self
        #endif
    }

    @ViewBuilder
    func platformTextInputConfig() -> some View {
        #if os(iOS)
        self.textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        self.autocorrectionDisabled()
        #endif
    }

    @ViewBuilder
    func platformListButtonStyle() -> some View {
        #if os(iOS)
        self.buttonStyle(.pressable)
        #else
        self.buttonStyle(.plain)
        #endif
    }

    @ViewBuilder
    func platformContentMaxWidth(for layoutMode: LayoutMode) -> some View {
        self.frame(maxWidth: layoutMode.contentMaxWidth)
            .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    func platformHideNavigationBar() -> some View {
        #if os(iOS)
        self.toolbar(.hidden, for: .navigationBar)
        #else
        self
        #endif
    }

    @ViewBuilder
    func platformRefreshable(action: @escaping () async -> Void) -> some View {
        #if os(iOS)
        self.refreshable { await action() }
        #else
        self
        #endif
    }
}

// MARK: - Cross-platform Clipboard

enum PlatformClipboard {
    static func copy(_ string: String) {
        #if os(iOS)
        UIPasteboard.general.string = string
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(string, forType: .string)
        #endif
    }
}

// MARK: - Cross-platform Accessibility

enum PlatformAccessibility {
    /// VoiceOver 開啟時發送 announcement，回傳是否已處理。
    @discardableResult
    static func announceIfVoiceOver(_ message: String) -> Bool {
        #if os(iOS)
        guard UIAccessibility.isVoiceOverRunning else { return false }
        UIAccessibility.post(notification: .announcement, argument: message)
        return true
        #elseif os(macOS)
        guard NSWorkspace.shared.isVoiceOverEnabled else { return false }
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [.announcement: message]
        )
        return true
        #endif
    }
}

// MARK: - Cross-platform Store

enum PlatformStore {
    @MainActor
    static func manageSubscriptions() async {
        #if os(iOS)
        guard let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene }).first else { return }
        try? await AppStore.showManageSubscriptions(in: scene)
        #elseif os(macOS)
        if let url = URL(string: "https://apps.apple.com/account/subscriptions") {
            NSWorkspace.shared.open(url)
        }
        #endif
    }
}

// MARK: - Cross-platform Share

struct PlatformShareView: View {
    let url: URL
    var body: some View {
        #if os(iOS)
        PlatformShareSheet(url: url)
        #else
        ShareLink(item: url).padding()
        #endif
    }
}

#if os(iOS)
private struct PlatformShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
#endif

// MARK: - macOS Key Responder

#if os(macOS)
private struct MacKeyResponderRepresentable: NSViewRepresentable {
    let active: Bool
    let onKeyPress: (MacKeyPress) -> Bool

    func makeNSView(context: Context) -> MacKeyResponderView {
        let view = MacKeyResponderView()
        view.onKeyPress = onKeyPress
        view.setActive(active)
        return view
    }

    func updateNSView(_ nsView: MacKeyResponderView, context: Context) {
        nsView.onKeyPress = onKeyPress
        nsView.setActive(active)
    }
}

private final class MacKeyResponderView: NSView {
    var onKeyPress: ((MacKeyPress) -> Bool)?
    private var isActive = true

    override var acceptsFirstResponder: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        claimFirstResponderIfNeeded()
    }

    override func mouseDown(with event: NSEvent) {
        claimFirstResponderIfNeeded()
        super.mouseDown(with: event)
    }

    override func keyDown(with event: NSEvent) {
        guard isActive, let key = map(event), onKeyPress?(key) == true else {
            super.keyDown(with: event)
            return
        }
    }

    func setActive(_ active: Bool) {
        isActive = active
        if active { claimFirstResponderIfNeeded() }
        // inactive 時不 resign — keyDown 已有 isActive guard，留著當 first responder 無害
    }

    private func claimFirstResponderIfNeeded() {
        guard isActive, let window, window.firstResponder !== self else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isActive, let window = self.window,
                  window.firstResponder !== self else { return }
            window.makeFirstResponder(self)
        }
    }

    private func map(_ event: NSEvent) -> MacKeyPress? {
        switch event.keyCode {
        case 49:
            return .space
        case 123:
            return .leftArrow
        case 124:
            return .rightArrow
        case 125:
            return .downArrow
        case 126:
            return .upArrow
        case 53:
            return .escape
        default:
            guard let chars = event.charactersIgnoringModifiers?.lowercased(), !chars.isEmpty else {
                return nil
            }
            return .character(chars)
        }
    }
}
#endif
