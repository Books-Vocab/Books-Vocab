#!/usr/bin/env swift

import AppKit
import Foundation

struct ImageReport: Encodable {
    let path: String
    let pixelWidth: Int
    let pixelHeight: Int
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

private func clampByte(_ value: CGFloat) -> Int {
    Int(max(0, min(255, lround(Double(value * 255.0)))))
}

private func report(for path: String) throws -> ImageReport {
    guard
        let image = NSImage(contentsOfFile: path),
        let tiff = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff)
    else {
        throw InspectError.unreadableImage(path)
    }

    let width = bitmap.pixelsWide
    let height = bitmap.pixelsHigh
    guard width > 0, height > 0 else {
        throw InspectError.unreadableBitmap(path)
    }

    var alphaMin = 255
    var alphaMax = 0
    var luminanceMin = 255
    var luminanceMax = 0

    for y in 0 ..< height {
        for x in 0 ..< width {
            guard let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else {
                throw InspectError.unreadableBitmap(path)
            }
            let alpha = clampByte(color.alphaComponent)
            let red = clampByte(color.redComponent)
            let green = clampByte(color.greenComponent)
            let blue = clampByte(color.blueComponent)
            let luminance = Int(round(0.2126 * Double(red) + 0.7152 * Double(green) + 0.0722 * Double(blue)))

            alphaMin = min(alphaMin, alpha)
            alphaMax = max(alphaMax, alpha)
            luminanceMin = min(luminanceMin, luminance)
            luminanceMax = max(luminanceMax, luminance)
        }
    }

    return ImageReport(
        path: path,
        pixelWidth: width,
        pixelHeight: height,
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
