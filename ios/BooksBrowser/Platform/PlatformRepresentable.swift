//
//  PlatformRepresentable.swift
//  BooksBrowser
//
//  跨平台型別橋接
//

import SwiftUI

#if os(iOS)
import UIKit
typealias PlatformView = UIView
typealias PlatformColor = UIColor
typealias PlatformImage = UIImage
typealias PlatformFont = UIFont
typealias PlatformFontDescriptor = UIFontDescriptor
#elseif os(macOS)
import AppKit
typealias PlatformView = NSView
typealias PlatformColor = NSColor
typealias PlatformImage = NSImage
typealias PlatformFont = NSFont
typealias PlatformFontDescriptor = NSFontDescriptor
#endif
