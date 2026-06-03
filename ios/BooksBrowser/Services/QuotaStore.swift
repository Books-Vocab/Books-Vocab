import Foundation

@Observable
final class QuotaStore: QuotaProviding {
    static let shared = QuotaStore()

    private(set) var fraction: Double = 1.0
    private(set) var resetSeconds: Int = 0

    var isExhausted: Bool { fraction <= 0 }

    enum Level {
        case normal, warning, critical, exhausted
    }

    var level: Level {
        switch fraction {
        case ...0:          return .exhausted
        case 0..<0.1:       return .critical
        case 0.1..<0.3:     return .warning
        default:            return .normal
        }
    }

    func update(fraction: Double, resetSeconds: Int) {
        self.fraction = fraction
        self.resetSeconds = resetSeconds
    }

    /// Restores the pristine pre-fetch state. Called on logout / account-switch so a new
    /// account never inherits the previous account's remaining quota (account A's number
    /// flashing under account B until the next response header overwrites it).
    func reset() {
        self.fraction = 1.0
        self.resetSeconds = 0
    }

    func update(from response: HTTPURLResponse) {
        if let fractionStr = response.value(forHTTPHeaderField: "X-Quota-Fraction"),
           let f = Double(fractionStr) {
            self.fraction = f
        }
        if let resetStr = response.value(forHTTPHeaderField: "X-Quota-Reset"),
           let r = Int(resetStr) {
            self.resetSeconds = r
        }
    }

    var resetText: String {
        let h = resetSeconds / 3600
        let m = (resetSeconds % 3600) / 60
        if h > 0 {
            return L10n.format("%@h %@m 後重置", "\(h)", "\(m)")
        }
        return L10n.format("%@m 後重置", "\(m)")
    }

    init() {}
}
