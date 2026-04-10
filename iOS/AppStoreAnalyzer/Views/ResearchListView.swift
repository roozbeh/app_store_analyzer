import SwiftUI

struct ResearchListView: View {
    @EnvironmentObject var authService: AuthService
    @StateObject private var apiService = APIService()

    @State private var researches: [Research] = []
    @State private var isLoading = false
    @State private var loadError: String?
    @State private var showSheet = false
    @State private var showProfile = false

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && researches.isEmpty {
                    ProgressView("Loading…")
                } else if let error = loadError, researches.isEmpty {
                    errorView(error)
                } else if researches.isEmpty {
                    emptyView
                } else {
                    list
                }
            }
            .navigationTitle("Market Research")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button { showProfile = true } label: {
                        Image(systemName: "person.circle")
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { showSheet = true } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            // Sheet: show SignIn if not authenticated, otherwise show New Research form.
            // When isSignedIn flips to true, SwiftUI re-evaluates the if/else and shows
            // NewResearchView without dismissing the sheet.
            .sheet(isPresented: $showSheet, onDismiss: {
                Task { await loadResearches() }
            }) {
                NewResearchOrSignInView()
            }
            .sheet(isPresented: $showProfile, onDismiss: {
                Task { await loadResearches() }
            }) {
                UserProfileView(allResearches: researches)
            }
        }
        .task { await loadResearches() }
    }

    // MARK: Sub-views

    private var list: some View {
        List(researches) { research in
            NavigationLink(destination: ResearchDetailView(research: research)) {
                ResearchRowView(research: research)
            }
        }
        .refreshable { await loadResearches() }
    }

    private var emptyView: some View {
        VStack(spacing: 20) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 52))
                .foregroundStyle(.secondary)
            Text("No research yet")
                .font(.headline)
            Text("Tap + to start your first market research.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
    }

    private func errorView(_ message: String) -> some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 44))
                .foregroundStyle(.orange)
            Text(message)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Retry") { Task { await loadResearches() } }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    // MARK: Data

    private func loadResearches() async {
        isLoading = true
        loadError = nil
        do {
            researches = try await apiService.fetchResearches()
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }
}

// MARK: - Sheet wrapper

/// Switches between SignInView and NewResearchView without dismissing the sheet.
private struct NewResearchOrSignInView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        if authService.isSignedIn {
            NewResearchView()
        } else {
            SignInView()
        }
    }
}

// MARK: - Row

struct ResearchRowView: View {
    let research: Research

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(research.keyword)
                    .font(.headline)
                Spacer()
                StatusBadge(status: research.status)
            }

            HStack(spacing: 4) {
                Image(systemName: "app.badge")
                    .foregroundStyle(.secondary)
                Text("\(research.appsAnalyzed) apps")
                    .foregroundStyle(.secondary)
                Spacer()
                Text(research.formattedDate)
                    .foregroundStyle(.secondary)
            }
            .font(.caption)

            if (research.status == .running || research.status == .pending),
               let msg = research.progressMessage {
                Text(msg)
                    .font(.caption2)
                    .foregroundStyle(.blue)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Status Badge

struct StatusBadge: View {
    let status: ResearchStatus

    private var color: Color {
        switch status {
        case .pending:   return .orange
        case .running:   return .blue
        case .completed: return .green
        case .failed:    return .red
        }
    }

    var body: some View {
        Text(status.displayName)
            .font(.caption2)
            .fontWeight(.semibold)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}
