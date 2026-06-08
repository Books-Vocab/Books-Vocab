#!/usr/bin/env swift

import AppKit
import Foundation

struct ImageReport: Encodable {
    let path: String
    let pixelWidth: Int
    let pixelHeight: Int
    let sampledPixelCount: Int
    let alphaMin: Int
    let alphaMax: Int
    let luminanceMin: Int
    let luminanceMax: Int
    let isFullyTransparent: Bool
    let isUniform: Bool
}

private enum InspectError: Error {
    case usage
    case unreadableImage(String)
    case unreadableBitmap(String)
}

private func report(for path: String) throws -> ImageReport {
    guard
        let image = NSImage(contentsOfFile: path),
        let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
    else {
        throw InspectError.unreadableImage(path)
    }

    let width = cgImage.width
    let height = cgImage.height
    guard width > 0, height > 0 else {
        throw InspectError.unreadableBitmap(path)
    }

    let thumbnailEdge = 128
    let sampleWidth = min(width, thumbnailEdge)
    let sampleHeight = min(height, thumbnailEdge)
    let bytesPerPixel = 4
    let bitsPerComponent = 8
    let bytesPerRow = sampleWidth * bytesPerPixel
    guard
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let context = CGContext(
            data: nil,
            width: sampleWidth,
            height: sampleHeight,
            bitsPerComponent: bitsPerComponent,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ),
        let data = context.data
    else {
        throw InspectError.unreadableBitmap(path)
    }

    context.interpolationQuality = .high
    context.clear(CGRect(x: 0, y: 0, width: sampleWidth, height: sampleHeight))
    let rect = CGRect(x: 0, y: 0, width: sampleWidth, height: sampleHeight)
    context.draw(cgImage, in: rect)
    let pixels = data.assumingMemoryBound(to: UInt8.self)

    var alphaMin = 255
    var alphaMax = 0
    var luminanceMin = 255
    var luminanceMax = 0
    var sampledPixelCount = 0

    for y in 0..<sampleHeight {
        for x in 0..<sampleWidth {
            let offset = (y * bytesPerRow) + (x * bytesPerPixel)
            let red = Int(pixels[offset])
            let green = Int(pixels[offset + 1])
            let blue = Int(pixels[offset + 2])
            let alpha = Int(pixels[offset + 3])
            let luminance = Int(round(0.2126 * Double(red) + 0.7152 * Double(green) + 0.0722 * Double(blue)))

            alphaMin = min(alphaMin, alpha)
            alphaMax = max(alphaMax, alpha)
            luminanceMin = min(luminanceMin, luminance)
            luminanceMax = max(luminanceMax, luminance)
            sampledPixelCount += 1
        }
    }

    return ImageReport(
        path: path,
        pixelWidth: width,
        pixelHeight: height,
        sampledPixelCount: sampledPixelCount,
        alphaMin: alphaMin,
        alphaMax: alphaMax,
        luminanceMin: luminanceMin,
        luminanceMax: luminanceMax,
        isFullyTransparent: alphaMax == 0,
        isUniform: alphaMin == alphaMax && luminanceMin == luminanceMax
    )
}

do {
    let paths = Array(CommandLine.arguments.dropFirst())
    guard !paths.isEmpty else { throw InspectError.usage }
    let reports = try paths.map(report(for:))
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    FileHandle.standardOutput.write(try encoder.encode(reports))
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch InspectError.usage {
    fputs("usage: catalog_png_inspect.swift <png-path>...\n", stderr)
    exit(64)
} catch let InspectError.unreadableImage(path) {
    fputs("error: unreadable image: \(path)\n", stderr)
    exit(66)
} catch let InspectError.unreadableBitmap(path) {
    fputs("error: unreadable bitmap: \(path)\n", stderr)
    exit(67)
} catch {
    fputs("error: \(error)\n", stderr)
    exit(1)
}
