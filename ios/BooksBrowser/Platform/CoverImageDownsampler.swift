#if os(iOS)
//
//  CoverImageDownsampler.swift
//  BooksBrowser
//
//  Shrinks a full-resolution cover image down to a thumbnail before it is
//  persisted in `Book.coverImageData`. EPUB cover extraction (`ReadiumService`)
//  previously stored the raw full-size PNG, producing large SwiftData blobs;
//  the PDF path already downsamples via `PDFPage.thumbnail(of:)`. This helper
//  gives the EPUB path equivalent treatment with a UIImage-based seam.
//

import UIKit
import ImageIO
import os

enum CoverImageDownsampler {

    /// Default cover thumbnail bound. Covers display far smaller than this on
    /// the bookshelf; the bound leaves headroom over the PDF path's 300×400.
    static let defaultMaxDimension: CGFloat = 600

    /// JPEG is materially smaller than PNG for photographic cover art.
    static let defaultCompressionQuality: CGFloat = 0.8

    /// Downsample `image` so its longest edge is at most `maxDimension`, then
    /// encode as JPEG. Returns `nil` if encoding fails so callers can fall back
    /// to the original data rather than silently dropping the cover.
    ///
    /// Images already within the bound are re-encoded to JPEG (still a size win
    /// over the source PNG) without upscaling.
    static func downsampledJPEG(
        from image: UIImage,
        maxDimension: CGFloat = defaultMaxDimension,
        compressionQuality: CGFloat = defaultCompressionQuality
    ) -> Data? {
        let resized = resize(image, maxDimension: maxDimension)
        return resized.jpegData(compressionQuality: compressionQuality)
    }

    /// Decode + downsample directly from encoded image `data` via ImageIO,
    /// avoiding a full-resolution intermediate decode. Falls back to the
    /// UIImage path if ImageIO cannot read the data.
    static func downsampledJPEG(
        from data: Data,
        maxDimension: CGFloat = defaultMaxDimension,
        compressionQuality: CGFloat = defaultCompressionQuality
    ) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else {
            return UIImage(data: data).flatMap {
                downsampledJPEG(from: $0, maxDimension: maxDimension, compressionQuality: compressionQuality)
            }
        }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: max(1, Int(maxDimension.rounded()))
        ]
        guard let cgThumb = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            return UIImage(data: data).flatMap {
                downsampledJPEG(from: $0, maxDimension: maxDimension, compressionQuality: compressionQuality)
            }
        }
        return UIImage(cgImage: cgThumb).jpegData(compressionQuality: compressionQuality)
    }

    /// Aspect-preserving resize. Never upscales.
    private static func resize(_ image: UIImage, maxDimension: CGFloat) -> UIImage {
        let size = image.size
        let longest = max(size.width, size.height)
        guard longest > maxDimension, longest > 0 else { return image }

        let scale = maxDimension / longest
        let target = CGSize(width: size.width * scale, height: size.height * scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = false
        let renderer = UIGraphicsImageRenderer(size: target, format: format)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }
}
#endif
