using System.Globalization;
using System.Windows;
using System.Windows.Interop;
using InterviewAssistant.Api;
using InterviewAssistant.Configuration;
using InterviewAssistant.Utilities;
using Forms = System.Windows.Forms;

namespace InterviewAssistant;

public partial class MainWindow : Window
{
    private readonly SettingsStore _settingsStore = new();
    private readonly GlobalHotkeyManager _hotkeyManager = new();
    private readonly Forms.NotifyIcon _trayIcon;
    private AppSettings _settings;
    private OverlayWindow? _overlay;

    public MainWindow()
    {
        InitializeComponent();
        _settings = _settingsStore.Load();
        PopulateControls();

        _trayIcon = new Forms.NotifyIcon
        {
            Icon = System.Drawing.SystemIcons.Information,
            Text = "AI Interview Assistant",
            Visible = true,
            ContextMenuStrip = BuildTrayMenu(),
        };
        _trayIcon.DoubleClick += (_, _) => ShowSettings();

        SourceInitialized += OnSourceInitialized;
        _hotkeyManager.Pressed += (_, _) => OpenAssistant();
    }

    private void OnSourceInitialized(object? sender, EventArgs eventArgs)
    {
        _hotkeyManager.Attach(this);
        TryRegisterHotkey();
    }

    private void PopulateControls()
    {
        HotkeyBox.ItemsSource = new[]
        {
            "Space", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "A", "B", "C", "D", "E", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"
        };
        ApiEndpointBox.Text = _settings.ApiEndpoint;
        ModelBox.Text = _settings.Model;
        GroqVisionModelBox.Text = _settings.GroqVisionModel;
        GeminiVisionModelBox.Text = _settings.GeminiVisionModel;
        GroqKeyBox.Password = _settings.GroqApiKey;
        GeminiKeyBox.Password = _settings.GeminiApiKey;
        ProviderComboBox.SelectedIndex = _settings.SelectedProvider.Equals("Gemini", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
        EnableProtectionBox.IsChecked = _settings.EnableCaptureProtection;
        AutoUiaBox.IsChecked = _settings.AutoExtractUiaContext;
        HotkeyBox.SelectedItem = _settings.HotkeyKey;
        ControlBox.IsChecked = _settings.HotkeyControl;
        AltBox.IsChecked = _settings.HotkeyAlt;
        ShiftBox.IsChecked = _settings.HotkeyShift;
        WindowsBox.IsChecked = _settings.HotkeyWindows;
        OpacitySlider.Value = _settings.OverlayOpacity;
        WidthBox.Text = _settings.OverlayWidth.ToString(CultureInfo.InvariantCulture);
        HeightBox.Text = _settings.OverlayHeight.ToString(CultureInfo.InvariantCulture);
        LeftBox.Text = _settings.OverlayLeft.ToString(CultureInfo.InvariantCulture);
        TopBox.Text = _settings.OverlayTop.ToString(CultureInfo.InvariantCulture);
    }

    private bool SaveSettings()
    {
        try
        {
            AppSettings settings = ReadSettings();
            _settingsStore.Save(settings);
            _settings = settings;
            TryRegisterHotkey();
            StatusText.Text = $"Saved. Shortcut: {_settings.HotkeyDisplay}";
            AppLogger.Info("Settings saved.");
            return true;
        }
        catch (Exception exception)
        {
            StatusText.Text = exception.Message;
            AppLogger.Error("Could not save settings.", exception);
            return false;
        }
    }

    private AppSettings ReadSettings()
    {
        if (string.IsNullOrWhiteSpace(ApiEndpointBox.Text) || string.IsNullOrWhiteSpace(ModelBox.Text))
            throw new InvalidOperationException("API endpoint and model are required.");
        if (HotkeyBox.SelectedItem is not string hotkey)
            throw new InvalidOperationException("Choose a shortcut key.");

        return new AppSettings
        {
            ApiEndpoint = ApiEndpointBox.Text.Trim(),
            Model = ModelBox.Text.Trim(),
            GroqVisionModel = GroqVisionModelBox.Text.Trim(),
            GeminiVisionModel = GeminiVisionModelBox.Text.Trim(),
            GroqApiKey = GroqKeyBox.Password.Trim(),
            GeminiApiKey = GeminiKeyBox.Password.Trim(),
            SelectedProvider = ProviderComboBox.SelectedIndex == 1 ? "Gemini" : "Groq",
            EnableCaptureProtection = EnableProtectionBox.IsChecked == true,
            AutoExtractUiaContext = AutoUiaBox.IsChecked == true,
            HotkeyKey = hotkey,
            HotkeyControl = ControlBox.IsChecked == true,
            HotkeyAlt = AltBox.IsChecked == true,
            HotkeyShift = ShiftBox.IsChecked == true,
            HotkeyWindows = WindowsBox.IsChecked == true,
            OverlayOpacity = OpacitySlider.Value,
            OverlayWidth = ParseRange(WidthBox.Text, "Width", 360, 1000),
            OverlayHeight = ParseRange(HeightBox.Text, "Height", 420, 1000),
            OverlayLeft = ParseRange(LeftBox.Text, "Left position", -10000, 10000),
            OverlayTop = ParseRange(TopBox.Text, "Top position", -10000, 10000),
        };
    }

    private static double ParseRange(string value, string label, double min, double max)
    {
        if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed) || parsed < min || parsed > max)
            throw new InvalidOperationException($"{label} must be between {min} and {max}.");
        return parsed;
    }

    private void TryRegisterHotkey()
    {
        try
        {
            _hotkeyManager.Register(_settings.HotkeyKey, _settings.HotkeyControl, _settings.HotkeyAlt, _settings.HotkeyShift, _settings.HotkeyWindows);
        }
        catch (Exception exception)
        {
            StatusText.Text = $"Could not register {_settings.HotkeyDisplay}: {exception.Message}";
            AppLogger.Error("Could not register hotkey.", exception);
        }
    }

    private void SaveSettings_Click(object sender, RoutedEventArgs eventArgs) => SaveSettings();

    private void OpenAssistant_Click(object sender, RoutedEventArgs eventArgs)
    {
        if (SaveSettings()) OpenAssistant();
    }

    private void OpenAssistant()
    {
        _overlay ??= new OverlayWindow();
        _overlay.ShowAssistant(_settings);
    }

    private Forms.ContextMenuStrip BuildTrayMenu()
    {
        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("Open assistant", null, (_, _) => OpenAssistant());
        menu.Items.Add("Show settings", null, (_, _) => ShowSettings());
        menu.Items.Add("Exit", null, (_, _) => ExitApplication());
        return menu;
    }

    private void ShowSettings()
    {
        Show();
        WindowState = WindowState.Normal;
        Activate();
    }

    private void Exit_Click(object sender, RoutedEventArgs eventArgs) => ExitApplication();

    private void ExitApplication()
    {
        _overlay?.CloseForShutdown();
        Close();
    }

    protected override void OnClosed(EventArgs eventArgs)
    {
        _hotkeyManager.Dispose();
        _trayIcon.Dispose();
        base.OnClosed(eventArgs);
    }
}
