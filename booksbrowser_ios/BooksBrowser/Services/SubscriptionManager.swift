import Foundation

enum PaywallSource: String {
    case settings
    case sync
    case graph
    case reader
}

@MainActor
protocol SubscriptionManaging: AnyObject {
    var entitlements: KGEntitlements { get }
    var isLoading: Bool { get }
    var lastError: String? { get }
    var activePaywallSource: PaywallSource? { get set }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async
}

@Observable
@MainActor
final class SubscriptionManager: SubscriptionManaging {
    static let shared = SubscriptionManager()

    var entitlements = KGEntitlements(
        pro: KGSubscriptionStatus(
            is_active: false,
            product_id: nil,
            plan_name: "BooksBrowser Pro",
            price_display: nil,
            status: "inactive",
            is_trial: false,
            trial_days: 7,
            will_renew: false,
            expires_at: nil,
            source: "app_store",
            last_synced_at: nil
        )
    )
    var isLoading = false
    var lastError: String?
    var activePaywallSource: PaywallSource?

    private init() {}

    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async {
        guard authManager.isLoggedIn else {
            entitlements = Self.defaultEntitlements
            lastError = nil
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            entitlements = try await kgService.fetchEntitlements()
            lastError = nil
        } catch {
            entitlements = Self.defaultEntitlements
            lastError = error.localizedDescription
        }
    }

    static var defaultEntitlements: KGEntitlements {
        KGEntitlements(
            pro: KGSubscriptionStatus(
                is_active: false,
                product_id: nil,
                plan_name: "BooksBrowser Pro",
                price_display: nil,
                status: "inactive",
                is_trial: false,
                trial_days: 7,
                will_renew: false,
                expires_at: nil,
                source: "app_store",
                last_synced_at: nil
            )
        )
    }
}
