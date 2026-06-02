import SwiftUI

/// Shown inside a sheet when the user is already signed in.
/// When not signed in, ResearchListView shows SignInView instead.
struct NewResearchView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) var dismiss
    @StateObject private var apiService = APIService()

    @State private var keyword = ""
    @State private var limit = 10
    @State private var pages = 3
    @State private var country = "us"
    @State private var isSubmitting = false
    @State private var error: String?

    private let countries = ["us", "gb", "ca", "au", "de", "fr", "jp", "cn"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("e.g. habit tracker, todo list", text: $keyword)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .submitLabel(.done)
                        .onSubmit { if canSubmit { startResearch() } }
                } header: {
                    Text("Keyword")
                } footer: {
                    Text("One keyword or short phrase to search the App Store.")
                }

                Section("Options") {
                    Stepper("Apps per keyword: \(limit)", value: $limit, in: 5...15)
                    Stepper("Review pages: \(pages)", value: $pages, in: 1...10)
                    Picker("Country", selection: $country) {
                        ForEach(countries, id: \.self) { c in
                            Text(c.uppercased()).tag(c)
                        }
                    }
                }

                if let error {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                            .font(.subheadline)
                    }
                }

                Section {
                    Button(action: startResearch) {
                        HStack {
                            Spacer()
                            if isSubmitting {
                                ProgressView()
                                    .padding(.trailing, 6)
                            }
                            Text(isSubmitting ? "Starting…" : "Start Research")
                                .fontWeight(.semibold)
                            Spacer()
                        }
                    }
                    .disabled(!canSubmit)
                }

                Section {
                    Button("Sign Out", role: .destructive) {
                        authService.signOut()
                        dismiss()
                    }
                }
            }
            .navigationTitle("New Research")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private var canSubmit: Bool {
        !keyword.trimmingCharacters(in: .whitespaces).isEmpty && !isSubmitting
    }

    private func startResearch() {
        guard let token = authService.token else { return }
        isSubmitting = true
        error = nil

        Task {
            do {
                _ = try await apiService.createResearch(
                    keyword: keyword.trimmingCharacters(in: .whitespaces),
                    token: token,
                    limit: limit,
                    pages: pages,
                    country: country
                )
                dismiss()
            } catch let apiErr as APIError {
                if case .serverError(401, _) = apiErr {
                    authService.signOut()
                    dismiss()
                } else {
                    self.error = apiErr.localizedDescription
                    isSubmitting = false
                }
            } catch {
                self.error = error.localizedDescription
                isSubmitting = false
            }
        }
    }
}
