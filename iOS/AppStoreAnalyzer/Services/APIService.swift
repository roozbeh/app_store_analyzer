import Foundation

// MARK: - Errors

enum APIError: Error, LocalizedError {
    case invalidURL
    case invalidResponse
    case serverError(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid backend URL. Check Settings."
        case .invalidResponse:
            return "Invalid response from server."
        case .serverError(let code, let body):
            return "Server error \(code): \(body)"
        }
    }
}

// MARK: - APIService

@MainActor
class APIService: ObservableObject {

    private var baseURL: String { Config.backendURL }

    // MARK: Generic request

    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        body: [String: Any]? = nil,
        token: String? = nil
    ) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
        }

        var req = URLRequest(url: url, timeoutInterval: 30)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: req)

        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(http.statusCode, message)
        }

        return try JSONDecoder().decode(T.self, from: data)
    }

    // MARK: Public API

    func fetchResearches() async throws -> [Research] {
        try await request("/api/researches")
    }

    func fetchResearch(id: String) async throws -> Research {
        try await request("/api/researches/\(id)")
    }

    func signInWithApple(identityToken: String) async throws -> AuthResponse {
        try await request(
            "/api/auth/apple",
            method: "POST",
            body: ["identity_token": identityToken]
        )
    }

    func deleteAccount(token: String) async throws {
        struct MessageResponse: Decodable { let message: String }
        let _: MessageResponse = try await request("/api/account", method: "DELETE", token: token)
    }

    func createResearch(
        keyword: String,
        token: String,
        limit: Int = 10,
        pages: Int = 3,
        country: String = "us"
    ) async throws -> CreateResearchResponse {
        try await request(
            "/api/researches",
            method: "POST",
            body: [
                "keyword": keyword,
                "limit": limit,
                "pages": pages,
                "country": country,
            ],
            token: token
        )
    }
}
