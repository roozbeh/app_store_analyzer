import Foundation
import AuthenticationServices

@MainActor
class AuthService: NSObject, ObservableObject {

    @Published var isSignedIn = false
    @Published var token: String?
    @Published var userId: String?
    @Published var isLoading = false
    @Published var error: String?

    private let apiService = APIService()
    private let tokenKey  = "auth_token"
    private let userIdKey = "user_id"

    override init() {
        super.init()
        // Restore session from UserDefaults (use Keychain in production for higher security)
        if let saved = UserDefaults.standard.string(forKey: tokenKey),
           let uid   = UserDefaults.standard.string(forKey: userIdKey) {
            token      = saved
            userId     = uid
            isSignedIn = true
        }
    }

    // MARK: Sign In with Apple

    func handleAppleSignIn(result: Result<ASAuthorization, Error>) async {
        isLoading = true
        error = nil
        defer { isLoading = false }

        switch result {
        case .failure(let err):
            // ASAuthorizationError.canceled is not a real error — ignore it
            let asErr = err as? ASAuthorizationError
            if asErr?.code != .canceled {
                error = err.localizedDescription
            }

        case .success(let auth):
            guard
                let credential  = auth.credential as? ASAuthorizationAppleIDCredential,
                let tokenData   = credential.identityToken,
                let idToken     = String(data: tokenData, encoding: .utf8)
            else {
                error = "Failed to read identity token from Apple."
                return
            }

            do {
                let response = try await apiService.signInWithApple(identityToken: idToken)
                persist(token: response.token, userId: response.userId)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Sign Out

    func signOut() {
        token      = nil
        userId     = nil
        isSignedIn = false
        UserDefaults.standard.removeObject(forKey: tokenKey)
        UserDefaults.standard.removeObject(forKey: userIdKey)
    }

    // MARK: Private

    private func persist(token: String, userId: String) {
        self.token      = token
        self.userId     = userId
        self.isSignedIn = true
        UserDefaults.standard.set(token,  forKey: tokenKey)
        UserDefaults.standard.set(userId, forKey: userIdKey)
    }
}
