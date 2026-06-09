import Foundation
import os

enum AppLog {
    private static let subsystem = Bundle.main.bundleIdentifier ?? BrandIdentity.bundleSubsystemFallback

    static let kg = Logger(subsystem: subsystem, category: "KGService")
    static let subscription = Logger(subsystem: subsystem, category: "Subscription")
    static let readium = Logger(subsystem: subsystem, category: "Readium")
    static let translation = Logger(subsystem: subsystem, category: "Translation")
    static let auth = Logger(subsystem: subsystem, category: "Auth")
    static let sync = Logger(subsystem: subsystem, category: "Sync")
    static let dictionary = Logger(subsystem: subsystem, category: "Dictionary")
    static let book = Logger(subsystem: subsystem, category: "Book")
    static let reader = Logger(subsystem: subsystem, category: "Reader")
    static let fonts = Logger(subsystem: subsystem, category: "Fonts")
    static let data = Logger(subsystem: subsystem, category: "Data")
    static let app = Logger(subsystem: subsystem, category: "App")
}
