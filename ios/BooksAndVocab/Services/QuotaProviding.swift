import Foundation

/// QuotaStore 的 protocol 抽象，供 View 和 Service 注入使用
protocol QuotaProviding: AnyObject {
    var fraction: Double { get }
    var isExhausted: Bool { get }
    var level: QuotaStore.Level { get }
    var resetText: String { get }
    func update(from response: HTTPURLResponse)
}
