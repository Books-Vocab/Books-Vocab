//
//  KGErrorTests.swift
//  Books & Vocab Tests
//
//  Pins KGError retryability and network-related classification. A regression
//  here changes whether a failed request is silently retried or immediately
//  surfaced to the user.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct KGErrorTests {

    // MARK: - isNetworkRelated

    @Test func offlineIsNetworkRelated() {
        #expect(KGError.offline.isNetworkRelated == true)
    }

    @Test func networkErrorIsNetworkRelated() {
        let error = KGError.networkError(underlying: URLError(.notConnectedToInternet))
        #expect(error.isNetworkRelated == true)
    }

    @Test func notAuthenticatedIsNotNetworkRelated() {
        #expect(KGError.notAuthenticated.isNetworkRelated == false)
    }

    @Test func unauthorizedIsNotNetworkRelated() {
        #expect(KGError.unauthorized.isNetworkRelated == false)
    }

    @Test func httpErrorIsNotNetworkRelated() {
        let error = KGError.httpError(statusCode: 500, detail: "oops")
        #expect(error.isNetworkRelated == false)
    }

    @Test func decodingErrorIsNotNetworkRelated() {
        let error = KGError.decodingError(underlying: URLError(.badURL))
        #expect(error.isNetworkRelated == false)
    }

    @Test func serverErrorIsNotNetworkRelated() {
        #expect(KGError.serverError("fail").isNetworkRelated == false)
    }

    // MARK: - isRetryable

    @Test func serverError5xxIsRetryable() {
        let error = KGError.httpError(statusCode: 503, detail: "unavailable")
        #expect(error.isRetryable == true)
    }

    @Test func rateLimit429IsRetryable() {
        let error = KGError.httpError(statusCode: 429, detail: "slow down")
        #expect(error.isRetryable == true)
    }

    @Test func clientError4xxIsNotRetryable() {
        let error = KGError.httpError(statusCode: 400, detail: "bad request")
        #expect(error.isRetryable == false)
    }

    @Test func notFound404IsNotRetryable() {
        let error = KGError.httpError(statusCode: 404, detail: "not found")
        #expect(error.isRetryable == false)
    }

    @Test func offlineIsRetryable() {
        #expect(KGError.offline.isRetryable == true)
    }

    @Test func networkErrorIsRetryable() {
        let error = KGError.networkError(underlying: URLError(.timedOut))
        #expect(error.isRetryable == true)
    }

    @Test func notAuthenticatedIsNotRetryable() {
        #expect(KGError.notAuthenticated.isRetryable == false)
    }

    @Test func unauthorizedIsNotRetryable() {
        #expect(KGError.unauthorized.isRetryable == false)
    }

    @Test func decodingErrorIsNotRetryable() {
        let error = KGError.decodingError(underlying: URLError(.badURL))
        #expect(error.isRetryable == false)
    }

    @Test func serverErrorStringIsNotRetryable() {
        #expect(KGError.serverError("fail").isRetryable == false)
    }
}
