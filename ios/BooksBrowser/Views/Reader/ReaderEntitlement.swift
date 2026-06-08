#if os(iOS)
import Foundation

/// Single source of truth for reader pro-feature gating, shared by both the
/// EPUB (`ReaderView`) and PDF (`PDFReaderView`) readers so vocabulary capture
/// is gated identically. Returns `true` today (no entitlement check shipped);
/// when one lands it lands here once, not per-reader.
enum ReaderEntitlement {
    static func canUseProReaderFeature() -> Bool {
        true
    }
}
#endif
