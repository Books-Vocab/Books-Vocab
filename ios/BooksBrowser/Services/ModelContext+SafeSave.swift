import Foundation
import SwiftData
import os

extension ModelContext {
    /// `save()` with error logging — drop-in replacement for `try? save()`.
    func safeSave(file: String = #file, line: Int = #line) {
        do {
            try save()
        } catch {
            let fileName = URL(fileURLWithPath: file).lastPathComponent
            AppLog.data.error("ModelContext.save() failed [\(fileName):\(line)]: \(error.localizedDescription)")
        }
    }
}
