//
//  VocabPalette.swift
//  BooksBrowser
//
//  生詞庫專用配色：比書庫更明亮、輕巧、現代。
//

import SwiftUI

enum VocabPalette {
    static let background = Color(red: 0.952, green: 0.972, blue: 0.995)
    static let surface = Color.white.opacity(0.84)
    static let surfaceStrong = Color.white.opacity(0.94)
    static let line = Color(red: 0.13, green: 0.23, blue: 0.42).opacity(0.08)

    static let primary = Color(red: 0.16, green: 0.44, blue: 0.94)
    static let accent = Color(red: 0.04, green: 0.72, blue: 0.68)
    static let warm = Color(red: 0.97, green: 0.56, blue: 0.31)
    static let success = Color(red: 0.14, green: 0.69, blue: 0.52)

    static let textMuted = Color.black.opacity(0.54)
}
