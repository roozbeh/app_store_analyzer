import SwiftUI

/// Renders the Markdown that Claude produces in competitive reports.
/// Handles: # headings, ## headings, --- dividers, - bullet points,
/// **bold** / *italic* inline (via AttributedString), and plain paragraphs.
struct MarkdownContentView: View {
    let markdown: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                blockView(for: block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Block model

    private enum Block {
        case h1(String)
        case h2(String)
        case h3(String)
        case divider
        case bullet(String)
        case paragraph(String)
    }

    // MARK: - Parser

    private var blocks: [Block] {
        markdown
            .components(separatedBy: "\n")
            .compactMap { line -> Block? in
                let t = line.trimmingCharacters(in: .whitespaces)
                if t.hasPrefix("### ")      { return .h3(String(t.dropFirst(4))) }
                if t.hasPrefix("## ")       { return .h2(String(t.dropFirst(3))) }
                if t.hasPrefix("# ")        { return .h1(String(t.dropFirst(2))) }
                if t == "---" || t == "***" { return .divider }
                if t.hasPrefix("- ") || t.hasPrefix("* ") {
                    return .bullet(String(t.dropFirst(2)))
                }
                if t.isEmpty { return nil }
                return .paragraph(t)
            }
    }

    // MARK: - Block renderers

    @ViewBuilder
    private func blockView(for block: Block) -> some View {
        switch block {

        case .h1(let text):
            Text(inline(text))
                .font(.title2.bold())
                .padding(.top, 6)

        case .h2(let text):
            Text(inline(text))
                .font(.headline)
                .padding(.top, 4)

        case .h3(let text):
            Text(inline(text))
                .font(.subheadline.bold())
                .padding(.top, 2)

        case .divider:
            Divider()
                .padding(.vertical, 2)

        case .bullet(let text):
            HStack(alignment: .top, spacing: 8) {
                Text("•")
                    .foregroundStyle(.secondary)
                    .frame(width: 10, alignment: .leading)
                Text(inline(text))
                    .fixedSize(horizontal: false, vertical: true)
            }

        case .paragraph(let text):
            Text(inline(text))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - Inline markdown (bold, italic via AttributedString)

    private func inline(_ text: String) -> AttributedString {
        let opts = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
        return (try? AttributedString(markdown: text, options: opts)) ?? AttributedString(text)
    }
}
