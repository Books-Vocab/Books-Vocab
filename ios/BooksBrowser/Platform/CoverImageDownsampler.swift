#if os(iOS)
//
//  CoverImageDownsampler.swift
//  BooksBrowser
//
//  封面縮圖降採樣 — 兩條互補路徑共用一個命名空間：
//
//  1. `downsample(data:maxDimensionPoints:scale:)` — 顯示路徑（track-14）。
//     用 ImageIO 直接以縮圖解析度解碼成 `UIImage`，給 `BookCard` 在書架上
//     顯示，避免先解全解析度 UIImage 再縮放造成的 backing store 記憶體爆量。
//
//  2. `downsampledJPEG(from:)` — 存檔路徑（track-15）。
//     在持久化前把全解析度封面縮成縮圖再編碼為 JPEG，給
//     `ReadiumService.extractCover` 使用；EPUB 封面原為全尺寸 PNG，直接存進
//     `Book.coverImageData` 會撐大 SwiftData blob（PDF 路徑已透過
//     `PDFPage.thumbnail(of:)` 降採樣）。
//

import UIKit
import ImageIO

enum CoverImageDownsampler {

    // MARK: - 顯示路徑（track-14）：Data → 降採樣 UIImage

    /// 將封面 `Data` 直接降採樣為不超過 `maxDimensionPoints * scale` 像素的縮圖。
    ///
    /// 使用 `CGImageSourceCreateThumbnailAtIndex`，ImageIO 直接以目標尺寸解碼，
    /// 不會在記憶體中建立全解析度 backing store。
    ///
    /// - Parameters:
    ///   - data: 原始封面位元組（任意 ImageIO 支援格式）。
    ///   - maxDimensionPoints: 顯示時最長邊的點數（顯示尺寸）。
    ///   - scale: 螢幕縮放（retina 通常為 2 或 3）。
    /// - Returns: 降採樣後的 `UIImage`；解碼失敗回 `nil`。
    static func downsample(
        data: Data,
        maxDimensionPoints: CGFloat,
        scale: CGFloat
    ) -> UIImage? {
        let maxPixels = max(1, Int((maxDimensionPoints * scale).rounded()))

        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions) else {
            return nil
        }

        let thumbnailOptions = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixels,
        ] as CFDictionary

        guard let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, thumbnailOptions) else {
            return nil
        }

        return UIImage(cgImage: cgImage, scale: scale, orientation: .up)
    }

    // MARK: - 存檔路徑（track-15）：→ 降採樣 JPEG Data

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
