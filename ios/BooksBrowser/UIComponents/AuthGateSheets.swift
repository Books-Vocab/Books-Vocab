#if os(iOS)
import SwiftUI

struct LoginGateState {
    var isLoginPresented = false

    mutating func presentLogin() {
        isLoginPresented = true
    }
}

struct MonetizationGateState {
    var isLoginPresented = false
    var isPaywallPresented = false

    mutating func presentLogin() {
        isLoginPresented = true
    }

    mutating func presentPaywall() {
        isPaywallPresented = true
    }
}

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

    func loginGateSheet(_ gate: Binding<LoginGateState>) -> some View {
        loginSheet(isPresented: gate.isLoginPresented)
    }

    func monetizationGateSheets(_ gate: Binding<MonetizationGateState>) -> some View {
        loginSheet(isPresented: gate.isLoginPresented)
            .subscriptionPaywallSheet(isPresented: gate.isPaywallPresented)
    }
}
#endif
