#if os(iOS)
import SwiftUI

extension View {
    func loginSheet(isPresented: Binding<Bool>) -> some View {
        sheet(isPresented: isPresented) {
            LoginSheet()
        }
    }

    func subscriptionPaywallSheet(isPresented: Binding<Bool>) -> some View {
        toastSheet(isPresented: isPresented) {
            SubscriptionPaywallSheet()
        }
    }

    func monetizationGateSheets(
        login: Binding<Bool>,
        paywall: Binding<Bool>
    ) -> some View {
        loginSheet(isPresented: login)
            .subscriptionPaywallSheet(isPresented: paywall)
    }
}
#endif
