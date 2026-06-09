//
//  BookFormatTests.swift
//  Books & Vocab Tests
//
//  Pins Book.format fallback for CloudKit migration safety.
//  Old records may lack formatRaw; a regression here breaks format detection.
//

import Testing
@testable import BooksAndVocab

struct BookFormatTests {

    @Test func validEpubRawValueReturnsEpub() {
        let book = Book(title: "T", author: "A", fileName: "f.epub")
        book.formatRaw = BookFormat.epub.rawValue
        #expect(book.format == .epub)
    }

    @Test func validPdfRawValueReturnsPdf() {
        let book = Book(title: "T", author: "A", fileName: "f.pdf")
        book.formatRaw = BookFormat.pdf.rawValue
        #expect(book.format == .pdf)
    }

    @Test func validTxtRawValueReturnsTxt() {
        let book = Book(title: "T", author: "A", fileName: "f.txt")
        book.formatRaw = BookFormat.txt.rawValue
        #expect(book.format == .txt)
    }

    @Test func validMdRawValueReturnsMd() {
        let book = Book(title: "T", author: "A", fileName: "f.md")
        book.formatRaw = BookFormat.md.rawValue
        #expect(book.format == .md)
    }

    @Test func unknownRawValueFallsBackToEpub() {
        let book = Book(title: "T", author: "A", fileName: "f.epub")
        book.formatRaw = "unknown_format"
        #expect(book.format == .epub)
    }

    @Test func emptyRawValueFallsBackToEpub() {
        let book = Book(title: "T", author: "A", fileName: "f.epub")
        book.formatRaw = ""
        #expect(book.format == .epub)
    }

    @Test func setterUpdatesRawValue() {
        let book = Book(title: "T", author: "A", fileName: "f.epub")
        book.format = .pdf
        #expect(book.formatRaw == BookFormat.pdf.rawValue)
    }
}
