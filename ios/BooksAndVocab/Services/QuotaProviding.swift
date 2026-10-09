import Foundation

/// QuotaStore 的 protocol 抽象，供 View 和 Service 注入使用
protocol QuotaProviding: AnyObject {
    var epoch: Int { get }
    var fraction: Double { get }
    var isExhausted: Bool { get }
    var level: QuotaStore.Level { get }
    var resetText: String { get }
    func update(from response: HTTPURLResponse)
    func update(from response: HTTPURLResponse, ifEpoch epoch: Int)
}

extension QuotaProviding {
    /// Stores without account scoping (previews, mocks) never go stale.
    var epoch: Int { 0 }

    func update(from response: HTTPURLResponse, ifEpoch epoch: Int) {
        update(from: response)
    }
}
