//
//  NetworkMonitor.swift
//  Books & Vocab
//
//  NWPathMonitor wrapper — 即時網路連線狀態，供 UI 層與 Service 層共用
//

import Foundation
import Network

@Observable
final class NetworkMonitor: @unchecked Sendable {
    static let shared = NetworkMonitor()

    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: BrandIdentity.networkMonitorQueueLabel)

    /// 目前是否有網路連線（Wi-Fi / Cellular / Ethernet）
    var isConnected: Bool = true

    private init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let connected = path.status == .satisfied
            Task { @MainActor [weak self] in
                self?.isConnected = connected
            }
            if !connected {
                AppLog.app.info("Network: disconnected")
            }
        }
        monitor.start(queue: monitorQueue)
    }

}
