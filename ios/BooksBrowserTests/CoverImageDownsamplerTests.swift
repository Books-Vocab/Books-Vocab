#if os(iOS)
import Foundation
import UIKit
import ImageIO
import Testing
@testable import BooksBrowser

/// Pins `CoverImageDownsampler` — the seam that keeps EPUB cover blobs small in
/// `Book.coverImageData`. The EPUB path (`ReadiumService.extractCover`) feeds a
/// full-resolution `UIImage` through here before persisting; previously it
/// stored the raw full-size PNG.
struct CoverImageDownsamplerTests {

    /// A solid-colour image of a given pixel size (scale 1 → pixels == points).
    private func makeImage(width: CGFloat, height: CGFloat) -> UIImage {
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
        return renderer.image { ctx in
            UIColor.systemTeal.setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        }
    }

    private func pixelSize(of data: Data) -> CGSize? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = props[kCGImagePropertyPixelWidth] as? CGFloat,
              let h = props[kCGImagePropertyPixelHeight] as? CGFloat else { return nil }
        return CGSize(width: w, height: h)
    }

    // MARK: - UIImage path

    @Test func largeCoverShrinksWithinBound() throws {
        // 1200×1800 → longest edge must collapse to the 600 default bound.
        let big = makeImage(width: 1200, height: 1800)
        let data = try #require(CoverImageDownsampler.downsampledJPEG(from: big))
        let size = try #require(pixelSize(of: data))
        #expect(max(size.width, size.height) <= CoverImageDownsampler.defaultMaxDimension)
        // Aspect ratio preserved (2:3 → ~400×600).
        #expect(abs(size.width / size.height - (2.0 / 3.0)) < 0.02)
    }

    @Test func smallCoverIsNotUpscaled() throws {
        let small = makeImage(width: 200, height: 300)
        let data = try #require(CoverImageDownsampler.downsampledJPEG(from: small))
        let size = try #require(pixelSize(of: data))
        #expect(max(size.width, size.height) <= 300)
    }

    @Test func customMaxDimensionHonoured() throws {
        let big = makeImage(width: 1000, height: 1000)
        let data = try #require(CoverImageDownsampler.downsampledJPEG(from: big, maxDimension: 300))
        let size = try #require(pixelSize(of: data))
        #expect(max(size.width, size.height) <= 300)
    }

    @Test func jpegIsSmallerThanSourcePNG() throws {
        let big = makeImage(width: 1500, height: 2000)
        let png = try #require(big.pngData())
        let jpeg = try #require(CoverImageDownsampler.downsampledJPEG(from: big))
        #expect(jpeg.count < png.count)
    }

    // MARK: - Data (ImageIO) path

    @Test func dataPathShrinksWithinBound() throws {
        let big = makeImage(width: 1400, height: 1400)
        let png = try #require(big.pngData())
        let data = try #require(CoverImageDownsampler.downsampledJPEG(from: png))
        let size = try #require(pixelSize(of: data))
        #expect(max(size.width, size.height) <= CoverImageDownsampler.defaultMaxDimension)
    }

    @Test func dataPathReturnsNilOnGarbage() {
        let garbage = Data([0x00, 0x01, 0x02, 0x03])
        #expect(CoverImageDownsampler.downsampledJPEG(from: garbage) == nil)
    }
}
#endif
