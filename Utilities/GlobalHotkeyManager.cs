using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;

namespace InterviewAssistant.Utilities;

public sealed class GlobalHotkeyManager : IDisposable
{
    private const int HotkeyId = 1;
    private const int WmHotkey = 0x0312;
    private const uint ModAlt = 0x0001;
    private const uint ModControl = 0x0002;
    private const uint ModShift = 0x0004;
    private const uint ModWin = 0x0008;
    private const uint ModNoRepeat = 0x4000;

    private HwndSource? _source;
    private IntPtr _handle;

    public event EventHandler? Pressed;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint virtualKey);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    public void Attach(Window window)
    {
        _handle = new WindowInteropHelper(window).Handle;
        _source = HwndSource.FromHwnd(_handle);
        _source?.AddHook(WindowProc);
    }

    public void Register(string key, bool control, bool alt, bool shift, bool windows)
    {
        Unregister();
        if (!Enum.TryParse(key, true, out Key wpfKey))
        {
            throw new ArgumentException("Choose a valid hotkey.");
        }

        uint modifiers = ModNoRepeat;
        if (control) modifiers |= ModControl;
        if (alt) modifiers |= ModAlt;
        if (shift) modifiers |= ModShift;
        if (windows) modifiers |= ModWin;

        uint virtualKey = (uint)KeyInterop.VirtualKeyFromKey(wpfKey);
        if (!RegisterHotKey(_handle, HotkeyId, modifiers, virtualKey))
        {
            throw new InvalidOperationException("That hotkey is unavailable. Choose another combination.");
        }
    }

    public void Unregister()
    {
        if (_handle != IntPtr.Zero) UnregisterHotKey(_handle, HotkeyId);
    }

    private IntPtr WindowProc(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (message == WmHotkey && wParam.ToInt32() == HotkeyId)
        {
            handled = true;
            Pressed?.Invoke(this, EventArgs.Empty);
        }
        return IntPtr.Zero;
    }

    public void Dispose()
    {
        Unregister();
        _source?.RemoveHook(WindowProc);
    }
}
