using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;

namespace OverlayAlert
{
    public partial class OverlayWindow : Window
    {
        // Win32 extended window style constants
        private const int GWL_EXSTYLE   = -20;
        private const int WS_EX_TRANSPARENT = 0x00000020;   // click-through
        private const int WS_EX_TOOLWINDOW = 0x00000080;    // hide from Alt-Tab
        private const int WS_EX_NOACTIVATE  = 0x08000000;   // never steals focus

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr hwnd, int index);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int SetWindowLong(IntPtr hwnd, int index, int newStyle);

        public OverlayWindow()
        {
            InitializeComponent();
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);

            // Make the overlay window focusless and hidden from Alt-Tab
            // NOTE: We do NOT use WS_EX_TRANSPARENT here because it prevents scrolling
            // Instead, we use a hit test override to pass clicks through the transparent areas
            var hwnd = new WindowInteropHelper(this).Handle;
            int style = GetWindowLong(hwnd, GWL_EXSTYLE);
            SetWindowLong(hwnd, GWL_EXSTYLE,
                style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE);

            // Set up Win32 composition to allow layered window effects
            HwndSource.FromHwnd(hwnd).AddHook(WndProc);
        }

        private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            const int WM_NCHITTEST = 0x0084;

            if (msg == WM_NCHITTEST)
            {
                // Check if the hit point is over the content area
                var hitTestResult = IntPtr.Zero;
                if (GetHitTestResult(lParam) == HitTestResult.Content)
                {
                    handled = false; // Let WPF handle it
                }
                else
                {
                    // Pass clicks through transparent areas to the window underneath
                    hitTestResult = new IntPtr(-1); // HTTRANSPARENT
                    handled = true;
                }
                return hitTestResult;
            }

            return IntPtr.Zero;
        }

        private enum HitTestResult
        {
            Transparent,
            Content
        }

        private HitTestResult GetHitTestResult(IntPtr lParam)
        {
            // Convert the hit test point to client coordinates
            var pt = new System.Windows.Point(
                unchecked((short)(lParam.ToInt32() & 0xFFFF)),
                unchecked((short)((lParam.ToInt32() >> 16) & 0xFFFF))
            );

            // Check if the point is within the Border (content area)
            // If Border is visible, it means content is shown
            if (Visibility == Visibility.Visible)
            {
                // Simple check: if the point is roughly in the center area, it's over content
                var rect = new System.Windows.Rect(
                    this.ActualWidth * 0.1,
                    this.ActualHeight * 0.1,
                    this.ActualWidth * 0.8,
                    this.ActualHeight * 0.8
                );

                if (rect.Contains(pt))
                {
                    return HitTestResult.Content;
                }
            }

            return HitTestResult.Transparent;
        }

        public void ShowAlert(string message, string code)
        {
            AlertMessage.Text = message;
            AlertCode.Text    = code;
            AlertTimestamp.Text = $"Triggered at {DateTime.Now:HH:mm:ss.fff}";
            Visibility = Visibility.Visible;
        }

        public void HideAlert()
        {
            Visibility = Visibility.Hidden;
        }

        // Handle mouse wheel for proper scrolling within the overlay
        private void ScrollViewer_PreviewMouseWheel(object sender, System.Windows.Input.MouseWheelEventArgs e)
        {
            e.Handled = true;
            if (sender is ScrollViewer scrollViewer)
            {
                scrollViewer.ScrollToVerticalOffset(scrollViewer.VerticalOffset - e.Delta);
            }
        }
    }
}
