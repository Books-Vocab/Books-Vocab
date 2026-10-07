//
//  SentryReporter.swift
//  Books & Vocab
//
//  The only file in the app allowed to reference SentrySDK. All other app
//  code talks to AppCrashReporting, so removing or disabling the SDK leaves a
//  tested no-op path instead of spreading conditional imports through the app.
//

import Foundation

#if canImport(Sentry)
import Sentry
#endif

enum SentryReporter {
    static func bootstrap(configuration: SentryConfiguration) {
        #if canImport(Sentry)
        guard configuration.enabled, let dsn = configuration.dsn else { return }

        SentrySDK.start { options in
            options.dsn = dsn
            options.environment = configuration.environment
            options.releaseName = configuration.releaseName
            options.dist = configuration.dist
            options.attachStacktrace = true
            options.sendDefaultPii = false
            options.enableAutoPerformanceTracing = configuration.tracesSampleRate > 0
            options.tracesSampleRate = NSNumber(value: configuration.tracesSampleRate)
            options.maxBreadcrumbs = 100
            options.enableUserInteractionTracing = false
            options.attachScreenshot = false
            options.sessionReplay.sessionSampleRate = 0
            options.sessionReplay.onErrorSampleRate = 0
            options.beforeBreadcrumb = { crumb in
                crumb.category = SentryPrivacyPolicy.redactContext(crumb.category) ?? "app"
                crumb.message = SentryPrivacyPolicy.redactBreadcrumbMessage(crumb.message)
                let originalData = crumb.data
                let originalKeys = originalData.map { Array($0.keys) } ?? []
                for key in originalKeys {
                    crumb.setData(value: nil, key: key)
                }
                if let data = SentryPrivacyPolicy.redactBreadcrumbData(originalData) {
                    for (key, value) in data {
                        crumb.setData(value: value, key: key)
                    }
                }
                return crumb
            }
            options.beforeSend = { event in
                if let exception = event.exceptions?.first,
                   SentryPrivacyPolicy.isCancellationException(
                       type: exception.type,
                       value: exception.value
                   ) {
                    return nil
                }
                // capture(error:) asks the SDK to bridge Swift Error/NSError.
                // That bridge may place descriptions, associated values and
                // NSError userInfo into exception.value/mechanism. SDK crash,
                // hang and watchdog events keep their identity and handled
                // flag for triage; every human/error payload (mechanism
                // data/meta/desc, NSException reasons, free-form values) is
                // removed before processors run. Rules: SentryPrivacyPolicy.
                for exception in event.exceptions ?? [] {
                    let redacted = SentryPrivacyPolicy.redactException(
                        type: exception.type,
                        value: exception.value,
                        mechanismType: exception.mechanism?.type,
                        handled: exception.mechanism?.handled?.boolValue
                    )
                    exception.type = redacted.type
                    exception.value = redacted.value
                    exception.module = nil
                    if let mechanismType = redacted.mechanismType {
                        let mechanism = Mechanism(type: mechanismType)
                        mechanism.handled = redacted.handled.map { NSNumber(value: $0) }
                        exception.mechanism = mechanism
                    } else {
                        exception.mechanism = nil
                    }
                }
                event.error = nil
                event.message = SentryPrivacyPolicy.redactEventMessage(event.message?.formatted)
                    .map { SentryMessage(formatted: $0) }
                if let request = event.request {
                    request.url = request.url.flatMap(SentryPrivacyPolicy.redactBreadcrumbURL)
                    request.queryString = nil
                    request.cookies = nil
                    if let headers = request.headers {
                        request.headers = Dictionary(uniqueKeysWithValues: headers.filter {
                            !SentryPrivacyPolicy.isSensitiveField($0.key)
                        })
                    }
                }
                event.extra = SentryPrivacyPolicy.redactEventExtra(event.extra)
                return event
            }
            #if DEBUG
            options.debug = false
            options.enabled = configuration.enabled
            #endif
        }

        if configuration.refinesEnvironmentAtRuntime {
            let bootstrapEnvironment = configuration.environment
            Task.detached(priority: .background) {
                let environment = await SentryConfiguration.fetchAppTransactionEnvironment()
                guard let channel = SentryConfiguration.verifiedChannel(for: environment) else { return }
                SentryConfiguration.storeVerifiedChannel(channel)
                guard channel != bootstrapEnvironment else { return }
                SentrySDK.configureScope { $0.setEnvironment(channel) }
            }
        }

        if configuration.testEventRequested {
            let eventID = SentrySDK.capture(message: SentryPrivacyPolicy.verificationMessage)
            AppDiagnosticContext.shared.recordEventID(eventIDString(eventID))
        }
        #else
        _ = configuration
        #endif
    }

    @discardableResult
    static func record(error: Error, context: String?, requestID: String?) -> String? {
        #if canImport(Sentry)
        let eventID = SentrySDK.capture(error: error) { scope in
            if let context = SentryPrivacyPolicy.redactContext(context) {
                scope.setTag(value: context, key: "context")
            }
            if let requestID = SentryPrivacyPolicy.redactRequestID(requestID) {
                scope.setTag(value: requestID, key: "request_id")
            }
        }
        return eventIDString(eventID)
        #else
        _ = (error, context, requestID)
        return nil
        #endif
    }

    static func addBreadcrumb(
        category: String,
        message: String,
        level: AppCrashReporting.BreadcrumbLevel,
        data: [String: Any]?
    ) {
        #if canImport(Sentry)
        let crumb = Breadcrumb()
        crumb.category = SentryPrivacyPolicy.redactContext(category) ?? "app"
        crumb.message = SentryPrivacyPolicy.redactBreadcrumbMessage(message)
        crumb.level = sentryLevel(from: level)
        if let data = SentryPrivacyPolicy.redactBreadcrumbData(data) {
            for (key, value) in data {
                crumb.setData(value: value, key: key)
            }
        }
        SentrySDK.addBreadcrumb(crumb)
        #else
        _ = (category, message, level, data)
        #endif
    }

    static func setUser(id: String?) {
        #if canImport(Sentry)
        SentrySDK.configureScope { scope in
            if let safeID = SentryPrivacyPolicy.redactUserID(id) {
                let user = User()
                user.userId = safeID
                scope.setUser(user)
            } else {
                scope.setUser(nil)
            }
        }
        #else
        _ = id
        #endif
    }

    #if canImport(Sentry)
    private static func eventIDString(_ eventID: SentryId) -> String? {
        let value = eventID.sentryIdString
        return value.allSatisfy({ $0 == "0" }) ? nil : value
    }

    private static func sentryLevel(from level: AppCrashReporting.BreadcrumbLevel) -> SentryLevel {
        switch level {
        case .debug: return .debug
        case .info: return .info
        case .warning: return .warning
        case .error: return .error
        case .fatal: return .fatal
        }
    }
    #endif
}
