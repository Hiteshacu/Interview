
import threading
import time
import tkinter as tk
import ctypes
from ctypes import wintypes
import os
import sys

# Check and import pynput
try:
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    print("[+] pynput library loaded successfully")
except ImportError:
    print("[!] pynput not installed. Installing...")
    os.system(f"{sys.executable} -m pip install pynput -q")
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    print("[+] pynput installed and loaded successfully")

# ── Win32 API ─────────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32
SetWindowPos = user32.SetWindowPos
GetForegroundWindow = user32.GetForegroundWindow
GetWindowLongW = user32.GetWindowLongW
SetWindowLongW = user32.SetWindowLongW

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008

# ── Config ────────────────────────────────────────────────────────────────────
TRIGGER_KEY = keyboard.KeyCode.from_char('a')  # Show/hide overlay
AUTO_TYPE_KEY = keyboard.KeyCode.from_char('b')  # Long press for auto-type
AUTO_TYPE_PAUSE_KEY = keyboard.KeyCode.from_char('q')  # Double press to pause/resume
HOLD_SECONDS = 0.8
PAUSE_TOGGLE_PRESS_COUNT = 2
PAUSE_TOGGLE_WINDOW_SECONDS = 0.6
PAUSE_TOGGLE_CLEANUP_DELAY_SECONDS = 0.25
PAUSE_TOGGLE_REPAIR_CHARS = 8
TYPE_START_DELAY_SECONDS = 3.0
TYPE_CHARACTER_DELAY_SECONDS = 0.12
TYPE_SPACE_DELAY_SECONDS = 0.18
TYPE_PUNCTUATION_DELAY_SECONDS = 0.22
TYPE_NEWLINE_DELAY_SECONDS = 0.45
TYPE_PROGRESS_EVERY_CHARS = 100
TYPE_PUNCTUATION_CHARS = set(".,;:!?)]}\"'")
TYPE_TABS_AS_SPACES = True
TYPE_TAB_SIZE_SPACES = 2

# Single alert with Flutter code only
ALERTS = [
    {
        "title": "📝 EXAM CODE DISPLAY",
        "subtitle": "Flutter To-Do App - Auto-Type Ready",
        "content": """import 'package:flutter/material.dart';

void main() => runApp(const MaterialApp(home: TodoApp()));

class TodoApp extends StatefulWidget {
  const TodoApp({super.key});

  @override
  State<TodoApp> createState() => _TodoAppState();
}

class _TodoAppState extends State<TodoApp> {
  final List<String> tasks = [];
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
    setState(() {
      tasks.removeAt(index);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("To-Do List")),
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
}""",
        "color": "#FF6B35"
    }
]

CURRENT_ALERT = 0
# ──────────────────────────────────────────────────────────────────────────────

class OverlayWindow:
    """Advanced overlay with multiple bypass techniques."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.hwnd = None
        self._typing_thread = None
        self._typing_stop_event = threading.Event()
        self._typing_pause_event = threading.Event()
        self._typing_output_event = threading.Event()
        self._typing_repair_event = threading.Event()
        self._typed_content = ""
        self._typed_count = 0
        self._build()

    def _build(self):
        r = self.root
        r.title("AlertOverlay")
        r.overrideredirect(True)
        r.wm_attributes('-topmost', True)
        r.wm_attributes('-alpha', 0.98)
        r.configure(bg='#1a1a2e')

        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        r.geometry(f"{sw}x{sh}+0+0")

        r.update_idletasks()
        self.hwnd = ctypes.windll.user32.FindWindowW(None, "AlertOverlay")

        # Apply extended styles for click-through
        if self.hwnd:
            ex_style = GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                          ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT)

        # FULLSCREEN CARD - NO PADDING
        self.card = tk.Frame(r, bg='#1a1a2e', bd=0)
        self.card.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Header with dynamic color
        header = tk.Frame(self.card, bg='#1a1a2e')
        header.pack(fill='x', padx=12, pady=(8, 4))

        self.title_label = tk.Label(header, text=ALERTS[0]["title"],
                                    font=('Segoe UI', 16, 'bold'),
                                    fg=ALERTS[0]["color"], bg='#1a1a2e')
        self.title_label.pack()

        self.subtitle_label = tk.Label(header, text=ALERTS[0]["subtitle"],
                                       font=('Segoe UI', 8),
                                       fg='#888888', bg='#1a1a2e')
        self.subtitle_label.pack(pady=(1, 0))

        # Separator line with alert color
        self.separator = tk.Frame(header, height=1, bg=ALERTS[0]["color"])
        self.separator.pack(fill='x', pady=(2, 0))

# Content area with two-column layout - FULLSCREEN
        content_frame = tk.Frame(self.card, bg='#1a1a2e')
        content_frame.pack(fill='both', expand=True, padx=6, pady=6)
        left_frame = tk.Frame(content_frame, bg='#1a1a2e')
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 3))

        self.content_text_left = tk.Text(left_frame,
                                         font=('Consolas', 11),
                                         fg='#AAAAFF',
                                         bg='#0f0f15',
                                         wrap='word',
                                         padx=6,
                                         pady=6,
                                         selectforeground='#FFFFFF',
                                         selectbackground='#444466',
                                         borderwidth=0,
                                         highlightthickness=0,
                                         spacing1=0,
                                         spacing2=0,
                                         spacing3=0)
        self.content_text_left.pack(fill='both', expand=True)
        self.content_text_left.config(state='disabled')
        
        # Bind keyboard shortcuts for left column
        self.content_text_left.bind('<Control-c>', lambda e: self._copy_text())
        self.content_text_left.bind('<Control-a>', lambda e: self._select_all())
        self.content_text_left.bind('<Button-3>', lambda e: self._show_context_menu(e))

        # Right column
        right_frame = tk.Frame(content_frame, bg='#1a1a2e')
        right_frame.pack(side='right', fill='both', expand=True, padx=(3, 0))

        self.content_text_right = tk.Text(right_frame,
                                          font=('Consolas', 11),
                                          fg='#AAAAFF',
                                          bg='#0f0f15',
                                          wrap='word',
                                          padx=6,
                                          pady=6,
                                          selectforeground='#FFFFFF',
                                          selectbackground='#444466',
                                          borderwidth=0,
                                          highlightthickness=0,
                                          spacing1=0,
                                          spacing2=0,
                                          spacing3=0)
        self.content_text_right.pack(fill='both', expand=True)
        self.content_text_right.config(state='disabled')
        
        # Bind keyboard shortcuts for right column
        self.content_text_right.bind('<Control-c>', lambda e: self._copy_text())
        self.content_text_right.bind('<Control-a>', lambda e: self._select_all())
        self.content_text_right.bind('<Button-3>', lambda e: self._show_context_menu(e))

        # Initial content - split into two columns
        self._update_content_split(ALERTS[0]["content"])

        # Footer
        footer = tk.Frame(self.card, bg='#1a1a2e')
        footer.pack(fill='x', padx=12, pady=(4, 6))

        self.timestamp_var = tk.StringVar()
        tk.Label(footer, textvariable=self.timestamp_var,
                font=('Segoe UI', 7), fg='#666666',
                bg='#1a1a2e').pack()

        tk.Label(footer,
                text="Hold [A] to show | Release to hide | Hold [B] to auto-type code",
                font=('Segoe UI', 6), fg='#444444',
                bg='#1a1a2e').pack(pady=(0, 0))

        r.withdraw()

    def _update_content_split(self, content):
        """Split content into two columns."""
        lines = content.split('\n')
        mid = len(lines) // 2
        
        left_content = '\n'.join(lines[:mid])
        right_content = '\n'.join(lines[mid:])
        
        self.content_text_left.config(state='normal')
        self.content_text_left.delete('1.0', 'end')
        self.content_text_left.insert('1.0', left_content)
        self.content_text_left.config(state='disabled')
        
        self.content_text_right.config(state='normal')
        self.content_text_right.delete('1.0', 'end')
        self.content_text_right.insert('1.0', right_content)
        self.content_text_right.config(state='disabled')

    def cycle_alert(self):
        """Switch to next alert type."""
        global CURRENT_ALERT
        CURRENT_ALERT = (CURRENT_ALERT + 1) % len(ALERTS)
        alert = ALERTS[CURRENT_ALERT]

        self._update_content_split(alert["content"])

        self.title_label.config(text=alert["title"], fg=alert["color"])
        self.subtitle_label.config(text=alert["subtitle"])
        self.separator.config(bg=alert["color"])

    def bring_to_top(self):
        """Force window to top - called repeatedly."""
        if self.hwnd:
            SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def show_alert(self):
        import datetime
        self.timestamp_var.set(f"Active: {datetime.datetime.now():%H:%M:%S.%f} | Overlay Bypass Active")
        self.root.deiconify()
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.bring_to_top()

    def hide_alert(self):
        self.root.withdraw()

    def _copy_text(self):
        """Copy selected text or all content to clipboard."""
        try:
            # Try to get selected text
            active_widget = self.root.focus_get()
            if isinstance(active_widget, tk.Text):
                selected = active_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            else:
                # Copy all content if nothing selected
                selected = self.content_text_left.get('1.0', 'end-1c') + '\n' + \
                          self.content_text_right.get('1.0', 'end-1c')
            
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
            self.root.update()
            print("[+] Content copied to clipboard!")
        except tk.TclError:
            # Copy all if no selection
            all_text = self.content_text_left.get('1.0', 'end-1c') + '\n' + \
                      self.content_text_right.get('1.0', 'end-1c')
            self.root.clipboard_clear()
            self.root.clipboard_append(all_text)
            self.root.update()
            print("[+] All content copied to clipboard!")

    def _select_all(self):
        """Select all text in both columns."""
        self.content_text_left.config(state='normal')
        self.content_text_left.tag_add(tk.SEL, '1.0', tk.END)
        self.content_text_left.config(state='disabled')
        
        self.content_text_right.config(state='normal')
        self.content_text_right.tag_add(tk.SEL, '1.0', tk.END)
        self.content_text_right.config(state='disabled')
        print("[+] All text selected!")

    def _show_context_menu(self, event):
        """Show right-click context menu with copy/select options."""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Copy", command=self._copy_text)
        menu.add_command(label="Select All", command=self._select_all)
        menu.add_command(label="Auto-Type (Ctrl+I)", command=self.auto_type_content)
        menu.add_command(label="Screenshot", command=self._take_screenshot)
        menu.add_separator()
        menu.add_command(label="Save to File", command=self._save_content)
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _take_screenshot(self):
        """Capture screenshot of the overlay - bypass screenshot detection."""
        try:
            import subprocess
            from PIL import ImageGrab
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"exam_overlay_{timestamp}.png"
            
            # Capture fullscreen
            screenshot = ImageGrab.grab()
            screenshot.save(filename)
            print(f"[+] Screenshot saved: {filename}")
            
        except ImportError:
            print("[-] PIL not installed. Installing...")
            os.system("pip install pillow")
            
        except Exception as e:
            print(f"[!] Screenshot failed: {e}")

    def _save_content(self):
        """Save overlay content to file."""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"exam_content_{timestamp}.txt"
            
            left_text = self.content_text_left.get('1.0', 'end')
            right_text = self.content_text_right.get('1.0', 'end')
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=== LEFT COLUMN ===\n")
                f.write(left_text)
                f.write("\n\n=== RIGHT COLUMN ===\n")
                f.write(right_text)
            
            print(f"[+] Content saved: {filename}")
            
        except Exception as e:
            print(f"[!] Save failed: {e}")

    def _typing_delay_for(self, char):
        """Return the delay to use after typing a character."""
        if char == '\n':
            return TYPE_NEWLINE_DELAY_SECONDS
        if char.isspace():
            return TYPE_SPACE_DELAY_SECONDS
        if char in TYPE_PUNCTUATION_CHARS:
            return TYPE_PUNCTUATION_DELAY_SECONDS
        return TYPE_CHARACTER_DELAY_SECONDS

    def stop_auto_type(self):
        """Request any active auto-typing run to stop safely."""
        self._typing_stop_event.set()
        self._typing_pause_event.clear()
        self._typing_repair_event.clear()

    def is_auto_type_active(self):
        """Return True while an auto-typing thread can be paused or stopped."""
        return self._typing_thread is not None and self._typing_thread.is_alive()

    def is_auto_type_output_active(self):
        """Return True while this app is sending a simulated keypress."""
        return self._typing_output_event.is_set()

    def toggle_auto_type_pause(self, remove_toggle_keys=True):
        """Pause or resume the current auto-typing run."""
        if not self.is_auto_type_active():
            return

        if self._typing_pause_event.is_set():
            if remove_toggle_keys:
                self._remove_pause_toggle_keys(after_cleanup=self._resume_auto_type)
            else:
                self._resume_auto_type()
        else:
            self._typing_pause_event.set()
            if remove_toggle_keys:
                self._remove_pause_toggle_keys()
            print("[*] Auto-typing paused. Double-press Q again to resume.")

    def _resume_auto_type(self):
        self._typing_pause_event.clear()
        print("[*] Auto-typing resumed.")

    def _remove_pause_toggle_keys(self, after_cleanup=None):
        """Remove toggle keys and repair nearby text from the source buffer."""
        def cleanup():
            keyboard_controller = Controller()
            repair_count = min(self._typed_count, PAUSE_TOGGLE_REPAIR_CHARS)
            repair_text = self._typed_content[
                self._typed_count - repair_count:self._typed_count
            ]

            self._typing_output_event.set()
            self._typing_repair_event.set()
            try:
                delete_count = PAUSE_TOGGLE_PRESS_COUNT + repair_count
                for _ in range(delete_count):
                    keyboard_controller.press(Key.backspace)
                    keyboard_controller.release(Key.backspace)
                    time.sleep(0.02)

                if repair_text:
                    time.sleep(0.05)
                    for char in repair_text:
                        self._type_character(keyboard_controller, char)
                        time.sleep(0.01)
            finally:
                self._typing_repair_event.clear()
                self._typing_output_event.clear()

            if after_cleanup:
                after_cleanup()

        timer = threading.Timer(PAUSE_TOGGLE_CLEANUP_DELAY_SECONDS, cleanup)
        timer.daemon = True
        timer.start()

    def _type_character(self, keyboard_controller, char):
        """Type one source character while preserving editor-friendly indentation."""
        if char == '\n':
            keyboard_controller.press(Key.enter)
            keyboard_controller.release(Key.enter)
        elif char == '\t' and TYPE_TABS_AS_SPACES:
            keyboard_controller.type(" " * TYPE_TAB_SIZE_SPACES)
        elif char == '\t':
            keyboard_controller.press(Key.tab)
            keyboard_controller.release(Key.tab)
        else:
            keyboard_controller.type(char)

    def auto_type_content(self):
        """Type the overlay content gradually for UI simulation/testing."""
        if self._typing_thread and self._typing_thread.is_alive():
            self.stop_auto_type()
            print("[*] Stop requested for active auto-typing run.")
            return

        left_text = self.content_text_left.get('1.0', 'end-1c')
        right_text = self.content_text_right.get('1.0', 'end-1c')
        full_content = left_text + "\n" + right_text
        full_content = '\n'.join(line.rstrip() for line in full_content.split('\n'))

        self._typing_stop_event.clear()
        self._typing_pause_event.clear()
        self._typed_content = full_content
        self._typed_count = 0

        def type_thread(content):
            typed_count = 0
            total_chars = len(content)

            try:
                print("\n" + "="*60)
                print("[*] Auto-typing simulation starting.")
                print("[*] Focus the target input field now.")
                print(f"[*] Typing will begin in {TYPE_START_DELAY_SECONDS:.1f} seconds.")
                print("[*] Double-press Q to pause or resume without adding Q to the text.")
                print("[*] Run auto-type again or close the app to stop safely.")
                print("="*60)

                if self._typing_stop_event.wait(TYPE_START_DELAY_SECONDS):
                    print("[*] Auto-typing cancelled before it started.")
                    return

                keyboard_controller = Controller()
                print(f"\n[*] Typing started - {total_chars} characters to type...")

                for i, char in enumerate(content, start=1):
                    if self._typing_stop_event.is_set():
                        print(f"\n[*] Auto-typing stopped at {typed_count}/{total_chars} characters.")
                        return

                    while self._typing_pause_event.is_set():
                        if self._typing_stop_event.wait(0.1):
                            print(f"\n[*] Auto-typing stopped at {typed_count}/{total_chars} characters.")
                            return

                    while self._typing_repair_event.is_set():
                        if self._typing_stop_event.wait(0.05):
                            print(f"\n[*] Auto-typing stopped at {typed_count}/{total_chars} characters.")
                            return

                    try:
                        self._typing_output_event.set()
                        self._type_character(keyboard_controller, char)
                        typed_count += 1
                        self._typed_count = typed_count

                        if i % TYPE_PROGRESS_EVERY_CHARS == 0:
                            progress_pct = int(100 * i / total_chars)
                            print(f"    [{progress_pct}%] Typed {i}/{total_chars} characters...")

                    except Exception as e:
                        print(f"[!] Error typing char {char!r}: {e}")
                        continue
                    finally:
                        self._typing_output_event.clear()

                    if self._typing_stop_event.wait(self._typing_delay_for(char)):
                        print(f"\n[*] Auto-typing stopped at {typed_count}/{total_chars} characters.")
                        return

                print(f"\n[+] Finished typing {typed_count} out of {total_chars} characters.")
                print("="*60 + "\n")

            except Exception as e:
                print("\n[!] AUTO-TYPE FAILED!")
                print(f"[!] Error: {e}")
                import traceback
                traceback.print_exc()
                print("\n[!] Troubleshooting:")
                print("    1. Make sure an input field is focused")
                print("    2. Check pynput is installed: pip install pynput")
                print("    3. Some applications may ignore simulated input")

        print("\n[*] Starting auto-typing simulation thread...")
        self._typing_thread = threading.Thread(
            target=type_thread,
            args=(full_content,),
            daemon=True,
        )
        self._typing_thread.start()
        print("[*] Thread started - watch the terminal and input field.")


class KeyboardMonitor:
    """Global keyboard hook with cycle support."""

    def __init__(self, overlay: OverlayWindow, root: tk.Tk):
        self._overlay = overlay
        self._root = root
        self._press_time = None
        self._alert_on = False
        self._listener = None
        self._hold_timer = None
        self._topmost_timer = None
        self._autoype_press_time = None  # Separate tracking for [B] key
        self._autoype_timer = None
        self._pause_toggle_count = 0
        self._pause_toggle_last_press = 0

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        print("\n" + "="*60)
        print("  ADVANCED OVERLAY SYSTEM - EXAM CODE INJECTION")
        print("="*60)
        print(f"\n  [OK] Global keyboard hook active")
        print(f"  [OK] Hold [A] for {HOLD_SECONDS}s to show code overlay")
        print(f"  [OK] Hold [B] for {HOLD_SECONDS}s to auto-type code")
        print("\n  WORKFLOW:")
        print("    1. Hold [A] (0.8s) → Code overlay appears")
        print("    2. Click in exam input field to focus it")
        print("    3. Hold [B] (0.8s) → Auto-typing starts!")
        print("    4. Wait 3 seconds → Code begins typing")
        print("\n  FEATURES:")
        print("    ✓ Auto-type with 20ms character delays")
        print("    ✓ Handles special characters (newlines, tabs)")
        print("    ✓ Proper Flutter syntax (type-safe)")
        print("    ✓ Click-through overlay (won't block input)")
        print("    ✓ Always-on-top (above exam app)")
        print("\n  FOR MAXIMUM BYPASS: Run as Administrator")
        print("    (Right-click python → Run as Administrator)")
        print("="*60 + "\n")

    def stop(self):
        self._overlay.stop_auto_type()
        if self._listener:
            self._listener.stop()
        if self._topmost_timer:
            self._topmost_timer.cancel()

    def _on_press(self, key):
        # [A] key for showing overlay
        if key == TRIGGER_KEY and self._press_time is None:
            self._press_time = time.monotonic()
            self._hold_timer = threading.Timer(HOLD_SECONDS, self._fire_alert)
            self._hold_timer.start()
        
        # [B] key for auto-typing (long press)
        if key == AUTO_TYPE_KEY and self._autoype_press_time is None:
            self._autoype_press_time = time.monotonic()
            self._autoype_timer = threading.Timer(HOLD_SECONDS, self._fire_autotype)
            self._autoype_timer.start()

        # Double-press [Q] to pause/resume active auto-typing.
        if (
            key == AUTO_TYPE_PAUSE_KEY
            and self._overlay.is_auto_type_active()
            and not self._overlay.is_auto_type_output_active()
        ):
            now = time.monotonic()
            if now - self._pause_toggle_last_press <= PAUSE_TOGGLE_WINDOW_SECONDS:
                self._pause_toggle_count += 1
            else:
                self._pause_toggle_count = 1

            self._pause_toggle_last_press = now

            if self._pause_toggle_count >= PAUSE_TOGGLE_PRESS_COUNT:
                self._pause_toggle_count = 0
                self._root.after(0, self._overlay.toggle_auto_type_pause)

    def _on_release(self, key):
        # Release [A] key
        if key == TRIGGER_KEY:
            self._press_time = None
            if self._hold_timer:
                self._hold_timer.cancel()
                self._hold_timer = None
            if self._alert_on:
                self._alert_on = False
                if self._topmost_timer:
                    self._topmost_timer.cancel()
                self._root.after(0, self._overlay.hide_alert)
        
        # Release [B] key
        if key == AUTO_TYPE_KEY:
            self._autoype_press_time = None
            if self._autoype_timer:
                self._autoype_timer.cancel()
                self._autoype_timer = None

    def _fire_alert(self):
        self._alert_on = True
        self._root.after(0, self._overlay.show_alert)

        # Maintain topmost to fight fullscreen apps
        def maintain_topmost():
            if self._alert_on:
                self._overlay.bring_to_top()
                self._overlay.root.attributes('-topmost', True)
                self._topmost_timer = threading.Timer(0.1, maintain_topmost)
                self._topmost_timer.start()

        maintain_topmost()
    
    def _fire_autotype(self):
        """Trigger auto-typing when [B] is held long enough."""
        self._root.after(0, self._overlay.auto_type_content)


def main():
    root = tk.Tk()

    # Center on screen
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{sw}x{sh}+0+0")

    overlay = OverlayWindow(root)
    monitor = KeyboardMonitor(overlay, root)
    monitor.start()

    def on_close():
        monitor.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_close()


if __name__ == '__main__':
    main()
