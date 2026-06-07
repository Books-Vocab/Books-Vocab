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
    let isUniform: Bool
}

private enum InspectError: Error {
    case usage
    case unreadableImage(String)
    case unreadableBitmap(String)
}

private func sampleCoordinates(length: Int, targetBuckets: Int = 64) -> [Int] {
    guard length > 0 else { return [] }
    let step = max(1, length / targetBuckets)
    var coordinates = Array(stride(from: 0, to: length, by: step))
    if coordinates.last != length - 1 {
        coordinates.append(length - 1)
    }
    return coordinates
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

    let bytesPerPixel = 4
    let bitsPerComponent = 8
    let bytesPerRow = width * bytesPerPixel
    guard
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: bitsPerComponent,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ),
        let data = context.data
    else {
        throw InspectError.unreadableBitmap(path)
    }

    let rect = CGRect(x: 0, y: 0, width: width, height: height)
    context.draw(cgImage, in: rect)
    let pixels = data.assumingMemoryBound(to: UInt8.self)

    var alphaMin = 255
    var alphaMax = 0
    var luminanceMin = 255
    var luminanceMax = 0
    let sampleXs = sampleCoordinates(length: width)
    let sampleYs = sampleCoordinates(length: height)
    var sampledPixelCount = 0

    for y in sampleYs {
        for x in sampleXs {
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
