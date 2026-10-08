//
//  TranslationServiceErrorMappingTests.swift
//  Books & Vocab Tests
//
//  Pins retry classification and decode-failure mapping of TranslationService.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct TranslationServiceErrorMappingTests {
    private struct Payload: Decodable { let t: String }

    @Test func clientErrorStatusesAreNotRetryable() {
        for status in [400, 403, 404, 422] {
            #expect(TranslationService.isPermanentClientStatus(status))
        }
        for status in [500, 502, 503, 504] {
            #expect(!TranslationService.isPermanentClientStatus(status))
        }
    }

    @Test func decodeFailureBecomesParseError() {
        do {
            _ = try TranslationService.decodeResponse(Payload.self, from: Data("{}".utf8))
            Issue.record("expected parseError")
        } catch let error as TranslationError {
            guard case .parseError = error else {
                Issue.record("expected parseError, got \(error)")
                return
            }
        } catch {
            Issue.record("raw error leaked: \(error)")
        }
    }

    @Test func decodeSuccessReturnsValue() throws {
        let value = try TranslationService.decodeResponse(Payload.self, from: Data(#"{"t":"x"}"#.utf8))
        #expect(value.t == "x")
    }
}
