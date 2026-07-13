import Testing
@testable import BooksAndVocab

struct AccountIdentityFingerprintTests {
    @Test func normalizesReviewerUsernameBeforeHashing() {
        let fingerprint = AccountIdentityFingerprint.sha256(
            "  REVIEWER@EXAMPLE.COM\n"
        )

        #expect(
            fingerprint
                == "18717f7f1f60f92207bd02972c16aec92f52b31c2a8442444df988d8e8503c5e"
        )
    }

    @Test func canonicalUnicodeFormsProduceTheSameFingerprint() {
        let composed = AccountIdentityFingerprint.sha256("réviewer@example.com")
        let decomposed = AccountIdentityFingerprint.sha256("réviewer@example.com")

        #expect(composed == decomposed)
    }

    @Test func missingIdentityCannotProduceEvidence() {
        #expect(AccountIdentityFingerprint.sha256(nil) == nil)
        #expect(AccountIdentityFingerprint.sha256(" \n\t") == nil)
    }
}
