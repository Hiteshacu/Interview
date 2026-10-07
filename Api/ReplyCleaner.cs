using System.Text.RegularExpressions;

namespace InterviewAssistant.Api;

/// <summary>
/// Turns a raw model reply into what the overlay shows: scratch work removed, and
/// the answer lifted to the top.
/// </summary>
public static class ReplyCleaner
{
    private static readonly Regex ThinkBlock =
        new(@"<think>.*?</think>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex StrayThinkTag =
        new(@"</?think>", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex AnswerLine =
        new(@"^[ \t]*(?:\*\*)?answer\s*[:\-].*$",
            RegexOptions.IgnoreCase | RegexOptions.Multiline | RegexOptions.Compiled);

    /// <summary>
    /// Prepended when the model was cut off mid-answer. It goes at the top because a
    /// truncated reasoning model dumps its scratch work, and a warning buried under
    /// that is a warning nobody reads.
    /// </summary>
    public const string TruncatedNote =
        "[Cut off at the token limit - this reply is incomplete. Ask again, or switch to a model with more room.]";

    /// <summary>Cleans a reply and flags it when the provider reported truncation.</summary>
    public static string Clean(string? raw, bool truncated)
    {
        string reply = Clean(raw);
        if (!truncated)
        {
            return reply;
        }

        return reply.Length == 0
            ? TruncatedNote
            : $"{TruncatedNote}{Environment.NewLine}{Environment.NewLine}{reply}";
    }

    public static string Clean(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return "";
        }

        string cleaned = ThinkBlock.Replace(raw, "");

        // An opening tag with no closing tag means the model ran its working
        // straight into the answer; fall back to the "Answer:" line rather than
        // dumping a page of derivation into the overlay.
        if (cleaned.Contains("<think>", StringComparison.OrdinalIgnoreCase))
        {
            Match unterminated = AnswerLine.Match(cleaned);
            if (unterminated.Success)
            {
                cleaned = cleaned[unterminated.Index..];
            }
        }

        cleaned = StrayThinkTag.Replace(cleaned, "").Trim();
        return cleaned.Length == 0 ? raw.Trim() : AnswerFirst(cleaned);
    }

    /// <summary>
    /// Moves a single "Answer: ..." line to the top, keeping the working below.
    /// The model is told to derive before it answers, because answering first and
    /// justifying afterwards is what makes it fail aptitude questions; this puts
    /// the result back where a reader needs it without costing that accuracy.
    /// Replies containing several answers are left in their original order.
    /// </summary>
    private static string AnswerFirst(string text)
    {
        MatchCollection matches = AnswerLine.Matches(text);
        if (matches.Count != 1)
        {
            return text;
        }

        Match match = matches[0];
        string answer = match.Value.Trim();
        string rest = (text[..match.Index] + text[(match.Index + match.Length)..]).Trim();

        return rest.Length == 0 ? answer : $"{answer}{Environment.NewLine}{Environment.NewLine}{rest}";
    }
}
