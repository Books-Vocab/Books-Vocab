//
//  PlatformCompatibility.swift
//  Books & Vocab
//
//  iOS / Mac Catalyst SwiftUI modifier wrapper
//

import SwiftUI
import StoreKit

extension View {
    @ViewBuilder
    func inlineNavigationBarTitle() -> some View {
        self.navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    func largeNavigationBarTitle() -> some View {
        self.navigationBarTitleDisplayMode(.large)
    }

    @ViewBuilder
    func platformFullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        self.fullScreenCover(isPresented: isPresented, onDismiss: onDismiss, content: content)
    }

    @ViewBuilder
    func platformFullScreenCover<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        self.fullScreenCover(item: item, onDismiss: onDismiss, content: content)
    }

    func dismissKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
    }

    @ViewBuilder
    func platformTextInputConfig() -> some View {
        self.textInputAutocapitalization(.never).autocorrectionDisabled()
    }

    /// Source-language-aware text input: same as `platformTextInputConfig()`
    /// but additionally forces ASCII keyboard when the user's translation
    /// source language is English. Prevents Japanese / Korean IME from
    /// hijacking English word-lookup fields when the system locale is ja/ko.
    @ViewBuilder
    func platformSourceLangTextInput(
        source: TranslationLanguage = TranslationLanguage.currentSource
    ) -> some View {
        if source == .en {
            self
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.asciiCapable)
        } else {
            self
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        }
    }

    @ViewBuilder
    func platformListButtonStyle() -> some View {
        self.buttonStyle(.pressable)
    }

    @ViewBuilder
    func platformContentMaxWidth(for layoutMode: LayoutMode) -> some View {
        self.frame(maxWidth: layoutMode.contentMaxWidth)
            .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    func platformHideNavigationBar() -> some View {
        self.toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    func platformRefreshable(action: @escaping () async -> Void) -> some View {
        #if targetEnvironment(macCatalyst)
        // 電腦模式無下拉刷新手勢（不直覺）；桌面式刷新改由 toolbar 刷新鈕 / ⌘R 提供。
        self
        #else
        self.refreshable { await action() }
        #endif
    }
}

// MARK: - Cross-platform Clipboard

enum PlatformClipboard {
    static func copy(_ string: String) {
        UIPasteboard.general.string = string
    }
}

// MARK: - Cross-platform Accessibility

enum PlatformAccessibility {
    /// VoiceOver 開啟時發送 announcement，回傳是否已處理。
    @discardableResult
    static func announceIfVoiceOver(_ message: String) -> Bool {
        guard UIAccessibility.isVoiceOverRunning else { return false }
        UIAccessibility.post(notification: .announcement, argument: message)
        return true
    }
}

// MARK: - Cross-platform Store

enum PlatformStore {
    @MainActor
    static func manageSubscriptions() async {
        guard let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene }).first else { return }
        try? await AppStore.showManageSubscriptions(in: scene)
    }
}

// MARK: - Cross-platform Share

struct PlatformShareView: View {
    let url: URL
    var body: some View {
        PlatformShareSheet(url: url)
    }
}

private struct PlatformShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
