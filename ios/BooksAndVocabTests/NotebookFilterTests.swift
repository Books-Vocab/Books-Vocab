//
//  NotebookFilterTests.swift
//  Books & Vocab Tests
//
//  Pins NotebookFilter.matches / save / load. The filter is shared between
//  review and stats — a regression silently drops or includes the wrong
//  notebook subset in both features.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct NotebookFilterTests {

    // MARK: - matches

    @Test func emptyFilterMatchesEverything() {
        let filter = NotebookFilter()
        #expect(filter.matches("nb-a"))
        #expect(filter.matches("nb-b"))
    }

    @Test func nonEmptyFilterMatchesOnlySelected() {
        let filter = NotebookFilter(selectedIds: ["nb-a", "nb-c"])
        #expect(filter.matches("nb-a"))
        #expect(!filter.matches("nb-b"))
        #expect(filter.matches("nb-c"))
    }

    @Test func isFilteredFalseWhenEmpty() {
        let filter = NotebookFilter()
        #expect(!filter.isFiltered)
    }

    @Test func isFilteredTrueWhenNonEmpty() {
        let filter = NotebookFilter(selectedIds: ["nb-a"])
        #expect(filter.isFiltered)
    }

    // MARK: - save / load round-trip

    @Test func saveAndLoadRoundTrip() {
        let suite = UserDefaults(suiteName: #file)
        defer { suite?.removePersistentDomain(forName: #file) }

        var filter = NotebookFilter(selectedIds: ["nb-x", "nb-y"])
        filter.save(to: suite!)

        let loaded = NotebookFilter.load(from: suite!)
        #expect(loaded.selectedIds == ["nb-x", "nb-y"])
        #expect(loaded.isFiltered)
    }

    @Test func loadReturnsEmptyWhenNeverSaved() {
        let suite = UserDefaults(suiteName: #file)
        defer { suite?.removePersistentDomain(forName: #file) }

        let loaded = NotebookFilter.load(from: suite!)
        #expect(loaded.selectedIds.isEmpty)
        #expect(!loaded.isFiltered)
    }

    @Test func saveEmptyFilterAndLoadRoundTrip() {
        let suite = UserDefaults(suiteName: #file)
        defer { suite?.removePersistentDomain(forName: #file) }

        var filter = NotebookFilter()
        filter.save(to: suite!)

        let loaded = NotebookFilter.load(from: suite!)
        #expect(loaded.selectedIds.isEmpty)
        #expect(!loaded.isFiltered)
    }
}
