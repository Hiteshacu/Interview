using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using InterviewAssistant.Api;
using InterviewAssistant.Configuration;
using InterviewAssistant.Models;
using InterviewAssistant.Services;
using InterviewAssistant.Utilities;
using MediaColor = System.Windows.Media.Color;

namespace InterviewAssistant;

public partial class OverlayWindow : Window
{
    private readonly List<ChatMessage> _history = [];
    private AppSettings? _settings;
    private string _lastResponse = "";
    private string? _pendingImageDataUrl;
    private bool _isBusy;
    private bool _closeForShutdown;

    public OverlayWindow()
    {
        InitializeComponent();
        SourceInitialized += OverlayWindow_SourceInitialized;
        Loaded += OverlayWindow_Loaded;
    }

    private void OverlayWindow_SourceInitialized(object? sender, EventArgs eventArgs)
    {
        if (_settings != null)
        {
            ApplyProtection(_settings.EnableCaptureProtection);
        }
    }

    private void OverlayWindow_Loaded(object sender, RoutedEventArgs e)
    {
        if (_settings != null)
        {
            ApplyProtection(_settings.EnableCaptureProtection);
        }
    }


    public void ShowAssistant(AppSettings settings)
    {
        _settings = settings;
        Width = settings.OverlayWidth;
        Height = settings.OverlayHeight;
        Left = settings.OverlayLeft;
        Top = settings.OverlayTop;
        Topmost = true;

        if (settings.SelectedProvider.Equals("Gemini", StringComparison.OrdinalIgnoreCase))
            ProviderToggleCombo.SelectedIndex = 1;
        else
            ProviderToggleCombo.SelectedIndex = 0;

        // WPF Opacity < 1.0 sets WS_EX_LAYERED on the HWND, which makes
        // SetWindowDisplayAffinity silently fail.  When capture protection
        // is enabled we must keep opacity at 1.0.
        if (settings.EnableCaptureProtection)
        {
            Opacity = 1.0;
        }
        else
        {
            Opacity = settings.OverlayOpacity;
        }

        if (!IsVisible) Show();
        ApplyProtection(settings.EnableCaptureProtection);
        Activate();
        QuestionBox.Focus();

        if (MessagesPanel.Children.Count == 0)
        {
            string protectionNotice = settings.EnableCaptureProtection
                ? "Overlay protection (WDA) is ACTIVE. Excluded from screen capture/shares."
                : "Overlay protection is DISABLED.";
            AppendNote($"Ready. Active Provider: {settings.SelectedProvider}.\n{protectionNotice}");
        }
    }


    private void ApplyProtection(bool enable)
    {
        bool success = WdaProtectionHelper.SetProtection(this, enable);
        if (enable && success)
        {
            ProtectionBadge.Text = "Protected (WDA)";
            ProtectionBadge.Foreground = new SolidColorBrush(MediaColor.FromRgb(0x10, 0x7C, 0x41));
            ProtectionBadgeBorder.Background = new SolidColorBrush(MediaColor.FromRgb(0xDF, 0xF6, 0xDD));
            ProtectionBadgeBorder.BorderBrush = new SolidColorBrush(MediaColor.FromRgb(0x10, 0x7C, 0x41));
        }
        else
        {
            ProtectionBadge.Text = enable ? "Protection Error" : "Unprotected";
            ProtectionBadge.Foreground = new SolidColorBrush(MediaColor.FromRgb(0xA8, 0x00, 0x00));
            ProtectionBadgeBorder.Background = new SolidColorBrush(MediaColor.FromRgb(0xFD, 0xE7, 0xE9));
            ProtectionBadgeBorder.BorderBrush = new SolidColorBrush(MediaColor.FromRgb(0xA8, 0x00, 0x00));
        }
    }

    private async Task SendAsync(string? defaultQuestion = null)
    {
        if (_isBusy || _settings is null) return;

        string question = (defaultQuestion ?? QuestionBox.Text).Trim();
        if (question.Length == 0 && string.IsNullOrEmpty(_pendingImageDataUrl)) return;

        QuestionBox.Clear();
        string displayPrompt = question;
        if (!string.IsNullOrEmpty(_pendingImageDataUrl))
        {
            displayPrompt = string.IsNullOrEmpty(question)
                ? "📎 [Screenshot Attached]"
                : $"{question}\n📎 [Screenshot Attached]";
        }

        AppendMessage("You", displayPrompt, MessageKind.User);
        _history.Add(new ChatMessage("user", question, _pendingImageDataUrl));

        // Clear attached image after adding to history
        string? currentImage = _pendingImageDataUrl;
        ClearAttachment();

        _isBusy = true;
        SendButton.IsEnabled = false;
        StatusText.Text = currentImage != null ? "Processing with Vision model..." : "Getting a response...";

        try
        {
            string response = await QueryActiveLlmProviderAsync(_settings, _history, CancellationToken.None);
            _history.Add(new ChatMessage("assistant", response));
            _lastResponse = response;
            AppendMessage("Assistant", response, MessageKind.Assistant);
            StatusText.Text = "";
        }
        catch (Exception exception)
        {
            if (_history.LastOrDefault()?.Role == "user") _history.RemoveAt(_history.Count - 1);
            AppLogger.Error("Chat request failed.", exception);
            AppendMessage("Error", exception.Message, MessageKind.Error);
            StatusText.Text = "Request failed. Check settings and app.log.";
        }
        finally
        {
            _isBusy = false;
            SendButton.IsEnabled = true;
            QuestionBox.Focus();
        }
    }

    private async Task<string> QueryActiveLlmProviderAsync(
        AppSettings settings,
        IReadOnlyList<ChatMessage> history,
        CancellationToken token)
    {
        if (settings.SelectedProvider.Equals("Gemini", StringComparison.OrdinalIgnoreCase))
        {
            var geminiClient = new GeminiClient();
            return await geminiClient.SendAsync(settings, history, token);
        }
        else
        {
            var groqClient = new OpenAiCompatibleClient();
            return await groqClient.SendAsync(settings, history, token);
        }
    }

    private void SendButton_Click(object sender, RoutedEventArgs eventArgs) => _ = SendAsync();

    private void QuestionBox_KeyDown(object sender, System.Windows.Input.KeyEventArgs eventArgs)
    {
        if (eventArgs.Key == Key.Enter && Keyboard.Modifiers != ModifierKeys.Shift)
        {
            eventArgs.Handled = true;
            _ = SendAsync();
        }
    }

    private void QuestionBox_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs eventArgs)
    {
        if (eventArgs.Key == Key.V && Keyboard.Modifiers == ModifierKeys.Control)
        {
            string? base64 = ScreenCaptureService.CaptureClipboardImageToBase64();
            if (!string.IsNullOrEmpty(base64))
            {
                eventArgs.Handled = true;
                SetAttachment(base64, "📎 Screenshot pasted from clipboard");
            }
        }
    }


    private void ProviderToggleCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_settings == null || ProviderToggleCombo == null) return;
        string newProvider = ProviderToggleCombo.SelectedIndex == 1 ? "Gemini" : "Groq";
        if (_settings.SelectedProvider != newProvider)
        {
            _settings.SelectedProvider = newProvider;
            
            // Persist choice immediately
            var store = new SettingsStore();
            store.Save(_settings);
            
            StatusText.Text = $"Switched to {newProvider}";
        }
    }

    private void UiaRead_Click(object sender, RoutedEventArgs eventArgs)
    {
        StatusText.Text = "Reading active window UI...";
        string context = UiaContextService.ExtractActiveWindowContext();
        if (!string.IsNullOrWhiteSpace(context))
        {
            if (!string.IsNullOrWhiteSpace(QuestionBox.Text))
            {
                QuestionBox.Text += $"\n\n--- Extracted Text ---\n{context}";
            }
            else
            {
                QuestionBox.Text = $"{Api.Prompts.TextAnalysis}\n\n--- Extracted Text ---\n{context}";
            }
            StatusText.Text = "Active window text extracted!";
        }
        else
        {
            StatusText.Text = "Could not extract active window context.";
        }
    }

    private async void WatchScreen_Click(object sender, RoutedEventArgs eventArgs)
    {
        if (_isBusy) return;
        StatusText.Text = "Capturing screen...";

        // Briefly hide overlay window to capture what's behind it
        Hide();
        await Task.Delay(180);

        string base64 = ScreenCaptureService.CaptureScreenToBase64();

        if (_settings != null) ShowAssistant(_settings);

        if (!string.IsNullOrEmpty(base64))
        {
            SetAttachment(base64, "👁 Screen capture attached");
            string userQuestion = QuestionBox.Text.Trim();
            if (string.IsNullOrEmpty(userQuestion))
            {
                userQuestion = Api.Prompts.ScreenAnalysis;
            }
            _ = SendAsync(userQuestion);
        }
        else
        {
            StatusText.Text = "Failed to capture screen.";
        }
    }

    private void AttachImage_Click(object sender, RoutedEventArgs eventArgs)
    {
        // First check clipboard
        string? clipboardImage = ScreenCaptureService.CaptureClipboardImageToBase64();
        if (!string.IsNullOrEmpty(clipboardImage))
        {
            SetAttachment(clipboardImage, "📎 Image attached from clipboard");
            return;
        }

        // Fallback to file picker
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "Image Files|*.png;*.jpg;*.jpeg;*.bmp;*.webp|All Files|*.*",
            Title = "Select Image Attachment"
        };

        if (dialog.ShowDialog() == true)
        {
            try
            {
                using var bitmap = new System.Drawing.Bitmap(dialog.FileName);
                string base64 = ScreenCaptureService.EncodeBitmapToBase64DataUrl(bitmap);
                SetAttachment(base64, $"📎 {System.IO.Path.GetFileName(dialog.FileName)}");
            }
            catch (Exception ex)
            {
                StatusText.Text = $"Could not load image: {ex.Message}";
            }
        }
        else
        {
            StatusText.Text = "No image on clipboard. Snip a screenshot (Win+Shift+S), then try again.";
        }
    }

    private void SetAttachment(string base64DataUrl, string labelText)
    {
        _pendingImageDataUrl = base64DataUrl;
        AttachmentText.Text = labelText;
        AttachmentPanel.Visibility = Visibility.Visible;
        StatusText.Text = "Screenshot attached.";
    }

    private void ClearAttachment_Click(object sender, RoutedEventArgs eventArgs) => ClearAttachment();

    private void ClearAttachment()
    {
        _pendingImageDataUrl = null;
        AttachmentPanel.Visibility = Visibility.Collapsed;
    }

    private void CopyLast_Click(object sender, RoutedEventArgs eventArgs)
    {
        if (string.IsNullOrWhiteSpace(_lastResponse))
        {
            StatusText.Text = "There is no assistant response to copy yet.";
            return;
        }

        System.Windows.Clipboard.SetText(_lastResponse);
        StatusText.Text = "Latest assistant response copied.";

    }

    private void Clear_Click(object sender, RoutedEventArgs eventArgs)
    {
        _history.Clear();
        _lastResponse = "";
        ClearAttachment();
        MessagesPanel.Children.Clear();
        StatusText.Text = "Conversation cleared.";
    }

    private void Hide_Click(object sender, RoutedEventArgs eventArgs) => Hide();

    private void Window_Closing(object? sender, CancelEventArgs eventArgs)
    {
        if (!_closeForShutdown)
        {
            eventArgs.Cancel = true;
            Hide();
        }
    }

    public void CloseForShutdown()
    {
        _closeForShutdown = true;
        Close();
    }

    private void AppendMessage(string label, string content, MessageKind kind)
    {
        MediaColor labelColor = kind switch
        {
            MessageKind.User => MediaColor.FromRgb(0x27, 0x67, 0xC8),
            MessageKind.Error => MediaColor.FromRgb(0xB4, 0x23, 0x18),
            _ => MediaColor.FromRgb(0x1F, 0x53, 0x93),
        };
        MediaColor contentColor = kind == MessageKind.Error
            ? MediaColor.FromRgb(0x9D, 0x1C, 0x14)
            : MediaColor.FromRgb(0x21, 0x31, 0x4B);

        var card = new StackPanel { Margin = new Thickness(0, 0, 0, 14) };
        card.Children.Add(new TextBlock
        {
            Text = label,
            FontWeight = FontWeights.SemiBold,
            FontSize = 12,
            Foreground = new SolidColorBrush(labelColor),
            Margin = new Thickness(0, 0, 0, 3),
        });
        card.Children.Add(new TextBlock
        {
            Text = content,
            FontSize = 14,
            Foreground = new SolidColorBrush(contentColor),
            TextWrapping = TextWrapping.Wrap,
        });
        MessagesPanel.Children.Add(card);
        MessagesScroll.ScrollToEnd();
    }

    private void AppendNote(string text)
    {
        MessagesPanel.Children.Add(new TextBlock
        {
            Text = text,
            FontSize = 12,
            FontStyle = FontStyles.Italic,
            Foreground = new SolidColorBrush(MediaColor.FromRgb(0x53, 0x64, 0x7D)),
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12),
        });
    }

    private enum MessageKind { User, Assistant, Error }
}
