namespace InterviewAssistant.Models;

public sealed record ChatMessage(string Role, string Content, string? ImageDataUrl = null);
