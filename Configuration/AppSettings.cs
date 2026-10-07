namespace InterviewAssistant.Configuration;

public sealed class AppSettings
{
    public string ApiEndpoint { get; set; } = "https://api.groq.com/openai/v1/chat/completions";
    public string GroqApiKey { get; set; } = "";
    public string GeminiApiKey { get; set; } = "";
    public string SelectedProvider { get; set; } = "Groq";
    public string Model { get; set; } = "openai/gpt-oss-120b";
    public string HotkeyKey { get; set; } = "Space";
    public bool HotkeyControl { get; set; } = true;
    public bool HotkeyAlt { get; set; } = true;
    public bool HotkeyShift { get; set; }
    public bool HotkeyWindows { get; set; }
    public double OverlayOpacity { get; set; } = 0.96;
    public double OverlayWidth { get; set; } = 520;
    public double OverlayHeight { get; set; } = 620;
    public double OverlayLeft { get; set; } = 80;
    public double OverlayTop { get; set; } = 80;
    public bool EnableCaptureProtection { get; set; } = true;
    // Groq retired qwen/qwen3.6-27b in favour of 3.8; it is the only Groq model
    // that accepts images.
    public string GroqVisionModel { get; set; } = "qwen/qwen3.8-27b";
    public string GeminiVisionModel { get; set; } = "gemini-2.5-flash";
    public bool AutoExtractUiaContext { get; set; } = true;

    public string HotkeyDisplay => string.Join("+", new[]
    {
        HotkeyControl ? "Ctrl" : null,
        HotkeyAlt ? "Alt" : null,
        HotkeyShift ? "Shift" : null,
        HotkeyWindows ? "Win" : null,
        HotkeyKey,
    }.Where(value => !string.IsNullOrWhiteSpace(value)));
}

