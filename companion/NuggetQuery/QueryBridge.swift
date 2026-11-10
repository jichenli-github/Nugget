import Foundation
import Darwin
import CryptoKit

struct QueryFile: Codable, Equatable {
    let domain: String
    let path: String
    let operation: String
    let contents: Data
    let containerHint: String?
    var baseline: Data? = nil
}

struct QueryRequest: Codable {
    let protocolVersion: Int
    let id: String
    let build: String
    let version: String
    let operation: String
    let contents: Data
    let files: [QueryFile]?
    enum CodingKeys: String, CodingKey {
        case protocolVersion = "protocol"
        case id, build, version, operation, contents, files
    }
    var entries: [QueryFile] {
        files ?? [QueryFile(domain: QueryBridge.mgaDomain, path: QueryBridge.mgaPath,
                            operation: operation, contents: contents, containerHint: nil)]
    }
}

struct QueryResult: Codable {
    let protocolVersion: Int
    let id: String
    let build: String
    let success: Bool
    let message: String
    enum CodingKeys: String, CodingKey {
        case protocolVersion = "protocol"
        case id, build, success, message
    }
}

struct OriginalBackup: Codable {
    let build: String
    let contents: Data
}

struct ContainerBackup: Codable {
    let build: String
    let domain: String
    let path: String
    let contents: Data?
}

enum QueryError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        if case .message(let message) = self { return message }
        return nil
    }
}

/// Protocol 2 grants container-relative access only, never arbitrary /var access.
/// The host's container hints are checked against the on-device container ID.
enum QueryBridge {
    static let files = FileManager.default
    static let documents = files.urls(for: .documentDirectory, in: .userDomainMask)[0]
    static let pending = documents.appendingPathComponent("NuggetQuery-pending.plist")
    static let processing = documents.appendingPathComponent("NuggetQuery-processing.plist")
    static let result = documents.appendingPathComponent("NuggetQuery-result.plist")
    static let mgaDomain = "SysSharedContainerDomain-systemgroup.com.apple.mobilegestaltcache"
    static let mgaPath = "Library/Caches/com.apple.MobileGestalt.plist"
    static let container = "/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache"
    static let target = URL(fileURLWithPath: container + "/" + mgaPath)

    static func currentBuild() throws -> String {
        var size = 0
        guard sysctlbyname("kern.osversion", nil, &size, nil, 0) == 0, size > 0 else {
            throw QueryError.message("Could not determine the system build.")
        }
        var value = [CChar](repeating: 0, count: size)
        guard sysctlbyname("kern.osversion", &value, &size, nil, 0) == 0 else {
            throw QueryError.message("Could not read the system build.")
        }
        return String(cString: value)
    }

    static func validateOS() throws {
        let os = ProcessInfo.processInfo.operatingSystemVersion
        guard os.majorVersion == 27, os.minorVersion < 2 || (os.minorVersion == 2 && os.patchVersion == 0) else {
            throw QueryError.message("This experimental bridge supports iOS 27.0–27.2 only.")
        }
    }

    static func plist(_ data: Data) throws -> [String: Any] {
        guard let value = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any] else {
            throw QueryError.message("Expected a dictionary plist.")
        }
        return value
    }

    static func validatePlist(_ data: Data) throws {
        guard try plist(data)["CacheExtra"] is [String: Any] else {
            throw QueryError.message("This is not a MobileGestalt plist (CacheExtra is missing).")
        }
    }

    static func validateEntry(_ entry: QueryFile) throws {
        let prefixes = ["SysSharedContainerDomain-", "SysContainerDomain-", "AppDomain-", "AppDomainGroup-", "AppDomainPlugin-", "ContainerPathDomain-"]
        guard let prefix = prefixes.first(where: { entry.domain.hasPrefix($0) }) else {
            throw QueryError.message("worse_query does not support domain \(entry.domain).")
        }
        let identifier = String(entry.domain.dropFirst(prefix.count))
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
        guard let first = identifier.unicodeScalars.first,
              CharacterSet.alphanumerics.contains(first), identifier.unicodeScalars.allSatisfy({ allowed.contains($0) }),
              !entry.path.isEmpty, !entry.path.hasPrefix("/"), !entry.path.contains("\0"), !entry.path.contains("\\"),
              entry.path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
              ["write", "merge_plist", "restore_original"].contains(entry.operation) else {
            throw QueryError.message("Invalid container destination or operation.")
        }
        if prefix == "ContainerPathDomain-" {
            let parts = identifier.split(separator: "-", maxSplits: 1)
            guard parts.count == 2, ["Application", "InternalDaemon", "PluginKitPlugin"].contains(String(parts[0])),
                  UUID(uuidString: String(parts[1])) != nil else { throw QueryError.message("Invalid container UUID.") }
        }
        if entry.domain == mgaDomain && entry.path == mgaPath {
            guard entry.operation != "merge_plist" else { throw QueryError.message("MobileGestalt requires a complete plist.") }
            if entry.operation == "write" { try validatePlist(entry.contents) }
            if let baseline = entry.baseline { try validatePlist(baseline) }
        } else if entry.operation == "merge_plist" {
            _ = try plist(entry.contents)
        }
    }

    static func load() throws -> QueryRequest {
        try validateOS()
        guard !files.fileExists(atPath: processing.path) else {
            throw QueryError.message("An interrupted request exists. Check current files before discarding it and retrying.")
        }
        let request = try PropertyListDecoder().decode(QueryRequest.self, from: Data(contentsOf: pending))
        guard [1, 2].contains(request.protocolVersion), UUID(uuidString: request.id) != nil,
              request.build == (try currentBuild()) else {
            throw QueryError.message("Request protocol or system build does not match this device. Update Nugget and its companion together.")
        }
        let os = ProcessInfo.processInfo.operatingSystemVersion
        let components = request.version.split(separator: ".", omittingEmptySubsequences: false)
        let parts = components.compactMap { Int($0) }
        guard parts.count == components.count, (1...3).contains(parts.count),
              parts + Array(repeating: 0, count: 3 - parts.count) == [os.majorVersion, os.minorVersion, os.patchVersion],
              (request.protocolVersion == 1 && request.files == nil && ["write", "restore_original"].contains(request.operation)) ||
              (request.protocolVersion == 2 && request.operation == "batch" && request.files != nil) else {
            throw QueryError.message("Invalid operation or system version.")
        }
        guard (1...4096).contains(request.entries.count),
              request.entries.reduce(0, { $0 + $1.contents.count + ($1.baseline?.count ?? 0) }) <= 256 * 1024 * 1024 else {
            throw QueryError.message("Request exceeds the container batch limits.")
        }
        var seen = Set<String>()
        for entry in request.entries {
            try validateEntry(entry)
            guard seen.insert(entry.domain + "/" + entry.path).inserted else { throw QueryError.message("Duplicate destination.") }
        }
        return request
    }

    static func acquire(_ path: String) throws -> Int64 {
        try validateOS()
        // GestaltX resolves the actual signed App Group, which survives re-signing.
        guard let group = GXEntitlementsReader.usableAppGroup() else {
            throw QueryError.message("No usable signed App Group. Re-sign NuggetQuery with a dedicated App Group.")
        }
        let handle = worse_query(path, group, false, false)
        guard handle >= 0 else { throw QueryError.message("worse_query denied \(path) (\(handle)). Check signing, OS and filesystem permissions.") }
        return handle
    }

    static func withAccess<T>(_ body: () throws -> T) throws -> T {
        // Request the cache directory, as GestaltX does, rather than a broader root.
        let handle = try acquire(target.deletingLastPathComponent().path)
        defer { worse_query_release(handle) }
        return try body()
    }

    static func identifier(at url: URL) -> String? {
        var buffer = [CChar](repeating: 0, count: 1024)
        let length = getxattr(url.path, "com.apple.containermanager.identifier", &buffer, buffer.count - 1, 0, 0)
        guard length > 0 else { return nil }
        return String(cString: buffer)
    }

    static func findContainer(in root: String, identifier expected: String, handles: inout [Int64]) throws -> URL? {
        handles.append(try acquire(root))
        let urls = try files.contentsOfDirectory(at: URL(fileURLWithPath: root), includingPropertiesForKeys: nil)
        let matches = urls.filter { identifier(at: $0) == expected || (UUID(uuidString: expected) != nil && $0.lastPathComponent == expected) }
        guard matches.count <= 1 else { throw QueryError.message("Ambiguous container: \(expected)") }
        return matches.first
    }

    static func resolve(_ entry: QueryFile, handles: inout [Int64]) throws -> URL {
        if entry.domain.hasPrefix("ContainerPathDomain-") {
            let parts = entry.domain.dropFirst("ContainerPathDomain-".count).split(separator: "-", maxSplits: 1)
            let root = URL(fileURLWithPath: "/var/mobile/Containers/Data/\(parts[0])/\(parts[1])")
            handles.append(try acquire(root.path))
            return root
        }
        if entry.domain.hasPrefix("SysSharedContainerDomain-") {
            let name = String(entry.domain.dropFirst("SysSharedContainerDomain-".count))
            let root = URL(fileURLWithPath: "/var/containers/Shared/SystemGroup/" + name)
            handles.append(try acquire(entry.domain == mgaDomain ? target.deletingLastPathComponent().path : root.path))
            return root
        }
        let prefixes = ["SysContainerDomain-", "AppDomainGroup-", "AppDomainPlugin-", "AppDomain-"]
        let prefix = prefixes.first { entry.domain.hasPrefix($0) }!
        let name = String(entry.domain.dropFirst(prefix.count))
        if prefix == "AppDomainGroup-" {
            if let root = try findContainer(in: "/var/mobile/Containers/Shared/AppGroup", identifier: name, handles: &handles) { return root }
        } else {
            // System-container parent access is available on iOS 27. AppDomain
            // may refer to a system service such as PosterBoard.
            if let hint = entry.containerHint {
                let normalized = hint.hasPrefix("/private/var/") ? String(hint.dropFirst(8)) : hint
                let parents = ["/var/mobile/Containers/Data/Application/", "/var/mobile/Containers/Data/InternalDaemon/", "/var/mobile/Containers/Data/PluginKitPlugin/"]
                if let parent = parents.first(where: { normalized.hasPrefix($0) }),
                   UUID(uuidString: String(normalized.dropFirst(parent.count))) != nil {
                    handles.append(try acquire(normalized))
                    let root = URL(fileURLWithPath: normalized)
                    guard identifier(at: root) == name else { throw QueryError.message("Container hint does not match \(name).") }
                    return root
                }
            }
            if let root = try findContainer(in: "/var/containers/Data/System", identifier: name, handles: &handles) { return root }
        }
        throw QueryError.message("Cannot resolve container \(name). No device files have been written. This container needs a valid on-device path.")
    }

    static func safeTarget(_ entry: QueryFile, root: URL) throws -> URL {
        let canonical = root.resolvingSymlinksInPath().standardizedFileURL
        let expectedRoot = root.deletingLastPathComponent().resolvingSymlinksInPath().appendingPathComponent(root.lastPathComponent).standardizedFileURL
        guard canonical == expectedRoot else { throw QueryError.message("Container root is a symlink.") }
        let url = root.appendingPathComponent(entry.path).standardizedFileURL
        let resolved = url.resolvingSymlinksInPath().standardizedFileURL
        guard resolved.path.hasPrefix(canonical.path + "/"), resolved.path == canonical.appendingPathComponent(entry.path).path else {
            throw QueryError.message("Refusing a symlink or container escape: \(entry.path)")
        }
        return resolved
    }

    struct Prepared {
        let entry: QueryFile
        let url: URL
        let original: Data?
        let replacement: Data?
    }

    static func backupURL(_ entry: QueryFile, build: String) -> URL {
        let hash = SHA256.hash(data: Data((entry.domain + "/" + entry.path).utf8)).map { String(format: "%02x", $0) }.joined()
        return documents.appendingPathComponent("NuggetQuery-backups/\(build)/\(hash).plist")
    }

    static func prepare(_ entry: QueryFile, root: URL, build: String) throws -> Prepared {
        let url = try safeTarget(entry, root: root)
        var isDirectory: ObjCBool = false
        let exists = files.fileExists(atPath: url.path, isDirectory: &isDirectory)
        guard !isDirectory.boolValue else {
            throw QueryError.message("Directory reset is not supported by this bridge: \(entry.path). No target files were written.")
        }
        let original = exists ? try Data(contentsOf: url) : nil
        if exists {
            let descriptor = open(url.path, O_WRONLY | O_NOFOLLOW)
            guard descriptor >= 0 else { throw QueryError.message("File is not writable: \(entry.domain)/\(entry.path) (errno \(errno)).") }
            close(descriptor)
        } else {
            var parent = url.deletingLastPathComponent()
            while !files.fileExists(atPath: parent.path) { parent.deleteLastPathComponent() }
            guard access(parent.path, W_OK) == 0 else { throw QueryError.message("Parent directory is not writable: \(parent.path)") }
        }
        let backup = backupURL(entry, build: build)
        var replacement: Data? = entry.contents
        if entry.operation == "restore_original" {
            if entry.domain == mgaDomain && entry.path == mgaPath {
                // Preserve compatibility with backups made by the protocol-1 IPA.
                let legacy = documents.appendingPathComponent("MobileGestalt-original-\(build).plist")
                if files.fileExists(atPath: legacy.path) {
                    let saved = try PropertyListDecoder().decode(OriginalBackup.self, from: Data(contentsOf: legacy))
                    guard saved.build == build else { throw QueryError.message("Backup build mismatch.") }
                    replacement = saved.contents
                } else { replacement = try readBackup(backup, entry: entry, build: build).contents }
            } else { replacement = try readBackup(backup, entry: entry, build: build).contents }
        } else if entry.operation == "merge_plist" {
            var combined = try original.map { try plist($0) } ?? [:]
            combined.merge(try plist(entry.contents)) { _, new in new }
            replacement = try PropertyListSerialization.data(fromPropertyList: combined, format: .binary, options: 0)
        }
        if entry.domain == mgaDomain && entry.path == mgaPath {
            guard let original, let proposed = replacement else { throw QueryError.message("MobileGestalt must exist before applying or restoring.") }
            try validatePlist(proposed)
            let before = try plist(original)
            var after = try plist(proposed)
            if entry.operation == "write", let baseline = entry.baseline {
                let source = try plist(baseline)
                guard let previous = source["CacheExtra"] as? [String: Any],
                      let edited = after["CacheExtra"] as? [String: Any],
                      var current = before["CacheExtra"] as? [String: Any] else { throw QueryError.message("Invalid MobileGestalt baseline.") }
                // Rebase only edited keys onto the fresh device file; reject a
                // conflict instead of overwriting another app's newer changes.
                for key in Set(previous.keys).union(edited.keys) where !equal(previous[key], edited[key]) {
                    guard equal(current[key], previous[key]) else { throw QueryError.message("MobileGestalt key changed on-device: \(key). Export it again before applying.") }
                    current[key] = edited[key]
                }
                after["CacheExtra"] = current
            }
            let immutable = ["UniqueDeviceID", "SerialNumber", "UniqueChipID", "re6Zb+zwFKJNlkQTUeT+/w", "VasUgeSzVyHdB27g2XpN0g", "TF31PAB6aO8KAbPyNKSxKA"]
            let beforeExtra = before["CacheExtra"] as? [String: Any] ?? [:]
            let afterExtra = after["CacheExtra"] as? [String: Any] ?? [:]
            guard immutable.allSatisfy({ equal(beforeExtra[$0], afterExtra[$0]) }) else { throw QueryError.message("MobileGestalt device identity differs from the current file.") }
            // Never replace another cache layout or silently overwrite CacheData.
            for key in ["CacheUUID", "CacheVersion", "CacheData"] {
                guard NSDictionary(dictionary: ["value": before[key] ?? NSNull()]).isEqual(to: ["value": after[key] ?? NSNull()]) else {
                    throw QueryError.message("MobileGestalt \(key) differs from this device. Export a fresh file for this build.")
                }
            }
            replacement = try PropertyListSerialization.data(fromPropertyList: after, format: .binary, options: 0)
        }
        return Prepared(entry: entry, url: url, original: original, replacement: replacement)
    }

    static func equal(_ lhs: Any?, _ rhs: Any?) -> Bool {
        NSDictionary(dictionary: ["value": lhs ?? NSNull()]).isEqual(to: ["value": rhs ?? NSNull()])
    }

    static func readBackup(_ url: URL, entry: QueryFile, build: String) throws -> ContainerBackup {
        let saved = try PropertyListDecoder().decode(ContainerBackup.self, from: Data(contentsOf: url))
        guard saved.build == build, saved.domain == entry.domain, saved.path == entry.path else { throw QueryError.message("Backup destination or build mismatch.") }
        return saved
    }

    static func replace(_ data: Data?, at url: URL) throws {
        guard let data else {
            if files.fileExists(atPath: url.path) { try files.removeItem(at: url) }
            return
        }
        try files.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let exists = files.fileExists(atPath: url.path)
        let descriptor = open(url.path, O_WRONLY | O_NOFOLLOW | (exists ? 0 : O_CREAT | O_EXCL), mode_t(0o644))
        guard descriptor >= 0 else { throw QueryError.message("Cannot open \(url.lastPathComponent) (errno \(errno)).") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        try handle.write(contentsOf: data)
        try handle.truncate(atOffset: UInt64(data.count))
        try handle.synchronize()
        guard try Data(contentsOf: url) == data else { throw QueryError.message("Read-back verification failed: \(url.lastPathComponent)") }
    }

    static func update(_ request: QueryRequest) throws {
        var handles: [Int64] = []
        defer { for handle in handles.reversed() { worse_query_release(handle) } }
        var roots: [String: URL] = [:]
        var prepared: [Prepared] = []
        // Resolve and preflight EVERY entry before backing up or writing any target.
        for entry in request.entries {
            let root: URL
            if let existing = roots[entry.domain] { root = existing }
            else {
                root = try resolve(entry, handles: &handles)
                roots[entry.domain] = root
            }
            let item = try prepare(entry, root: root, build: request.build)
            guard !prepared.contains(where: { $0.url == item.url }) else { throw QueryError.message("Multiple domains resolve to the same target file.") }
            prepared.append(item)
        }
        // Back up every original first, before the first device file is changed.
        for item in prepared where item.entry.operation != "restore_original" {
            let url = backupURL(item.entry, build: request.build)
            if !files.fileExists(atPath: url.path) {
                try files.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                let saved = ContainerBackup(build: request.build, domain: item.entry.domain, path: item.entry.path, contents: item.original)
                try PropertyListEncoder().encode(saved).write(to: url, options: .atomic)
            }
        }
        var attempted: [Prepared] = []
        do {
            for item in prepared {
                let current = files.fileExists(atPath: item.url.path) ? try Data(contentsOf: item.url) : nil
                guard current == item.original else { throw QueryError.message("File changed during preflight: \(item.entry.path)") }
                attempted.append(item)
                try replace(item.replacement, at: item.url)
            }
        } catch {
            let reason = error.localizedDescription
            var failures: [String] = []
            for item in attempted.reversed() {
                do { try replace(item.original, at: item.url) }
                catch { failures.append(item.entry.domain + "/" + item.entry.path + ": " + error.localizedDescription) }
            }
            if !failures.isEmpty { throw QueryError.message("Write failed: \(reason). Rollback incomplete: \(failures.joined(separator: "; ")). Keep the backups and inspect the device.") }
            throw QueryError.message("Write failed; previous file contents restored: \(reason)")
        }
    }

    static func apply(_ displayed: QueryRequest) throws -> String {
        let request = try load()
        guard request.id == displayed.id, request.entries == displayed.entries, request.operation == displayed.operation else {
            throw QueryError.message("The request changed. Load it again before applying.")
        }
        try files.moveItem(at: pending, to: processing)
        let outcome: QueryResult
        do {
            try update(request)
            outcome = QueryResult(protocolVersion: request.protocolVersion, id: request.id, build: request.build,
                                  success: true, message: "\(request.entries.count) container file(s) verified. Restart the device to see changes.")
        } catch {
            outcome = QueryResult(protocolVersion: request.protocolVersion, id: request.id, build: request.build,
                                  success: false, message: error.localizedDescription)
        }
        try PropertyListEncoder().encode(outcome).write(to: result, options: .atomic)
        try files.removeItem(at: processing)
        if !outcome.success { throw QueryError.message(outcome.message) }
        return outcome.message
    }

    static func discard() throws {
        for url in [pending, processing] where files.fileExists(atPath: url.path) {
            let request = try PropertyListDecoder().decode(QueryRequest.self, from: Data(contentsOf: url))
            let outcome = QueryResult(protocolVersion: request.protocolVersion, id: request.id, build: request.build,
                                      success: false, message: "Request discarded. Check current files before retrying.")
            try PropertyListEncoder().encode(outcome).write(to: result, options: .atomic)
            try files.removeItem(at: url)
        }
    }

    static func exportCurrent() throws -> URL {
        try withAccess {
            let data = try Data(contentsOf: target)
            try validatePlist(data)
            let url = documents.appendingPathComponent("com.apple.MobileGestalt.plist")
            try data.write(to: url, options: .atomic)
            return url
        }
    }
}
