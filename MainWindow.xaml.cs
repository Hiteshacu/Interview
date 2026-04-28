using System;
using System.Windows;
using System.Windows.Forms; // for NotifyIcon (add ref: System.Windows.Forms)

namespace OverlayAlert
{
    public partial class MainWindow : Window
    {
        private GlobalKeyboardHook? _hook;
        private OverlayWindow?      _overlay;
        private NotifyIcon?         _trayIcon;

        public MainWindow()
        {
            InitializeComponent();
            InitializeTrayIcon();
            StartHook();

            // Create overlay window once; show/hide on demand
            _overlay = new OverlayWindow();
            _overlay.Show(); // must call Show() first so HWND is created
            _overlay.Hide();
        }

        // ── Hook setup ────────────────────────────────────────────────────────

        private void StartHook()
        {
            try
            {
                _hook = new GlobalKeyboardHook(Dispatcher);
                _hook.AlertKeyDown += OnAlertKeyDown;
                _hook.AlertKeyUp   += OnAlertKeyUp;
                _hook.Install();
                StatusText.Text = "● Hook active — hold [A] to trigger overlay";
            }
            catch (Exception ex)
            {
                StatusText.Text = $"✗ Hook failed: {ex.Message}";
                StatusBorder.Background = new System.Windows.Media.SolidColorBrush(
                    System.Windows.Media.Color.FromArgb(0x22, 0x88, 0, 0));
            }
        }

        private const string FlutterCode = @"import 'package:flutter/material.dart';
void main() => runApp(const MaterialApp(home: TodoApp()));
class TodoApp extends StatefulWidget {
  const TodoApp({super.key});
  @override
  State createState() => _TodoAppState();
}
class _TodoAppState extends State<TodoApp> {
  final tasks = [];
  final controller = TextEditingController();
  void addTask() {
    if (controller.text.isNotEmpty) {
      setState(() {
        tasks.add(controller.text);
        controller.clear();
      });
    }
  }
  void removeTask(int index) {
    setState(() => tasks.removeAt(index));
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text(""To-Do List"")),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                hintText: 'Enter task',
                suffixIcon: Icon(Icons.task),
              ),
              onSubmitted: (_) => addTask(),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: ListView.builder(
                itemCount: tasks.length,
                itemBuilder: (_, i) => ListTile(
                  title: Text(tasks[i]),
                  trailing: IconButton(
                    icon: const Icon(Icons.delete, color: Colors.red),
                    onPressed: () => removeTask(i),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: addTask,
        child: const Icon(Icons.add),
      ),
    );
  }
}";

        private void OnAlertKeyDown(object? sender, EventArgs e)
        {
            // Already on UI thread (marshalled by GlobalKeyboardHook)
            string alertText = AlertTextBox?.Text ?? "SECURITY ALERT";
            _overlay?.ShowAlert(alertText, FlutterCode);
        }

        private void OnAlertKeyUp(object? sender, EventArgs e)
        {
            _overlay?.HideAlert();
        }

        // ── Button handlers ───────────────────────────────────────────────────

        private void MinimizeToTray_Click(object sender, RoutedEventArgs e)
        {
            Hide(); // hide main config window; hook keeps running
        }

        private void TestOverlay_Click(object sender, RoutedEventArgs e)
        {
            string alertText = AlertTextBox?.Text ?? "TEST ALERT";
            _overlay?.ShowAlert(alertText, "Manual test — click anywhere or press A to dismiss");

            // Auto-hide after 3 s in test mode
            var timer = new System.Windows.Threading.DispatcherTimer
            {
                Interval = TimeSpan.FromSeconds(3)
            };
            timer.Tick += (_, __) => { timer.Stop(); _overlay?.HideAlert(); };
            timer.Start();
        }

        private void Exit_Click(object sender, RoutedEventArgs e)
        {
            Cleanup();
            System.Windows.Application.Current.Shutdown();
        }

        // ── Tray icon ─────────────────────────────────────────────────────────

        private void InitializeTrayIcon()
        {
            _trayIcon = new NotifyIcon
            {
                Icon    = System.Drawing.SystemIcons.Shield,
                Visible = true,
                Text    = "Alert Overlay System",
                ContextMenuStrip = BuildTrayMenu()
            };
            _trayIcon.DoubleClick += (_, __) => { Show(); WindowState = WindowState.Normal; };
        }

        private ContextMenuStrip BuildTrayMenu()
        {
            var menu = new ContextMenuStrip();
            menu.Items.Add("Show config", null, (_, __) => { Show(); Activate(); });
            menu.Items.Add("Exit",        null, (_, __) => Exit_Click(this, new RoutedEventArgs()));
            return menu;
        }

        // ── Cleanup ───────────────────────────────────────────────────────────

        private void Cleanup()
        {
            _hook?.Dispose();
            _trayIcon?.Dispose();
            _overlay?.Close();
        }

        protected override void OnClosed(EventArgs e)
        {
            Cleanup();
            base.OnClosed(e);
        }
    }
}
