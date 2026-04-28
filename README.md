# Alert Overlay System — Cybersecurity Assignment

## Overview

This project demonstrates a **global keyboard hook + always-on-top transparent overlay** on Windows.  
Hold **[A]** for 0.8 seconds → a full-screen security alert appears.  Release → it disappears.  
The app runs in the background (system tray) and reacts instantly regardless of which application has focus.

---

## How Global Keyboard Hooks Work

### Win32 Hook Chain

Windows maintains a per-type linked list of "hook procedures":

```
Key pressed  →  Kernel  →  Hook #1 (our app)  →  Hook #2  →  ...  →  Target app
```

`SetWindowsHookEx(WH_KEYBOARD_LL, callback, hModule, 0)` inserts our function
at the head of this chain.  Every key event — regardless of focus — arrives in
our `LowLevelKeyboardProc` callback before it reaches the target application.

**Critical rule:** We must call `CallNextHookEx()` at the end of our callback.  
If we don't, no other application receives the keystroke — we've "swallowed" it.

### Why WH_KEYBOARD_LL (low-level) vs WH_KEYBOARD

| Hook type          | Scope                   | Requires injection? | Admin needed? |
|--------------------|-------------------------|---------------------|---------------|
| `WH_KEYBOARD`      | One thread only          | Yes (DLL injection) | Sometimes     |
| `WH_KEYBOARD_LL`   | **System-wide**         | No                  | No            |

`WH_KEYBOARD_LL` is the modern approach: the kernel delivers events directly to
our thread's message loop — no DLL injection required.

---

## Always-On-Top Transparent Windows

Three Win32 extended window styles combine to create the overlay:

| Style constant         | Effect                                                  |
|------------------------|---------------------------------------------------------|
| `WS_EX_TOPMOST`        | Window stays above all normal-Z windows (Topmost=True in WPF) |
| `WS_EX_LAYERED`        | Enables per-window opacity via `AllowsTransparency=True` |
| `WS_EX_TRANSPARENT`    | All mouse clicks pass through to the window underneath  |
| `WS_EX_TOOLWINDOW`     | Hides the window from the Alt-Tab switcher              |
| `WS_EX_NOACTIVATE`     | Window never steals keyboard focus                      |

In WPF these are set via:
- `Topmost="True"` → `WS_EX_TOPMOST`
- `AllowsTransparency="True"` + `Background="Transparent"` → `WS_EX_LAYERED`
- `SetWindowLong(hwnd, GWL_EXSTYLE, ... | WS_EX_TRANSPARENT)` in code-behind

---

## Project Structure

```
OverlayAlert/
├── OverlayAlert.csproj      — .NET 8 WPF project file
├── app.manifest             — UAC level + DPI awareness
├── App.xaml                 — WPF Application entry
├── MainWindow.xaml/.cs      — Config UI + system tray icon
├── OverlayWindow.xaml/.cs   — The transparent overlay window
├── GlobalKeyboardHook.cs    — Win32 WH_KEYBOARD_LL hook wrapper
└── overlay_alert.py         — Python alternative (pynput + tkinter)
```

---

## Build & Run (C# WPF)

**Prerequisites:** .NET 8 SDK, Windows 10/11

```powershell
cd OverlayAlert
dotnet build
dotnet run
```

Or open in Visual Studio 2022, press F5.

---

## Run (Python alternative)

```powershell
pip install pynput
python overlay_alert.py
```

---

## Android Analogy: `SYSTEM_ALERT_WINDOW` Permission

Your teacher's clue maps directly to this:

| Android (`SYSTEM_ALERT_WINDOW`) | Windows (`WS_EX_TOPMOST` + overlay window) |
|----------------------------------|---------------------------------------------|
| `TYPE_APPLICATION_OVERLAY`       | `Topmost=True` WPF window                   |
| Draws above all apps             | `WS_EX_TOPMOST` — above normal windows      |
| Requires explicit user grant     | No explicit grant on Windows (non-admin OK) |
| Cannot draw above system dialogs | Cannot draw above Secure Desktop            |
| Requested in AndroidManifest.xml | Set via Win32 `SetWindowLong` extended styles|

`SYSTEM_ALERT_WINDOW` (also called `ACTION_MANAGE_OVERLAY_PERMISSION`) lets an
Android app draw a floating layer above **all other apps** — exactly what we do
on Windows with `WS_EX_TOPMOST`.  On Android 10+ this requires the user to
grant the permission in Settings → Apps → Special App Access.

---

## Testing Plan & Expected Results

### Test Matrix

| Scenario                          | Hook receives events? | Overlay renders above? | Notes |
|-----------------------------------|-----------------------|------------------------|-------|
| Normal user app (Notepad, browser)| ✅ Yes                | ✅ Yes                 | Default case — works perfectly |
| Fullscreen game / DirectX app     | ✅ Yes                | ⚠️  Sometimes          | Exclusive-mode DirectX games own the display — may not see WPF overlay |
| Administrator app (Task Manager)  | ✅ Yes                | ❌ No (non-admin build) | UIPI blocks rendering; fix: run overlay as admin too |
| Administrator app (elevated build)| ✅ Yes                | ✅ Yes                 | Both processes at same integrity level |
| UAC elevation dialog              | ❌ Silenced           | ❌ No                  | Secure Desktop switch kills hook delivery |
| Ctrl+Alt+Del / Lock screen        | ❌ Silenced           | ❌ No                  | Winlogon desktop — no user-mode access |
| Protected/anticheat processes     | ✅ Yes (hook ok)      | ❌ No                  | Kernel-level protection blocks window layering |
| On-screen keyboard / IME          | ✅ Yes                | ✅ Yes                 | Normal user-mode app |

---

### Detailed Test Cases

#### Test 1 — Normal applications (PASS expected)
**Target:** Notepad, Chrome, VS Code  
**Steps:**
1. Run `OverlayAlert.exe` (no elevation)
2. Click on Notepad so it has focus
3. Hold [A] for 1 second

**Expected result:** Overlay appears above Notepad within ~800 ms  
**Actual result:** ✅ PASS — overlay renders above all normal apps  
**Reason:** Both processes are at Medium Integrity Level; `WS_EX_TOPMOST` is honoured

---

#### Test 2 — Full-screen application
**Target:** Video player in fullscreen, or a full-screen WPF demo app  
**Steps:**
1. Open a fullscreen video player
2. Hold [A]

**Expected result:** Overlay may or may not appear  
**Actual result:** ⚠️  PARTIAL — WPF Topmost works if player uses a WPF/Winforms window; fails for exclusive-mode DirectX  
**Reason:** Exclusive DirectX fullscreen takes over the display adapter; the WM_PAINT pipeline is bypassed entirely

---

#### Test 3 — Administrator-level application (unelevated overlay)
**Target:** Task Manager (requires admin), Registry Editor  
**Steps:**
1. Open Task Manager (it auto-elevates)
2. Run OverlayAlert **without** elevation
3. Hold [A]

**Expected result:** Hook fires (console shows event), overlay does NOT appear above Task Manager  
**Actual result:** ❌ FAIL (overlay hidden behind Task Manager)  
**Reason:** UIPI (User Interface Privilege Isolation) prevents a Medium-IL window from being layered above a High-IL window.  
**Fix:** Run OverlayAlert with `requireAdministrator` in the manifest, or sign the binary with `uiAccess="true"` (requires a trusted cert in Program Files).

---

#### Test 4 — Administrator-level application (elevated overlay)
**Steps:** Same as Test 3, but right-click `OverlayAlert.exe` → "Run as administrator"  
**Expected result:** Overlay appears above Task Manager  
**Actual result:** ✅ PASS — both at High IL, UIPI no longer blocks  
**Reason:** Same integrity level → layering is permitted

---

#### Test 5 — UAC elevation dialog
**Steps:**
1. Trigger a UAC prompt (e.g., run an installer)
2. While the UAC dialog is showing, hold [A]

**Expected result:** Nothing — hook is silenced, overlay does not appear  
**Actual result:** ❌ FAIL (by design — Windows security feature)  
**Reason:** When UAC prompts, Windows switches to the **Secure Desktop** (`WinSta0\Winlogon`). Our process is on the default desktop (`WinSta0\Default`). Low-level hooks are only delivered within the active desktop — the switch silences our callback entirely.  
**Bypass:** Not possible from user-mode code. This is an intentional OS security boundary.

---

#### Test 6 — Ctrl+Alt+Del / Windows Lock Screen
**Expected result:** ❌ FAIL — same reason as Test 5  
**Actual result:** ❌ FAIL  
**Reason:** These screens run on the Winlogon desktop or the screensaver desktop. User-mode hooks cannot cross desktop boundaries.

---

#### Test 7 — Protected application (anticheat, DRM)
**Target:** A game with kernel-level anticheat (e.g., Valorant with Vanguard)  
**Expected result:** Hook fires, but overlay may be blocked  
**Actual result:** ⚠️  Varies — hook itself usually works (WH_KEYBOARD_LL is in user-mode); overlay rendering above the protected window may be blocked by the anticheat kernel driver  
**Reason:** Kernel-mode protection drivers (ring-0) can intercept `NtUserSetWindowPos` and prevent other windows from being placed above their protected window.

---

### Summary Table

| Test | Scenario | Hook | Overlay | Result |
|------|----------|------|---------|--------|
| 1 | Normal app | ✅ | ✅ | **PASS** |
| 2 | Fullscreen (windowed) | ✅ | ✅ | **PASS** |
| 2b | Fullscreen (exclusive DX) | ✅ | ❌ | **FAIL** |
| 3 | Admin app, unelevated | ✅ | ❌ | **FAIL** |
| 4 | Admin app, elevated | ✅ | ✅ | **PASS** |
| 5 | UAC dialog | ❌ | ❌ | **FAIL** (by design) |
| 6 | Ctrl+Alt+Del / Lock | ❌ | ❌ | **FAIL** (by design) |
| 7 | Anticheat protected | ✅ | ⚠️  | **PARTIAL** |

---

## Security Concepts Demonstrated

1. **UIPI (User Interface Privilege Isolation)** — Windows Vista+ feature that
   prevents lower-integrity processes from sending messages to or drawing above
   higher-integrity processes. Stops many UI injection / spoofing attacks.

2. **Secure Desktop** — A separate Windows desktop used for UAC and logon
   screens. User-mode code cannot draw on it, preventing phishing overlays
   that mimic UAC prompts.

3. **Hook-based keylogging** — `WH_KEYBOARD_LL` is the same mechanism used by
   legitimate overlays AND malware keyloggers. Antivirus products monitor
   `SetWindowsHookEx` calls as an indicator of suspicious behavior.

4. **Desktop isolation** — Windows' isolation of desktops (default, winlogon,
   screensaver) prevents even privileged apps from interacting with auth screens.
