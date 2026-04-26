//
//  NetworkMonitor.swift
//  BooksBrowser
//
//  NWPathMonitor wrapper — 即時網路連線狀態，供 UI 層與 Service 層共用
//

import Foundation
import Network
import os

@Observable
final class NetworkMonitor: @unchecked Sendable {
    static let shared = NetworkMonitor()

    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "com.wordnexus.NetworkMonitor")

    /// 目前是否有網路連線（Wi-Fi / Cellular / Ethernet）
    var isConnected: Bool = true

    /// 目前連線介面類型（用於日誌，非 UI）
    var interfaceType: NWInterface.InterfaceType? = nil

    private init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let connected = path.status == .satisfied
            let interface = path.availableInterfaces.first?.type
            Task { @MainActor [weak self] in
                self?.isConnected = connected
                self?.interfaceType = interface
            }
            if !connected {
                AppLog.app.info("Network: disconnected")
            }
        }
        monitor.start(queue: monitorQueue)
    }

    deinit {
        monitor.cancel()
    }
}
