#if os(iOS)
import Foundation
import UIKit
import ImageIO
import Testing
@testable import BooksAndVocab

/// Pins `CoverImageDownsampler` — 兩條路徑各自的契約：
///
/// - 顯示路徑（track-14）`downsample(data:maxDimensionPoints:scale:)`：保證輸出
///   像素 ≤ 目標上限、帶入指定 scale，避免可見 cell × 全解析度 backing store
///   疊加爆記憶體。
/// - 存檔路徑（track-15）`downsampledJPEG(from:)`：保持 EPUB 封面 blob 小於
///   `Book.coverImageData`；`ReadiumService.extractCover` 在持久化前把全解析度
///   `UIImage` 餵進此 seam，先前直接存原始全尺寸 PNG。
struct CoverImageDownsamplerTests {

    // MARK: - Fixtures

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

    /// 產生指定像素尺寸的 PNG `Data`（scale 1，便於 pixel 斷言）。
    private func makePNG(widthPx: Int, heightPx: Int) -> Data {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let size = CGSize(width: widthPx, height: heightPx)
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        let image = renderer.image { ctx in
            UIColor.systemBlue.setFill()
            ctx.fill(CGRect(origin: .zero, size: size))
        }
        return image.pngData()!
    }

    private func pixelSize(of data: Data) -> CGSize? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = props[kCGImagePropertyPixelWidth] as? CGFloat,
              let h = props[kCGImagePropertyPixelHeight] as? CGFloat else { return nil }
        return CGSize(width: w, height: h)
    }

    // MARK: - 顯示路徑（track-14）：downsample(data:maxDimensionPoints:scale:)

    @Test("大圖降採樣後最長邊像素 ≤ 目標上限")
    func downsamplesLargeImage() throws {
        // 模擬全解析度封面：1200×1800 px。
        let data = makePNG(widthPx: 1200, heightPx: 1800)
        let maxPoints: CGFloat = 210
        let scale: CGFloat = 2
        let maxPixels = maxPoints * scale // 420

        let result = try #require(
            CoverImageDownsampler.downsample(
                data: data,
                maxDimensionPoints: maxPoints,
                scale: scale
            )
        )

        let pixelW = result.size.width * result.scale
        let pixelH = result.size.height * result.scale
        let longest = max(pixelW, pixelH)

        // 最長邊不超過上限（允許 1px ImageIO rounding 容差）。
        #expect(longest <= maxPixels + 1)
        // 確實降採樣（沒退化成原圖）。
        #expect(longest < 1800)
        // 維持長寬比（2:3，容差 0.02）。
        #expect(abs((pixelW / pixelH) - (1200.0 / 1800.0)) < 0.02)
    }

    @Test("輸出 UIImage 帶入指定 scale")
    func appliesScale() throws {
        let data = makePNG(widthPx: 600, heightPx: 900)
        let result = try #require(
            CoverImageDownsampler.downsample(data: data, maxDimensionPoints: 210, scale: 3)
        )
        #expect(result.scale == 3)
    }

    @Test("非圖片資料回 nil")
    func invalidDataReturnsNil() {
        let garbage = Data([0x00, 0x01, 0x02, 0x03, 0x04])
        #expect(CoverImageDownsampler.downsample(data: garbage, maxDimensionPoints: 210, scale: 2) == nil)
    }

    @Test("空資料回 nil")
    func emptyDataReturnsNil() {
        #expect(CoverImageDownsampler.downsample(data: Data(), maxDimensionPoints: 210, scale: 2) == nil)
    }

    @Test("小於上限的圖不被放大超過上限")
    func smallImageNotUpscaledBeyondCap() throws {
        // 100×150 px 原圖，上限 420 px。ImageIO 縮圖不放大，輸出應 ≤ 原圖最長邊。
        let data = makePNG(widthPx: 100, heightPx: 150)
        let result = try #require(
            CoverImageDownsampler.downsample(data: data, maxDimensionPoints: 210, scale: 2)
        )
        let longest = max(result.size.width * result.scale, result.size.height * result.scale)
        #expect(longest <= 420 + 1)
    }

    @Test("Notebook cover cache reuses same path and display bound")
    func notebookCoverCacheReusesSamePathAndSize() throws {
        NotebookCoverImageCache.removeAll()
        defer { NotebookCoverImageCache.removeAll() }
        let png = makePNG(widthPx: 900, heightPx: 1200)
        var loads = 0

        let first = try #require(NotebookCoverImageCache.image(
            path: "/tmp/cover.png",
            displaySize: CGSize(width: 120, height: 180),
            scale: 2
        ) { _ in
            loads += 1
            return png
        })
        let second = try #require(NotebookCoverImageCache.image(
            path: "/tmp/cover.png",
            displaySize: CGSize(width: 120, height: 180),
            scale: 2
        ) { _ in
            loads += 1
            return png
        })

        #expect(loads == 1)
        #expect(first === second)
    }

    @Test("Notebook cover cache keys include display bound")
    func notebookCoverCacheSeparatesDisplaySizes() throws {
        NotebookCoverImageCache.removeAll()
        defer { NotebookCoverImageCache.removeAll() }
        let png = makePNG(widthPx: 900, heightPx: 1200)
        var loads = 0

        _ = try #require(NotebookCoverImageCache.image(
            path: "/tmp/cover.png",
            displaySize: CGSize(width: 80, height: 120),
            scale: 2
        ) { _ in
            loads += 1
            return png
        })
        _ = try #require(NotebookCoverImageCache.image(
            path: "/tmp/cover.png",
            displaySize: CGSize(width: 180, height: 270),
            scale: 2
        ) { _ in
            loads += 1
            return png
        })

        #expect(loads == 2)
    }

    @Test("Notebook cover cache keys include file metadata")
    func notebookCoverCacheInvalidatesWhenFileChanges() throws {
        NotebookCoverImageCache.removeAll()
        defer { NotebookCoverImageCache.removeAll() }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("notebook-cover-cache-\(UUID().uuidString).png")
        defer { try? FileManager.default.removeItem(at: url) }
        try makePNG(widthPx: 90, heightPx: 120).write(to: url)

        let first = try #require(NotebookCoverImageCache.image(
            path: url.path,
            displaySize: CGSize(width: 45, height: 60),
            scale: 2
        ))
        try makePNG(widthPx: 180, heightPx: 240).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(2)], ofItemAtPath: url.path)
        let second = try #require(NotebookCoverImageCache.image(
            path: url.path,
            displaySize: CGSize(width: 45, height: 60),
            scale: 2
        ))

        #expect(first !== second)
    }

    // MARK: - 存檔路徑（track-15）：downsampledJPEG（UIImage path）

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

    // MARK: - 存檔路徑（track-15）：downsampledJPEG（Data / ImageIO path）

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
