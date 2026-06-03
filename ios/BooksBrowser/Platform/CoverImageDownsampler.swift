//
//  CoverImageDownsampler.swift
//  BooksBrowser
//
//  封面縮圖降採樣 — 用 ImageIO 直接以縮圖解析度解碼，
//  避免先解全解析度 UIImage 再縮放造成的 backing store 記憶體爆量。
//

import ImageIO
import UIKit

enum CoverImageDownsampler {
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
}
