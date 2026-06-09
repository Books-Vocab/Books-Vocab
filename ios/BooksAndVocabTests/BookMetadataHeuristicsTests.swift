//
//  BookMetadataHeuristicsTests.swift
//  Books & Vocab Tests
//
//  Pins the fallback heuristics shared between reconciler, manifest writer,
//  and metadata repair. Regressions here cause UUID titles or empty authors
//  to be treated as real data and harden into the database / CloudKit.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct BookMetadataHeuristicsTests {

    // MARK: - looksLikeFallbackTitle

    @Test func titleMatchingFileBaseIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackTitle("MyBook", fileName: "MyBook.epub"))
    }

    @Test func titleMatchingFileBaseWithDifferentExtensionIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackTitle("MyBook", fileName: "MyBook.pdf"))
    }

    @Test func uuidTitleIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackTitle(
            "550e8400-e29b-41d4-a716-446655440000",
            fileName: "something.epub"
        ))
    }

    @Test func shortUuidLikeTitleIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackTitle(
            "123e4567-e89b-12d3-a456-426614174000",
            fileName: "book.epub"
        ))
    }

    @Test func normalTitleIsNotFallback() {
        #expect(!BookMetadataHeuristics.looksLikeFallbackTitle(
            "Pride and Prejudice",
            fileName: "pride.epub"
        ))
    }

    @Test func titleWithPathLikeFileNameIsNotFallback() {
        // fileName contains path components; only the base name matters
        #expect(!BookMetadataHeuristics.looksLikeFallbackTitle(
            "Pride and Prejudice",
            fileName: "/Users/books/pride.epub"
        ))
    }

    // MARK: - looksLikeFallbackAuthor

    @Test func emptyAuthorIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackAuthor(""))
    }

    @Test func unknownAuthorIsFallback() {
        #expect(BookMetadataHeuristics.looksLikeFallbackAuthor("Unknown"))
    }

    @Test func realAuthorIsNotFallback() {
        #expect(!BookMetadataHeuristics.looksLikeFallbackAuthor("Jane Austen"))
    }

    @Test func authorWithWhitespaceIsNotFallback() {
        #expect(!BookMetadataHeuristics.looksLikeFallbackAuthor("  Jane Austen  "))
    }

    // MARK: - isUsableExtractedTitle

    @Test func emptyTitleIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle("", fileName: "book.epub"))
    }

    @Test func whitespaceOnlyTitleIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle("   \n\t  ", fileName: "book.epub"))
    }

    @Test func untitledPlaceholderIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle("Untitled", fileName: "book.epub"))
    }

    @Test func uuidTitleIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle(
            "550e8400-e29b-41d4-a716-446655440000",
            fileName: "book.epub"
        ))
    }

    @Test func fileBaseTitleIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle("MyBook", fileName: "MyBook.epub"))
    }

    @Test func normalTitleIsUsable() {
        #expect(BookMetadataHeuristics.isUsableExtractedTitle(
            "Pride and Prejudice",
            fileName: "pride.epub"
        ))
    }

    @Test func trimmedNormalTitleIsUsable() {
        #expect(BookMetadataHeuristics.isUsableExtractedTitle(
            "  Pride and Prejudice  ",
            fileName: "pride.epub"
        ))
    }

    @Test func trimmedUntitledIsStillNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedTitle(
            "  Untitled  ",
            fileName: "book.epub"
        ))
    }

    // MARK: - isUsableExtractedAuthor

    @Test func emptyAuthorIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedAuthor(""))
    }

    @Test func whitespaceOnlyAuthorIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedAuthor("   \n\t  "))
    }

    @Test func unknownPlaceholderIsNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedAuthor("Unknown"))
    }

    @Test func trimmedUnknownIsStillNotUsable() {
        #expect(!BookMetadataHeuristics.isUsableExtractedAuthor("  Unknown  "))
    }

    @Test func realAuthorIsUsable() {
        #expect(BookMetadataHeuristics.isUsableExtractedAuthor("Jane Austen"))
    }

    @Test func trimmedRealAuthorIsUsable() {
        #expect(BookMetadataHeuristics.isUsableExtractedAuthor("  Jane Austen  "))
    }
}
