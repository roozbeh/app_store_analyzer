import SwiftUI

struct ResearchDetailView: View {
    @StateObject private var apiService = APIService()
    @State private var current: Research

    init(research: Research) {
        _current = State(initialValue: research)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                structuredSections
                if let apps = current.apps, !apps.isEmpty {
                    appsSection(apps)
                }
            }
            .padding(.vertical)
        }
        .navigationTitle(current.keyword)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            guard !current.status.isTerminal else { return }
            await pollUntilDone()
        }
    }

    // MARK: Header

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(current.keyword)
                    .font(.title2.bold())
                Spacer()
                StatusBadge(status: current.status)
            }

            if !current.status.isTerminal, let msg = current.progressMessage {
                HStack(spacing: 8) {
                    ProgressView().scaleEffect(0.8)
                    Text(msg)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if current.status == .failed, let err = current.error {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline)
                    .foregroundStyle(.red)
            }

            Label("\(current.appsAnalyzed) apps analyzed", systemImage: "app.badge")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color(.systemBackground))
    }

    // MARK: Structured report sections

    @ViewBuilder
    private var structuredSections: some View {
        let hasStructured = !(current.topValuedFeatures ?? []).isEmpty

        if hasStructured {
            // New structured view — one card per section
            insightCard(
                title: "Top Valued Features",
                icon: "star.fill",
                color: .yellow,
                items: current.topValuedFeatures ?? []
            )
            insightCard(
                title: "Common Pain Points",
                icon: "exclamationmark.bubble.fill",
                color: .red,
                items: current.commonPainPoints ?? []
            )
            insightCard(
                title: "Differentiation Opportunities",
                icon: "lightbulb.fill",
                color: .blue,
                items: current.differentiationOpportunities ?? []
            )
            insightCard(
                title: "Quick Wins",
                icon: "bolt.fill",
                color: .green,
                items: current.quickWins ?? []
            )
        } else if let report = current.competitiveReport, !report.isEmpty {
            // Fallback for older researches that only have the markdown report
            VStack(alignment: .leading, spacing: 8) {
                Text("Competitive Report")
                    .font(.headline)
                    .padding(.horizontal)
                MarkdownContentView(markdown: report)
                    .padding()
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .padding(.horizontal)
            }
        }
    }

    private func insightCard(title: String, icon: String, color: Color, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: icon)
                .font(.headline)
                .foregroundStyle(color)

            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: icon)
                        .font(.caption)
                        .foregroundStyle(color)
                        .frame(width: 14)
                        .padding(.top, 2)
                    Text(item)
                        .font(.subheadline)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal)
    }

    // MARK: Apps list

    private func appsSection(_ apps: [AppAnalysisModel]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("App Analyses")
                .font(.headline)
                .padding(.horizontal)

            ForEach(apps) { app in
                AppAnalysisCard(app: app)
                    .padding(.horizontal)
            }
        }
    }

    // MARK: Polling

    private func pollUntilDone() async {
        while !current.status.isTerminal {
            try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 s
            guard !Task.isCancelled else { return }
            do {
                let updated = try await apiService.fetchResearch(id: current.id)
                current = updated
            } catch {
                return // network error — stop polling silently
            }
        }
    }
}

// MARK: - AppAnalysisCard

struct AppAnalysisCard: View {
    let app: AppAnalysisModel
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // App header row
            HStack(spacing: 12) {
                AsyncImage(url: URL(string: app.iconUrl)) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(.systemGray5))
                }
                .frame(width: 52, height: 52)
                .clipShape(RoundedRectangle(cornerRadius: 12))

                VStack(alignment: .leading, spacing: 2) {
                    Text(app.name)
                        .font(.subheadline.bold())
                        .lineLimit(1)
                    Text(app.developer)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    HStack(spacing: 3) {
                        Image(systemName: "star.fill").foregroundStyle(.yellow)
                        Text(String(format: "%.1f", app.rating))
                        Text("(\(app.ratingCount.compactFormatted))")
                            .foregroundStyle(.secondary)
                    }
                    .font(.caption)
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 6) {
                    Text(app.price)
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.blue.opacity(0.1))
                        .foregroundStyle(.blue)
                        .clipShape(Capsule())

                    if let url = URL(string: app.url), !app.url.isEmpty {
                        Link(destination: url) {
                            Label("App Store", systemImage: "arrow.up.right.square")
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.blue)
                        }
                    }
                }
            }

            // Expandable detail
            if isExpanded {
                Divider()

                if !app.praisedFeatures.isEmpty {
                    featureList(
                        title: "Users Love",
                        icon: "heart.fill",
                        color: .green,
                        items: app.praisedFeatures
                    )
                }

                if !app.missingFeatures.isEmpty {
                    featureList(
                        title: "Users Want",
                        icon: "exclamationmark.bubble.fill",
                        color: .orange,
                        items: app.missingFeatures
                    )
                }

                marketEstimates

                if !app.sentimentSummary.isEmpty {
                    Text(app.sentimentSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .italic()
                }
            }

            Button {
                withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Text(isExpanded ? "Show less" : "Show more")
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                }
                .font(.caption)
                .foregroundStyle(.blue)
            }
        }
        .padding()
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func featureList(title: String, icon: String, color: Color, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: icon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(color)
            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 6) {
                    Text("•").foregroundStyle(color)
                    Text(item)
                }
                .font(.caption)
            }
        }
    }

    private var marketEstimates: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("Market Estimates", systemImage: "chart.bar.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.purple)
            HStack {
                Text("Downloads:").foregroundStyle(.secondary)
                Text(app.estimatedDownloads.compactFormatted).fontWeight(.medium)
            }
            .font(.caption)
            HStack {
                Text("MAU:").foregroundStyle(.secondary)
                Text(app.estimatedMau.compactFormatted).fontWeight(.medium)
            }
            .font(.caption)
            HStack {
                Text("Annual Revenue (mid):").foregroundStyle(.secondary)
                Text(app.revenueMid.usdFormatted).fontWeight(.medium)
            }
            .font(.caption)
        }
    }
}
