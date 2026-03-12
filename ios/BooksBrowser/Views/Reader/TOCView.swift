import SwiftUI
import ReadiumShared
import os

struct TOCView: View {
    let publication: Publication
    let onSelect: (ReadiumShared.Link) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var tocLinks: [ReadiumShared.Link] = []

    var body: some View {
        NavigationStack {
            List {
                ForEach(tocLinks.indices, id: \.self) { index in
                    let link = tocLinks[index]
                    Button {
                        onSelect(link)
                        dismiss()
                    } label: {
                        Text(link.title ?? "Untitled")
                            .font(AppFonts.body())
                    }
                }
            }
            .navigationTitle("目錄".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                }
            }
            .task {
                do {
                    let toc = try await publication.tableOfContents().get()
                    tocLinks = toc
                    AppLog.reader.info("TOC loaded: \(toc.count) items")
                    for (i, link) in toc.enumerated() {
                        AppLog.reader.debug("  [\(i)] \(link.title ?? "nil") → \(String(describing: link.url()))")
                    }
                    if toc.isEmpty {
                        AppLog.reader.warning("TOC is empty — this book may not have a table of contents")
                    }
                } catch {
                    AppLog.reader.error("TOC load failed: \(error.localizedDescription)")
                }
            }
        }
    }
}
