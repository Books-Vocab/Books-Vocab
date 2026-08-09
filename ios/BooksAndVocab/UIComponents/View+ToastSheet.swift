import SwiftUI

extension View {
    func toastSheet<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        sheet(isPresented: isPresented, onDismiss: onDismiss) {
            content().toastOverlay().appAppearanceScheme()
        }
    }

    func toastSheet<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        sheet(item: item, onDismiss: onDismiss) { value in
            content(value).toastOverlay().appAppearanceScheme()
        }
    }

    func toastFullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        platformFullScreenCover(isPresented: isPresented, onDismiss: onDismiss) {
            content().toastOverlay()
        }
    }

    func toastFullScreenCover<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        platformFullScreenCover(item: item, onDismiss: onDismiss) { value in
            content(value).toastOverlay()
        }
    }
}
