import Foundation

// MARK: - Enums

enum ResearchStatus: String, Codable {
    case pending
    case running
    case completed
    case failed

    var displayName: String {
        switch self {
        case .pending:   return "Pending"
        case .running:   return "Running"
        case .completed: return "Completed"
        case .failed:    return "Failed"
        }
    }

    var isTerminal: Bool {
        self == .completed || self == .failed
    }
}

// MARK: - Research (list + detail)

struct Research: Identifiable, Codable {
    let id: String
    let keyword: String
    let status: ResearchStatus
    let createdAt: String
    let completedAt: String?
    let appsAnalyzed: Int
    let competitiveReport: String?
    let apps: [AppAnalysisModel]?
    let progressMessage: String?
    let error: String?
    let userId: String?
    let topValuedFeatures: [String]?
    let commonPainPoints: [String]?
    let differentiationOpportunities: [String]?
    let quickWins: [String]?

    enum CodingKeys: String, CodingKey {
        case id
        case keyword
        case status
        case createdAt                    = "created_at"
        case completedAt                  = "completed_at"
        case appsAnalyzed                 = "apps_analyzed"
        case competitiveReport            = "competitive_report"
        case apps
        case progressMessage              = "progress_message"
        case error
        case userId                       = "user_id"
        case topValuedFeatures            = "top_valued_features"
        case commonPainPoints             = "common_pain_points"
        case differentiationOpportunities = "differentiation_opportunities"
        case quickWins                    = "quick_wins"
    }

    var formattedDate: String {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: createdAt) {
            let rel = RelativeDateTimeFormatter()
            rel.unitsStyle = .short
            return rel.localizedString(for: date, relativeTo: Date())
        }
        // Fallback: trim to date portion
        return String(createdAt.prefix(10))
    }
}

// MARK: - AppAnalysisModel

struct AppAnalysisModel: Identifiable, Codable {
    let appId: String
    let name: String
    let developer: String
    let rating: Double
    let ratingCount: Int
    let price: String
    let category: String
    let url: String
    let iconUrl: String
    let reviewsAnalyzed: Int
    let praisedFeatures: [String]
    let missingFeatures: [String]
    let sentimentSummary: String
    let competitiveNotes: String
    let estimatedDownloads: Int
    let estimatedMau: Int
    let revenueLow: Double
    let revenueMid: Double
    let revenueHigh: Double
    let monetizationNote: String

    var id: String { appId }

    enum CodingKeys: String, CodingKey {
        case appId              = "app_id"
        case name
        case developer
        case rating
        case ratingCount        = "rating_count"
        case price
        case category
        case url
        case iconUrl            = "icon_url"
        case reviewsAnalyzed    = "reviews_analyzed"
        case praisedFeatures    = "praised_features"
        case missingFeatures    = "missing_features"
        case sentimentSummary   = "sentiment_summary"
        case competitiveNotes   = "competitive_notes"
        case estimatedDownloads = "estimated_downloads"
        case estimatedMau       = "estimated_mau"
        case revenueLow         = "revenue_low"
        case revenueMid         = "revenue_mid"
        case revenueHigh        = "revenue_high"
        case monetizationNote   = "monetization_note"
    }
}

// MARK: - Auth / Research creation responses

struct AuthResponse: Codable {
    let token: String
    let userId: String

    enum CodingKeys: String, CodingKey {
        case token
        case userId = "user_id"
    }
}

struct CreateResearchResponse: Codable {
    let id: String
    let status: String
}

// MARK: - Formatting helpers

extension Int {
    var compactFormatted: String {
        let n = Double(self)
        if n >= 1_000_000 { return String(format: "%.1fM", n / 1_000_000) }
        if n >= 1_000     { return String(format: "%.0fK", n / 1_000) }
        return "\(self)"
    }
}

extension Double {
    var usdFormatted: String {
        if self >= 1_000_000_000 { return String(format: "$%.1fB", self / 1_000_000_000) }
        if self >= 1_000_000     { return String(format: "$%.1fM", self / 1_000_000) }
        if self >= 1_000         { return String(format: "$%.0fK", self / 1_000) }
        return String(format: "$%.0f", self)
    }
}
