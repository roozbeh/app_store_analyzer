import SwiftUI

struct ResearchDetailView: View {
    @StateObject private var apiService = APIService()
    @EnvironmentObject private var authService: AuthService
    @State private var current: Research
    @State private var isRetrying = false
    @State private var retryError: String?

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
        .toolbar {
            if current.status == .completed,
               let url = URL(string: "https://asa.ipronto.net/research/\(current.id)") {
                ToolbarItem(placement: .navigationBarTrailing) {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
            }
        }
        .task {
            // Always fetch the full detail (list endpoint omits apps and may omit other heavy fields)
            if let full = try? await apiService.fetchResearch(id: current.id) {
                current = full
            }
            if !current.status.isTerminal {
                await pollUntilDone()
            }
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

            if !current.status.isTerminal {
                VStack(alignment: .leading, spacing: 8) {
                    ProgressView()
                        .progressViewStyle(.linear)
                        .tint(.blue)
                    if let msg = current.progressMessage {
                        HStack(spacing: 6) {
                            ProgressView().scaleEffect(0.7).tint(.blue)
                            Text(msg)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            if current.status == .failed {
                if let err = current.error {
                    Label(err, systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline)
                        .foregroundStyle(.red)
                }
                if let token = authService.token {
                    Button {
                        Task { await retryResearch(token: token) }
                    } label: {
                        HStack(spacing: 6) {
                            if isRetrying {
                                ProgressView().scaleEffect(0.75)
                            } else {
                                Image(systemName: "arrow.clockwise")
                            }
                            Text(isRetrying ? "Retrying…" : "Retry")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 8)
                        .background(Color.blue)
                        .clipShape(Capsule())
                    }
                    .disabled(isRetrying)

                    if let err = retryError {
                        Text(err).font(.caption).foregroundStyle(.red)
                    }
                }
            }

            Label("\(current.appsAnalyzed) apps analyzed", systemImage: "app.badge")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color(.systemBackground))
    }

    // MARK: Structured report sections

    /// Resolves an array: native field → valid JSON parse → truncated-JSON extraction.
    private func resolveArray(_ key: String, native: [String]?) -> [String] {
        // 1. Use native MongoDB field if populated
        if let n = native, !n.isEmpty { return n }

        guard let report = current.competitiveReport else { return [] }
        let trimmed = report.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{") else { return [] }

        // 2. Try standard JSON (works when JSON is complete)
        if let data = trimmed.data(using: .utf8),
           let obj = try? JSONSerialization.jsonObject(with: data),
           let dict = obj as? [String: Any],
           let arr = dict[key] as? [Any] {
            let items = arr.compactMap { $0 as? String }
            if !items.isEmpty { return items }
        }

        // 3. Partial extraction — handles truncated JSON (hit token limit)
        return extractStringsFromTruncatedJSON(key: key, text: trimmed)
    }

    /// Extracts string items for a given key from JSON that may be cut off mid-stream.
    private func extractStringsFromTruncatedJSON(key: String, text: String) -> [String] {
        // Find  "key": [
        guard let keyRange = text.range(of: "\"\(key)\"") else { return [] }
        var rest = String(text[keyRange.upperBound...])

        // Skip to opening bracket
        guard let bracket = rest.firstIndex(of: "[") else { return [] }
        rest = String(rest[rest.index(after: bracket)...])

        var items: [String] = []

        while true {
            rest = rest.trimmingCharacters(in: .whitespacesAndNewlines)
            if rest.isEmpty || rest.hasPrefix("]") || rest.hasPrefix("}") { break }
            if rest.hasPrefix(",") { rest = String(rest.dropFirst()); continue }
            guard rest.hasPrefix("\"") else { break }
            rest = String(rest.dropFirst()) // consume opening quote

            var item = ""
            var escaped = false
            var closed = false
            var idx = rest.startIndex
            while idx < rest.endIndex {
                let c = rest[idx]
                idx = rest.index(after: idx)
                if escaped {
                    switch c {
                    case "\"": item += "\""; case "\\": item += "\\"
                    case "n":  item += "\n"; case "t":  item += "\t"
                    default:   item += String(c)
                    }
                    escaped = false
                } else if c == "\\" {
                    escaped = true
                } else if c == "\"" {
                    closed = true; break
                } else {
                    item += String(c)
                }
            }
            rest = String(rest[idx...])
            if !item.isEmpty { items.append(item) }
            if !closed { break } // truncated mid-string — stop here
        }
        return items
    }

    @ViewBuilder
    private var structuredSections: some View {
        let features      = resolveArray("top_valued_features",           native: current.topValuedFeatures)
        let painPoints    = resolveArray("common_pain_points",            native: current.commonPainPoints)
        let opportunities = resolveArray("differentiation_opportunities", native: current.differentiationOpportunities)
        let quickWins     = resolveArray("quick_wins",                    native: current.quickWins)

        if !features.isEmpty {
            insightCard(title: "Top Valued Features",           icon: "star.fill",                  color: .yellow, items: features)
            insightCard(title: "Common Pain Points",            icon: "exclamationmark.bubble.fill", color: .red,    items: painPoints)
            insightCard(title: "Differentiation Opportunities", icon: "lightbulb.fill",              color: .blue,   items: opportunities)
            insightCard(title: "Quick Wins",                    icon: "bolt.fill",                  color: .green,  items: quickWins)
        } else if current.status == .completed {
            // Structured data unavailable (legacy or truncated record) — prompt to re-run
            HStack(spacing: 14) {
                Image(systemName: "arrow.clockwise.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Insights not available")
                        .font(.subheadline.weight(.semibold))
                    Text("This research was created before structured insights were supported. Delete it and run a new search to see the full breakdown.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .padding(.horizontal)
        }
    }

    private func insightCard(title: String, icon: String, color: Color, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(color)
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(color)
                Spacer()
                Text("\(items.count)")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(color)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(color.opacity(0.15))
                    .clipShape(Capsule())
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(color.opacity(0.10))

            // Items
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                    HStack(alignment: .top, spacing: 12) {
                        Text("\(index + 1)")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(color)
                            .frame(width: 18, height: 18)
                            .background(color.opacity(0.12))
                            .clipShape(Circle())
                            .padding(.top, 1)
                        Text(item)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)

                    if index < items.count - 1 {
                        Divider().padding(.leading, 46)
                    }
                }
            }
            .background(Color(.secondarySystemBackground))
        }
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

    // MARK: Retry

    private func retryResearch(token: String) async {
        isRetrying = true
        retryError = nil
        do {
            try await apiService.retryResearch(id: current.id, token: token)
            // Reset local state and start polling
            if let fresh = try? await apiService.fetchResearch(id: current.id) {
                current = fresh
            }
            await pollUntilDone()
        } catch {
            retryError = error.localizedDescription
        }
        isRetrying = false
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
