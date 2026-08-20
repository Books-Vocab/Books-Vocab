//
//  AppCrashReporting.swift
//  Books & Vocab
//
//  Product-facing crash/error reporting facade. Product call sites depend on
//  this file only; SDK setup and privacy filtering live behind seams.
//

import Foundation
import os

enum AppCrashReporting {
    /// Strongly-typed breadcrumb severity. Avoids stringly-typed fallbacks.
    enum BreadcrumbLevel: String {
        case debug
        case info
        case warning
        case error
        case fatal
    }

    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? BrandIdentity.bundleSubsystemFallback,
        category: "CrashReporting"
    )

    /// Call once, as early as possible in the app lifecycle.
    static func bootstrap() {
        let configuration = SentryConfiguration.current()
        SentryReporter.bootstrap(configuration: configuration)

        guard configuration.dsn != nil, configuration.enabled else {
            logger.info("Sentry disabled by configuration")
            return
        }
        logger.info(
            "Sentry initialized env=\(configuration.environment, privacy: .public) release=\(configuration.releaseName ?? "-", privacy: .public)"
        )
    }

    /// Capture a Swift error. Safe to call even when Sentry is inactive.
    /// The optional request ID is explicit so async work cannot rely on a
    /// mutable global request context.
    @discardableResult
    static func record(
        _ error: Error,
        context: String? = nil,
        requestID: String? = nil
    ) -> String? {
        let eventID = SentryReporter.record(error: error, context: context, requestID: requestID)
        AppDiagnosticContext.shared.recordError(
            errorType: String(reflecting: type(of: error)),
            context: context,
            requestID: requestID,
            eventID: eventID
        )
        return eventID
    }

    /// Drop a breadcrumb describing a significant state change. Breadcrumb
    /// data is redacted again by the SDK adapter before it leaves the device.
    static func addBreadcrumb(
        category: String,
        message: String,
        level: BreadcrumbLevel = .info,
        data: [String: Any]? = nil
    ) {
        SentryReporter.addBreadcrumb(category: category, message: message, level: level, data: data)
        let requestID = data?["request_id"] as? String
        AppDiagnosticContext.shared.recordObservation(message: message, requestID: requestID)
    }

    /// Tag the current user with an opaque internal ID. Passing an email,
    /// token, or free-form text clears the user context instead.
    static func setUser(id: String?) {
        SentryReporter.setUser(id: id)
    }
}
