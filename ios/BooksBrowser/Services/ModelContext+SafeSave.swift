import Foundation
import SwiftData
import os

extension ModelContext {
    /// `save()` with error logging — drop-in replacement for `try? save()`.
    @discardableResult
    func safeSave(file: String = #file, line: Int = #line) -> Bool {
        do {
            try save()
            return true
        } catch {
            let fileName = URL(fileURLWithPath: file).lastPathComponent
            AppLog.data.error("ModelContext.save() failed [\(fileName):\(line)]: \(error.localizedDescription)")
            return false
        }
    }

    @MainActor @discardableResult
    func safeSaveWithToast(
        _ toastCoordinator: AppToastCoordinator,
        file: String = #file, line: Int = #line
    ) -> Bool {
        let ok = safeSave(file: file, line: line)
        if !ok { toastCoordinator.error("儲存失敗") }
        return ok
    }
}
