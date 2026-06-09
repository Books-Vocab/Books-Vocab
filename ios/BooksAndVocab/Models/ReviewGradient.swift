import SwiftUI

enum ReviewGradient {

    // MARK: - Public API

    static func color(for ratio: Double) -> Color {
        let clamped = max(ratio, 0)
        let hsl = interpolate(ratio: clamped)
        return Color(hue: hsl.h / 360, saturation: hsl.s / 100, brightness: hslToHSB(s: hsl.s, l: hsl.l).b / 100)
    }

    static func cssHex(for ratio: Double) -> String {
        let clamped = max(ratio, 0)
        let hsl = interpolate(ratio: clamped)
        let rgb = hslToRGB(h: hsl.h, s: hsl.s / 100, l: hsl.l / 100)
        return String(format: "#%02X%02X%02X", Int(rgb.r * 255), Int(rgb.g * 255), Int(rgb.b * 255))
    }

    // MARK: - Stops (Scheme C — high saturation greens, dark overdue)

    private struct HSL {
        let h: Double
        let s: Double
        let l: Double
    }

    private struct Stop {
        let at: Double
        let c: HSL
    }

    private static let stops: [Stop] = [
        Stop(at: 0.00, c: HSL(h: 160, s: 48, l: 38)),   // 翠綠
        Stop(at: 0.15, c: HSL(h: 150, s: 44, l: 40)),
        Stop(at: 0.30, c: HSL(h: 138, s: 42, l: 42)),
        Stop(at: 0.45, c: HSL(h: 122, s: 38, l: 44)),
        Stop(at: 0.60, c: HSL(h: 105, s: 38, l: 45)),
        Stop(at: 0.72, c: HSL(h:  85, s: 40, l: 46)),   // 萊姆
        Stop(at: 0.85, c: HSL(h:  60, s: 48, l: 46)),   // 琥珀
        Stop(at: 1.00, c: HSL(h:  45, s: 55, l: 48)),   // 到期黃
        Stop(at: 1.30, c: HSL(h:  28, s: 65, l: 44)),   // 深橘
        Stop(at: 2.00, c: HSL(h:   4, s: 58, l: 40)),   // 暗紅
        Stop(at: 3.00, c: HSL(h: 278, s: 50, l: 34)),   // 暗紫
    ]

    // MARK: - Interpolation

    private static func interpolate(ratio: Double) -> HSL {
        guard let firstStop = stops.first, let lastStop = stops.last else {
            return HSL(h: 0, s: 0, l: 50)
        }
        if ratio <= firstStop.at { return firstStop.c }
        if ratio >= lastStop.at { return lastStop.c }

        for i in 0 ..< stops.count - 1 {
            let s0 = stops[i], s1 = stops[i + 1]
            if ratio <= s1.at {
                let t = (ratio - s0.at) / (s1.at - s0.at)
                return lerpHSL(s0.c, s1.c, t: t)
            }
        }
        return lastStop.c
    }

    private static func lerpHSL(_ a: HSL, _ b: HSL, t: Double) -> HSL {
        var dh = b.h - a.h
        if dh > 180 { dh -= 360 }
        if dh < -180 { dh += 360 }
        let h = (a.h + dh * t).truncatingRemainder(dividingBy: 360)
        return HSL(
            h: h < 0 ? h + 360 : h,
            s: a.s + (b.s - a.s) * t,
            l: a.l + (b.l - a.l) * t
        )
    }

    // MARK: - Color space conversion

    private static func hslToHSB(s: Double, l: Double) -> (s: Double, b: Double) {
        let sF = s / 100, lF = l / 100
        let b = lF + sF * min(lF, 1 - lF)
        let sB = b == 0 ? 0 : 2 * (1 - lF / b)
        return (sB * 100, b * 100)
    }

    private static func hslToRGB(h: Double, s: Double, l: Double) -> (r: Double, g: Double, b: Double) {
        let c = (1 - abs(2 * l - 1)) * s
        let x = c * (1 - abs((h / 60).truncatingRemainder(dividingBy: 2) - 1))
        let m = l - c / 2
        let (r1, g1, b1): (Double, Double, Double)
        switch h {
        case 0..<60:    (r1, g1, b1) = (c, x, 0)
        case 60..<120:  (r1, g1, b1) = (x, c, 0)
        case 120..<180: (r1, g1, b1) = (0, c, x)
        case 180..<240: (r1, g1, b1) = (0, x, c)
        case 240..<300: (r1, g1, b1) = (x, 0, c)
        default:        (r1, g1, b1) = (c, 0, x)
        }
        return (r1 + m, g1 + m, b1 + m)
    }
}
