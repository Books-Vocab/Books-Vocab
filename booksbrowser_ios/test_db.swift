import Foundation
import SwiftData

// Read SQLite DB to see if records exist
let fileManager = FileManager.default
guard let appSupportURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
    print("Cannot find App Support")
    exit(1)
}

// Find the SQLite database for the app
let bundleID = "com.Max0228.BooksBrowser"
let dbURL = appSupportURL.appendingPathComponent("default.store")
print("DB Path: \(dbURL.path)")

if fileManager.fileExists(atPath: dbURL.path) {
    print("Database exists!")
} else {
    print("Database NOT FOUND at expected location.")
}
