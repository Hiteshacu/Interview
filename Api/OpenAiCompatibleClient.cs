using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using InterviewAssistant.Configuration;
using InterviewAssistant.Models;

namespace InterviewAssistant.Api;

public sealed class OpenAiCompatibleClient
{
    private readonly HttpClient _httpClient = new() { Timeout = TimeSpan.FromSeconds(60) };

    public async Task<string> SendAsync(
        AppSettings settings,
        IReadOnlyList<ChatMessage> history,
        CancellationToken cancellationToken)
    {
        string apiKey = settings.GroqApiKey.Trim();
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            apiKey = Environment.GetEnvironmentVariable("GROQ_API_KEY")?.Trim() ?? "";
        }

        if (string.IsNullOrWhiteSpace(apiKey))
        {
            throw new InvalidOperationException("Groq API Key is not set. Please set it in the settings.");
        }

        if (!Uri.TryCreate(settings.ApiEndpoint, UriKind.Absolute, out Uri? endpoint))
        {
            throw new InvalidOperationException("The API endpoint must be an absolute URL.");
        }

        bool hasImages = history.Any(m => !string.IsNullOrEmpty(m.ImageDataUrl));
        string targetModel = hasImages && !string.IsNullOrWhiteSpace(settings.GroqVisionModel)
            ? settings.GroqVisionModel
            : settings.Model;

        var messages = new List<object> { new { role = "system", content = Prompts.System } };
        
        for (int i = 0; i < history.Count; i++)
        {
            var message = history[i];
            bool isLastMessage = i == history.Count - 1;

            if (isLastMessage && !string.IsNullOrEmpty(message.ImageDataUrl))
            {
                var contentParts = new List<object>();
                if (!string.IsNullOrWhiteSpace(message.Content))
                {
                    contentParts.Add(new { type = "text", text = message.Content });
                }
                contentParts.Add(new { type = "image_url", image_url = new { url = message.ImageDataUrl } });

                messages.Add(new { role = message.Role, content = contentParts });
            }
            else
            {
                messages.Add(new { role = message.Role, content = message.Content });
            }
        }

        // temperature 0: these questions have one correct answer, so sampling noise
        // is pure downside.
        //
        // max_tokens is squeezed between two hard limits. Too low and a reasoning
        // model is cut off mid-derivation and never emits its answer at all - Groq's
        // own default of 2048 does exactly that, which is the single biggest cause of
        // blank or scratch-work replies. Too high and the request is rejected: Groq
        // reserves prompt + max_tokens against the tokens-per-minute limit (8000 on
        // the free tier), so 8192 fails with a 413 before the model even runs.
        var payload = new
        {
            model = targetModel,
            messages,
            stream = false,
            temperature = 0.0,
            top_p = 1.0,
            max_tokens = 4096,
        };

        using var request = new HttpRequestMessage(HttpMethod.Post, endpoint);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        request.Headers.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36");
        request.Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

        using HttpResponseMessage response = await _httpClient.SendAsync(request, cancellationToken);
        string body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            string detail = body.Length > 400 ? body[..400] : body;
            throw new InvalidOperationException($"The LLM API returned {(int)response.StatusCode}: {detail}");
        }

        using JsonDocument document = JsonDocument.Parse(body);
        JsonElement choice = document.RootElement.GetProperty("choices")[0];
        JsonElement responseMessage = choice.GetProperty("message");

        bool truncated = choice.TryGetProperty("finish_reason", out JsonElement finishReason) &&
                         finishReason.ValueEquals("length");

        string? rawContent = responseMessage.TryGetProperty("content", out JsonElement contentElement)
            ? contentElement.GetString()
            : null;

        // Some reasoning models put everything in a separate "reasoning" field and
        // leave content empty.
        if (string.IsNullOrWhiteSpace(rawContent) &&
            responseMessage.TryGetProperty("reasoning", out JsonElement reasoningElement))
        {
            rawContent = reasoningElement.GetString();
        }

        if (string.IsNullOrWhiteSpace(rawContent))
        {
            return "The LLM returned an empty response.";
        }

        return ReplyCleaner.Clean(rawContent, truncated);
    }
}
