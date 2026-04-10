import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @State private var backendURL = UserDefaults.standard.string(forKey: "backend_url") ?? ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://localhost:5000", text: $backendURL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                } header: {
                    Text("Backend URL")
                } footer: {
                    Text("URL of your Flask backend server. Leave empty to use the default (http://localhost:5000). Example for production: https://api.yourdomain.com")
                }

                Section {
                    Button("Reset to Default") {
                        backendURL = ""
                    }
                    .foregroundStyle(.red)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        UserDefaults.standard.set(backendURL, forKey: "backend_url")
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
            }
        }
    }
}
