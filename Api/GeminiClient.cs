using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using InterviewAssistant.Configuration;
using InterviewAssistant.Models;

namespace InterviewAssistant.Api;

public sealed class GeminiClient
{
    private readonly HttpClient _httpClient = new() { Timeout = TimeSpan.FromSeconds(60) };

    public async Task<string> SendAsync(
        AppSettings settings,
        IReadOnlyList<ChatMessage> history,
        CancellationToken cancellationToken)
    {
        string apiKey = settings.GeminiApiKey.Trim();
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            apiKey = Environment.GetEnvironmentVariable("GEMINI_API_KEY")?.Trim() ?? "";
        }

        if (string.IsNullOrWhiteSpace(apiKey))
        {
            throw new InvalidOperationException("Gemini API Key is not set. Please set it in the settings.");
        }

        string targetModel = settings.GeminiVisionModel;
        if (string.IsNullOrWhiteSpace(targetModel))
        {
            targetModel = "gemini-2.5-flash";
        }

        string url = $"https://generativelanguage.googleapis.com/v1beta/models/{targetModel}:generateContent?key={apiKey}";

        var contents = new List<object>();

        for (int i = 0; i < history.Count; i++)
        {
            var message = history[i];
            bool isLastMessage = i == history.Count - 1;
            var parts = new List<object>();

            if (isLastMessage && !string.IsNullOrEmpty(message.ImageDataUrl))
            {
                if (!string.IsNullOrWhiteSpace(message.Content))
                {
                    parts.Add(new { text = message.Content });
                }
                
                string dataUri = message.ImageDataUrl;
                string mime = dataUri.Split(';')[0].Split(':')[1];
                string b64 = dataUri.Split(',')[1];

                parts.Add(new
                {
                    inline_data = new
                    {
                        mime_type = mime,
                        data = b64
                    }
                });
            }
            else
            {
                parts.Add(new { text = message.Content });
            }

            string role = message.Role == "assistant" ? "model" : "user";
            contents.Add(new { role = role, parts = parts });
        }

        var payload = new
        {
            system_instruction = new { parts = new[] { new { text = Prompts.System } } },
            contents = contents,
            // NOTE: the REST API reads "generationConfig" - a "config" object (the
            // Python SDK's name) is not recognised here. thinkingBudget -1 lets the
            // model think as long as the question needs; 0 disables reasoning and
            // wrecks logical-reasoning / aptitude accuracy.
            generationConfig = new
            {
                temperature = 0.0,
                topP = 1.0,
                maxOutputTokens = 8192,
                thinkingConfig = new
                {
                    thinkingBudget = -1
                }
            }
        };

        using var request = new HttpRequestMessage(HttpMethod.Post, url);
        request.Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

        using HttpResponseMessage response = await _httpClient.SendAsync(request, cancellationToken);
        string body = await response.Content.ReadAsStringAsync(cancellationToken);
        
        if (!response.IsSuccessStatusCode)
        {
            string detail = body.Length > 400 ? body[..400] : body;
            throw new InvalidOperationException($"The Gemini API returned {(int)response.StatusCode}: {detail}");
        }

        using JsonDocument document = JsonDocument.Parse(body);
        
        try
        {
            // With thinking enabled the answer is not always parts[0]: the model can
            // emit thought parts first. Concatenate every non-thought text part.
            JsonElement candidate = document.RootElement.GetProperty("candidates")[0];
            bool truncated = candidate.TryGetProperty("finishReason", out JsonElement finishReason) &&
                             finishReason.ValueEquals("MAX_TOKENS");

            var builder = new StringBuilder();
            foreach (JsonElement part in candidate
                         .GetProperty("content")
                         .GetProperty("parts")
                         .EnumerateArray())
            {
                if (part.TryGetProperty("thought", out JsonElement thought) &&
                    thought.ValueKind == JsonValueKind.True)
                {
                    continue;
                }

                if (part.TryGetProperty("text", out JsonElement text))
                {
                    builder.Append(text.GetString());
                }
            }

            string? rawContent = builder.ToString();

            if (string.IsNullOrWhiteSpace(rawContent))
            {
                return "The LLM returned an empty response.";
            }

            return ReplyCleaner.Clean(rawContent, truncated);
        }
        catch (Exception)
        {
            return "The LLM returned an unexpected response format.";
        }
    }
}
