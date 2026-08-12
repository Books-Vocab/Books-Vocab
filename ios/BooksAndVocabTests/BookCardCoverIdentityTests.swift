#if os(iOS)

import Foundation
import Testing
@testable import BooksAndVocab

/// Cover decode identity must follow bytes, not only the optional blob length.
struct BookCardCoverIdentityTests {
    @Test func nilAndEqualBytesHaveStableIdentity() {
        #expect(BookCoverDecodeKey(data: nil) == BookCoverDecodeKey(data: nil))
        #expect(
            BookCoverDecodeKey(data: Data([0x01, 0x02]))
                == BookCoverDecodeKey(data: Data([0x01, 0x02]))
        )
    }

    @Test func sameLengthDifferentBytesChangeIdentity() {
        #expect(
            BookCoverDecodeKey(data: Data([0x01, 0x02]))
                != BookCoverDecodeKey(data: Data([0x03, 0x04]))
        )
    }

    @Test func nilAndNonNilAreDifferentStates() {
        #expect(BookCoverDecodeKey(data: nil) != BookCoverDecodeKey(data: Data()))
    }
}

#endif
