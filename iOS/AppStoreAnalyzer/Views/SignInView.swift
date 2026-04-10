import SwiftUI
import AuthenticationServices

struct SignInView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) var dismiss
    @Environment(\.colorScheme) var colorScheme

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Spacer()

                // Icon + title
                VStack(spacing: 16) {
                    Image(systemName: "chart.bar.doc.horizontal")
                        .font(.system(size: 64))
                        .foregroundStyle(.blue)

                    Text("App Store Analyzer")
                        .font(.largeTitle)
                        .fontWeight(.bold)

                    Text("Sign in to run market research\nand save your results.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding(.horizontal, 32)

                Spacer()

                // Sign-in controls
                VStack(spacing: 16) {
                    if authService.isLoading {
                        ProgressView("Signing in…")
                            .frame(height: 50)
                    } else {
                        SignInWithAppleButton(.signIn) { request in
                            request.requestedScopes = [.email, .fullName]
                        } onCompletion: { result in
                            Task {
                                await authService.handleAppleSignIn(result: result)
                                // Do NOT dismiss here — NewResearchOrSignInView will
                                // automatically switch to NewResearchView when isSignedIn flips.
                            }
                        }
                        .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
                        .frame(height: 50)
                        .padding(.horizontal, 32)
                    }

                    if let error = authService.error {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }

                    Button("Maybe later") { dismiss() }
                        .foregroundStyle(.secondary)
                }
                .padding(.bottom, 48)
            }
            .navigationTitle("Sign In")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}
