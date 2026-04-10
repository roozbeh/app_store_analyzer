import SwiftUI

struct UserProfileView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) var dismiss
    @StateObject private var apiService = APIService()

    let allResearches: [Research]

    @State private var showDeleteConfirmation = false
    @State private var isDeleting = false
    @State private var deleteError: String?

    private var myResearches: [Research] {
        guard let userId = authService.userId else { return [] }
        return allResearches.filter { $0.userId == userId }
    }

    var body: some View {
        NavigationStack {
            List {
                if authService.isSignedIn {
                    // My past researches
                    Section("My Researches") {
                        if myResearches.isEmpty {
                            Text("You haven't run any researches yet.")
                                .foregroundStyle(.secondary)
                                .font(.subheadline)
                        } else {
                            ForEach(myResearches) { research in
                                NavigationLink(destination: ResearchDetailView(research: research)) {
                                    ResearchRowView(research: research)
                                }
                            }
                        }
                    }

                    // Account actions
                    Section {
                        Button("Sign Out") {
                            authService.signOut()
                            dismiss()
                        }
                        .foregroundStyle(.red)

                        Button("Delete My Account", role: .destructive) {
                            showDeleteConfirmation = true
                        }
                    }

                    if let error = deleteError {
                        Section {
                            Text(error)
                                .foregroundStyle(.red)
                                .font(.caption)
                        }
                    }
                } else {
                    Section {
                        VStack(spacing: 12) {
                            Image(systemName: "person.slash")
                                .font(.system(size: 40))
                                .foregroundStyle(.secondary)
                            Text("Not signed in")
                                .font(.headline)
                            Text("Sign in to see your past researches.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 24)
                    }
                }
            }
            .navigationTitle("My Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .confirmationDialog(
                "Delete Account",
                isPresented: $showDeleteConfirmation,
                titleVisibility: .visible
            ) {
                Button("Delete All My Data", role: .destructive) {
                    Task { await deleteAccount() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This will permanently delete all your market researches. This cannot be undone.")
            }
            .overlay {
                if isDeleting {
                    ZStack {
                        Color.black.opacity(0.3).ignoresSafeArea()
                        VStack(spacing: 12) {
                            ProgressView()
                            Text("Deleting…")
                                .font(.subheadline)
                        }
                        .padding(24)
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                    }
                }
            }
        }
    }

    private func deleteAccount() async {
        guard let token = authService.token else { return }
        isDeleting = true
        deleteError = nil
        do {
            try await apiService.deleteAccount(token: token)
            authService.signOut()
            dismiss()
        } catch {
            deleteError = error.localizedDescription
        }
        isDeleting = false
    }
}
