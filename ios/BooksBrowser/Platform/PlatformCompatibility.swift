//
//  PlatformCompatibility.swift
//  BooksBrowser
//
//  iOS-only SwiftUI modifier 的跨平台 wrapper
//

import SwiftUI
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
        ensureFirstResponder()
    }

    override func mouseDown(with event: NSEvent) {
        ensureFirstResponder()
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
        ensureFirstResponder()
    }

    private func ensureFirstResponder() {
        guard isActive, let window, window.firstResponder !== self else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isActive else { return }
            self.window?.makeFirstResponder(self)
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
