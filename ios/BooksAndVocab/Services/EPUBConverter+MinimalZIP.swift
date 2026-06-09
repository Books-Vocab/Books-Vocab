import Foundation
import zlib

// MARK: - MinimalZIP

/// Pure-Swift ZIP archive builder using stored (no compression) method.
/// Uses system zlib only for CRC-32 calculation.
///
/// Used by `EPUBConverter.buildEPUB` to assemble the `.epub` archive.
struct MinimalZIP {
    private struct Entry {
        let name: String
        let data: Data
        let crc32: UInt32
        let offset: UInt32
    }

    private var entries: [Entry] = []
    private var payload = Data()

    mutating func addEntry(name: String, data: Data) {
        let crc = crc32Checksum(data)
        let offset = UInt32(payload.count)

        let nameData = Data(name.utf8)
        let nameLen = UInt16(nameData.count)
        let size = UInt32(data.count)

        // DOS date/time: 2025-01-01 00:00:00
        let modTime: UInt16 = 0
        let modDate: UInt16 = (45 << 9) | (1 << 5) | 1 // year=2025-1980=45

        // Local file header
        var header = Data()
        header.appendUInt32(0x04034b50) // signature
        header.appendUInt16(20)         // version needed
        header.appendUInt16(0)          // flags
        header.appendUInt16(0)          // method (stored)
        header.appendUInt16(modTime)
        header.appendUInt16(modDate)
        header.appendUInt32(crc)
        header.appendUInt32(size)       // compressed size
        header.appendUInt32(size)       // uncompressed size
        header.appendUInt16(nameLen)
        header.appendUInt16(0)          // extra length
        header.append(nameData)
        header.append(data)

        payload.append(header)
        entries.append(Entry(name: name, data: data, crc32: crc, offset: offset))
    }

    func finalize() -> Data {
        var result = payload

        let cdOffset = UInt32(result.count)
        var cdSize: UInt32 = 0

        // DOS date/time matching local headers
        let modTime: UInt16 = 0
        let modDate: UInt16 = (45 << 9) | (1 << 5) | 1

        for entry in entries {
            let nameData = Data(entry.name.utf8)
            let nameLen = UInt16(nameData.count)
            let size = UInt32(entry.data.count)

            var cd = Data()
            cd.appendUInt32(0x02014b50) // signature
            cd.appendUInt16(20)         // version made by
            cd.appendUInt16(20)         // version needed
            cd.appendUInt16(0)          // flags
            cd.appendUInt16(0)          // method
            cd.appendUInt16(modTime)
            cd.appendUInt16(modDate)
            cd.appendUInt32(entry.crc32)
            cd.appendUInt32(size)       // compressed
            cd.appendUInt32(size)       // uncompressed
            cd.appendUInt16(nameLen)
            cd.appendUInt16(0)          // extra length
            cd.appendUInt16(0)          // comment length
            cd.appendUInt16(0)          // disk number start
            cd.appendUInt16(0)          // internal attributes
            cd.appendUInt32(0)          // external attributes
            cd.appendUInt32(entry.offset)
            cd.append(nameData)

            result.append(cd)
            cdSize += UInt32(cd.count)
        }

        // End of central directory
        let count = UInt16(entries.count)
        var eocd = Data()
        eocd.appendUInt32(0x06054b50) // signature
        eocd.appendUInt16(0)          // disk number
        eocd.appendUInt16(0)          // disk with CD
        eocd.appendUInt16(count)      // entries on disk
        eocd.appendUInt16(count)      // total entries
        eocd.appendUInt32(cdSize)
        eocd.appendUInt32(cdOffset)
        eocd.appendUInt16(0)          // comment length

        result.append(eocd)
        return result
    }

    private func crc32Checksum(_ data: Data) -> UInt32 {
        data.withUnsafeBytes { buffer in
            let ptr = buffer.bindMemory(to: UInt8.self).baseAddress
            return UInt32(zlib.crc32(0, ptr, uInt(data.count)))
        }
    }
}

private extension Data {
    mutating func appendUInt16(_ value: UInt16) {
        var le = value.littleEndian
        append(Data(bytes: &le, count: 2))
    }

    mutating func appendUInt32(_ value: UInt32) {
        var le = value.littleEndian
        append(Data(bytes: &le, count: 4))
    }
}
