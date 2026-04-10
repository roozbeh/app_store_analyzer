import Foundation

enum Config {
    /// The base URL of the Flask backend.
    /// Priority: UserDefaults override (set in Settings) → compile-time default.
    static var backendURL: String {
        if let custom = UserDefaults.standard.string(forKey: "backend_url"),
           !custom.trimmingCharacters(in: .whitespaces).isEmpty {
            return custom.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        // Default for local development. Change this before shipping.
        return "https://asa.ipronto.net"
    }

    /// Must match APPLE_BUNDLE_ID in the backend .env and the Xcode signing settings.
    static let appleBundleID = "com.ipronto.appstoreanalyzer"
}
