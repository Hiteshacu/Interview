using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace InterviewAssistant.Utilities;

public static class WdaProtectionHelper
{
    // Display affinity values
    private const uint WDA_NONE = 0x00000000;
    private const uint WDA_MONITOR = 0x00000001;
    private const uint WDA_EXCLUDEFROMCAPTURE = 0x00000011;

    // Window style constants
    private const int GWL_EXSTYLE = -20;
    private const uint WS_EX_LAYERED = 0x00080000;
    private const uint SWP_FRAMECHANGED = 0x0020;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOZORDER = 0x0004;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowDisplayAffinity(IntPtr hWnd, uint dwAffinity);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetWindowDisplayAffinity(IntPtr hWnd, out uint pdwAffinity);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
        int x, int y, int cx, int cy, uint uFlags);

    /// <summary>
    /// Strips WS_EX_LAYERED from the window's extended style. WDA is
    /// incompatible with layered windows — SetWindowDisplayAffinity
    /// silently returns FALSE if WS_EX_LAYERED is set.
    /// WPF sets WS_EX_LAYERED automatically when Window.Opacity &lt; 1.0.
    /// </summary>
    private static void StripLayeredStyle(IntPtr handle)
    {
        int exStyle = GetWindowLong(handle, GWL_EXSTYLE);
        if ((exStyle & (int)WS_EX_LAYERED) != 0)
        {
            exStyle &= ~(int)WS_EX_LAYERED;
            SetWindowLong(handle, GWL_EXSTYLE, exStyle);
            SetWindowPos(handle, IntPtr.Zero, 0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER);
            AppLogger.Info("Stripped WS_EX_LAYERED from overlay HWND for WDA compatibility.");
        }
    }

    public static bool SetProtection(Window window, bool enable)
    {
        IntPtr handle = new WindowInteropHelper(window).EnsureHandle();
        if (handle == IntPtr.Zero) return false;

        if (enable)
        {
            // Must strip WS_EX_LAYERED BEFORE calling SetWindowDisplayAffinity
            StripLayeredStyle(handle);
        }

        uint targetAffinity = enable ? WDA_EXCLUDEFROMCAPTURE : WDA_NONE;
        bool success = SetWindowDisplayAffinity(handle, targetAffinity);

        if (!success && enable)
        {
            // Fallback for older Windows 10 builds (pre-2004)
            targetAffinity = WDA_MONITOR;
            success = SetWindowDisplayAffinity(handle, WDA_MONITOR);
        }

        if (success)
        {
            // Verify the affinity was actually applied
            if (GetWindowDisplayAffinity(handle, out uint currentAffinity))
            {
                AppLogger.Info($"WDA protection set={enable}. Verified affinity=0x{currentAffinity:X}.");
                if (enable && currentAffinity == WDA_NONE)
                {
                    AppLogger.Error("WDA affinity verified as NONE despite success return — protection NOT active.", new InvalidOperationException("WDA verification failed"));
                    return false;
                }
            }
            return true;
        }
        else
        {
            int errorCode = Marshal.GetLastWin32Error();
            AppLogger.Error($"SetWindowDisplayAffinity failed (win32 error={errorCode}).",
                new System.ComponentModel.Win32Exception(errorCode));
            return false;
        }
    }

    public static bool IsProtected(Window window)
    {
        IntPtr handle = new WindowInteropHelper(window).Handle;
        if (handle == IntPtr.Zero) return false;
        if (GetWindowDisplayAffinity(handle, out uint affinity))
        {
            return affinity == WDA_EXCLUDEFROMCAPTURE || affinity == WDA_MONITOR;
        }
        return false;
    }
}
