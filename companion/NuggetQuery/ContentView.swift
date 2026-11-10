import SwiftUI

struct ContentView: View {
    @State private var request: QueryRequest?
    @State private var message = "Experimental support for iOS 27.0–27.2. Keep this app open while applying from Nugget."
    @State private var exported: URL?

    var body: some View {
        NavigationStack {
            Form {
                Section("MobileGestalt") {
                    Text("First export your current MobileGestalt, transfer it to your computer and select it in Nugget. Then click Apply in Nugget and load the request here.")
                    Button("Export current MobileGestalt") {
                        run { exported = try QueryBridge.exportCurrent(); message = "Export ready to share." }
                    }
                    if let exported { ShareLink("Share MobileGestalt", item: exported) }
                }
                Section("Pending request") {
                    Button("Load pending request") {
                        request = nil
                        run { request = try QueryBridge.load(); message = "Review the operation, then tap Apply." }
                    }
                    if let request {
                        LabeledContent("Operation", value: request.operation)
                        LabeledContent("Files", value: String(request.entries.count))
                        ForEach(Array(request.entries.enumerated()), id: \.offset) { _, entry in
                            Text("\(entry.operation): \(entry.domain)/\(entry.path)").font(.caption)
                        }
                        LabeledContent("System build", value: request.build)
                        Text(request.id).font(.caption).textSelection(.enabled)
                        Button("Apply to this device") {
                            run { message = try QueryBridge.apply(request) }
                            self.request = nil
                        }
                    }
                    Button("Discard pending / interrupted request", role: .destructive) {
                        run { try QueryBridge.discard(); message = "Request discarded." }
                        request = nil
                    }
                }
                Section("Status") { Text(message).textSelection(.enabled) }
                Section("Original backup") {
                    Text("Before writing, all targets are checked and their originals are saved in Documents for this OS build. Keep this app and its backups. Reset MobileGestalt in Nugget restores its original. Other container backups are retained for recovery; a crash can interrupt writes or rollback.")
                }
            }
            .navigationTitle("NuggetQuery")
        }
    }

    private func run(_ action: () throws -> Void) {
        do { try action() }
        catch { message = error.localizedDescription }
    }
}
