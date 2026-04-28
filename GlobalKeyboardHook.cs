using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Threading;

namespace OverlayAlert
{
    /// <summary>
    /// Installs a WH_KEYBOARD_LL (low-level keyboard) hook that fires for
    /// every key event system-wide, regardless of which window has focus.
    ///
    /// HOW GLOBAL HOOKS WORK:
    ///   Windows maintains a chain of "hook procedures" per hook type.
    ///   SetWindowsHookEx(WH_KEYBOARD_LL, ...) inserts our callback at the
    ///   front of the chain.  Every time a key is pressed/released anywhere,
    ///   the kernel posts a WM_KEYDOWN / WM_KEYUP message to our thread's
    ///   message queue, which calls LowLevelKeyboardProc.
    ///   We MUST call CallNextHookEx so other hooks in the chain still fire.
    ///
    /// PRIVILEGE NOTE:
    ///   WH_KEYBOARD_LL works from a normal (non-admin) process.
    ///   However, when a UAC elevation dialog or the Secure Desktop is active,
    ///   Windows switches to a separate desktop (WinSta0\Winlogon) and our hook
    ///   is silenced — we receive no events during that window.
    /// </summary>
    public class GlobalKeyboardHook : IDisposable
    {
        // Win32 hook type for low-level keyboard events
        private const int WH_KEYBOARD_LL = 13;

        // Virtual key codes
        private const int VK_A = 0x41;

        // Message codes inside KBDLLHOOKSTRUCT
        private const int WM_KEYDOWN   = 0x0100;
        private const int WM_KEYUP     = 0x0101;
        private const int WM_SYSKEYDOWN = 0x0104;
        private const int WM_SYSKEYUP   = 0x0105;

        [StructLayout(LayoutKind.Sequential)]
        private struct KBDLLHOOKSTRUCT
        {
            public uint   vkCode;      // virtual key code
            public uint   scanCode;    // hardware scan code
            public uint   flags;
            public uint   time;
            public IntPtr dwExtraInfo;
        }

        private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetWindowsHookEx(int idHook,
            LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);

        [DllImport("user32.dll")]
        private static extern bool UnhookWindowsHookEx(IntPtr hhk);

        [DllImport("user32.dll")]
        private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode,
            IntPtr wParam, IntPtr lParam);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetModuleHandle(string lpModuleName);

        // Events raised on the WPF UI thread via Dispatcher
        public event EventHandler? AlertKeyDown;
        public event EventHandler? AlertKeyUp;

        private IntPtr                 _hookHandle  = IntPtr.Zero;
        private LowLevelKeyboardProc?  _hookProc;   // keep delegate alive — GC guard
        private readonly Dispatcher    _dispatcher;

        // Hold-timer: overlay fires only after the key is held ≥ HoldMs
        private readonly DispatcherTimer _holdTimer;
        private const int HoldMs = 800;
        private bool _alertActive = false;

        public GlobalKeyboardHook(Dispatcher dispatcher)
        {
            _dispatcher = dispatcher;

            _holdTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(HoldMs) };
            _holdTimer.Tick += (_, __) =>
            {
                _holdTimer.Stop();
                _alertActive = true;
                AlertKeyDown?.Invoke(this, EventArgs.Empty);
            };
        }

        public void Install()
        {
            _hookProc = HookCallback; // store to prevent GC collection
            using var proc = Process.GetCurrentProcess();
            using var module = proc.MainModule!;
            _hookHandle = SetWindowsHookEx(WH_KEYBOARD_LL, _hookProc,
                GetModuleHandle(module.ModuleName!), 0);

            if (_hookHandle == IntPtr.Zero)
                throw new InvalidOperationException(
                    $"SetWindowsHookEx failed (error {Marshal.GetLastWin32Error()})");
        }

        public void Uninstall()
        {
            if (_hookHandle != IntPtr.Zero)
            {
                UnhookWindowsHookEx(_hookHandle);
                _hookHandle = IntPtr.Zero;
            }
        }

        private IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
        {
            if (nCode >= 0)
            {
                var info = Marshal.PtrToStructure<KBDLLHOOKSTRUCT>(lParam);

                // Only respond to our trigger key (A)
                if (info.vkCode == VK_A)
                {
                    int msg = wParam.ToInt32();
                    bool isDown = msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN;
                    bool isUp   = msg == WM_KEYUP   || msg == WM_SYSKEYUP;

                    if (isDown && !_holdTimer.IsEnabled && !_alertActive)
                    {
                        // Key just pressed — start hold timer on UI thread
                        _dispatcher.BeginInvoke(() => _holdTimer.Start());
                    }
                    else if (isUp)
                    {
                        _dispatcher.BeginInvoke(() =>
                        {
                            _holdTimer.Stop();
                            if (_alertActive)
                            {
                                _alertActive = false;
                                AlertKeyUp?.Invoke(this, EventArgs.Empty);
                            }
                        });
                    }
                }
            }

            // CRITICAL: always call next hook so other apps still receive key events
            return CallNextHookEx(_hookHandle, nCode, wParam, lParam);
        }

        public void Dispose() => Uninstall();
    }
}
