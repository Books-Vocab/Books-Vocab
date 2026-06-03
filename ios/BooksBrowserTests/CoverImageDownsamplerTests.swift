//
//  CoverImageDownsamplerTests.swift
//  BooksBrowserTests
//
//  Pins CoverImageDownsampler — 封面縮圖降採樣 (track-14 記憶體修法)。
//  保證輸出像素 ≤ 目標上限，避免可見 cell × 全解析度 backing store 疊加爆記憶體。
//

import Foundation
import Testing
import UIKit
@testable import BooksBrowser

struct CoverImageDownsamplerTests {

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

    // MARK: - 上限封頂

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

    // MARK: - 回傳 scale

    @Test("輸出 UIImage 帶入指定 scale")
    func appliesScale() throws {
        let data = makePNG(widthPx: 600, heightPx: 900)
        let result = try #require(
            CoverImageDownsampler.downsample(data: data, maxDimensionPoints: 210, scale: 3)
        )
        #expect(result.scale == 3)
    }

    // MARK: - 失敗回 nil

    @Test("非圖片資料回 nil")
    func invalidDataReturnsNil() {
        let garbage = Data([0x00, 0x01, 0x02, 0x03, 0x04])
        #expect(CoverImageDownsampler.downsample(data: garbage, maxDimensionPoints: 210, scale: 2) == nil)
    }

    @Test("空資料回 nil")
    func emptyDataReturnsNil() {
        #expect(CoverImageDownsampler.downsample(data: Data(), maxDimensionPoints: 210, scale: 2) == nil)
    }

    // MARK: - 小圖不放大超過上限

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
}
