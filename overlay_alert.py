"""Groq Overlay - a global-hotkey full-screen chatbot.

Hold [A] for ~0.8 seconds anywhere on the desktop and a full-screen Groq chat
overlay appears and takes focus so you can type. Type q q q (or press Esc) to
close it.

Inside the chat you can attach a screenshot (click the 📎 button or press
Ctrl+V after snipping with Win+Shift+S) and ask about it - image turns are
routed to a vision-capable model automatically.

The app runs quietly in the background; nothing shows until you summon it.

Setup
-----
1. pip install pynput pillow    (pillow is only needed for screenshots)
2. Get an API key from https://console.groq.com and paste it into API_KEYS
   below. Keys are read from there only - never from the environment.
3. python overlay_alert.py

Optionally set GROQ_MODEL (default "openai/gpt-oss-120b").

OCR.space + Groq (many more screenshots per day than a vision model allows):
paste a free key from https://ocr.space/ocrapi into OCR_SPACE_API_KEY and a
Groq key into GROQ_OCR_API_KEY, both in API_KEYS below. Screenshots are then
read by OCR.space and answered by a Groq text model. Check the OCR key with:
    python overlay_alert.py --ocr some_screenshot.png
"""

import base64
import ctypes
import ctypes.wintypes
import io
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.error
import urllib.parse
import urllib.request

from pynput import keyboard

try:
    from PIL import Image, ImageGrab
    _PIL_OK = True
except ImportError:  # Pillow is only needed for screenshot attachments
    _PIL_OK = False

# -- Configuration ----------------------------------------------------------
APP_TITLE = "Groq Overlay"


def _env_or_registry(name, default=""):
    """Return an env var, falling back to the Windows user Environment registry.

    Used for optional settings such as model names - never for API keys, which
    come from API_KEYS alone (see _api_key).

    `setx` writes to HKCU\\Environment but does NOT update the running shell, so
    a key set with setx in the same terminal is invisible to this process until
    a new terminal is opened. Reading the registry directly makes it work now.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            found, _ = winreg.QueryValueEx(handle, name)
            found = (found or "").strip()
            return found if found else default
    except OSError:
        return default


# Paste API keys here. This is the ONLY place a key is read from: environment
# variables and `setx` values are ignored, so the script behaves the same on
# every machine. A provider whose entry is missing or "" is simply skipped.
# Anyone who gets this file gets these keys - do not commit or share it filled in.
API_KEYS = {
    "GROQ_API_KEY": "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",
    "GEMINI_API_KEY": "AQ.Ab8RN6IPjUz7aBU1WMvFp2qsCA2ov8nKvwZhxugaP5QD7kDJ0g",
    "MISTRAL_API_KEY": "mstrl_R6KBZlbXu54sTvRGKGOUs5tAzEm3AFLI_2OI1ET",
    # OCR.space + Groq (see OCR_PROVIDER below): the OCR.space key reads the
    # screenshot, and this Groq key - kept apart from GROQ_API_KEY so the two do
    # not share a quota - answers from the text.
    "OCR_SPACE_API_KEY": "K82922311588957",
    "GROQ_OCR_API_KEY": "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",
}


def _api_key(name, default=""):
    """Return the key pasted into API_KEYS. The environment is never consulted."""
    return API_KEYS.get(name, "").strip() or default


GROQ_API_KEY = _api_key("GROQ_API_KEY")
GEMINI_API_KEY = _api_key("GEMINI_API_KEY")
ACTIVE_PROVIDER = "groq"

GROQ_MODEL = _env_or_registry("GROQ_MODEL", "openai/gpt-oss-120b")
# Vision-capable model used only when a screenshot is attached or Watch is used.
GROQ_VISION_MODEL = _env_or_registry("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GEMINI_MODEL = _env_or_registry("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# -- OCR.space + Groq --------------------------------------------------------
# A screenshot sent to a vision model is billed as an image: about 70-100 a day
# on Groq, 20 requests per model on Gemini. Reading it with OCR.space first and
# sending only the text to a Groq text model costs a fraction of that, so far
# more screenshots fit in a day. The price is that pictures and diagrams are
# lost - when OCR finds no text the chain falls through to a real vision model.
OCR_PROVIDER = "ocr+groq"
OCR_SPACE_API_KEY = _api_key("OCR_SPACE_API_KEY")
OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"
OCR_SPACE_ENGINE = _env_or_registry("OCR_SPACE_ENGINE", "2")       # 2 reads screen text best
OCR_SPACE_LANGUAGE = _env_or_registry("OCR_SPACE_LANGUAGE", "eng")
# Tried in order, each with its own daily quota on the OCR Groq key.
GROQ_OCR_MODELS = [model.strip() for model in _env_or_registry(
    "GROQ_OCR_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-120b").split(",") if model.strip()]
# True: screenshots go through OCR first and vision models are the fallback.
# False: vision models first, OCR only once they are out of quota.
OCR_FIRST = True
OCR_MAX_FILE_BYTES = 950 * 1024    # OCR.space's free plan rejects files over 1024 KB
OCR_MIN_CHARS = 15                 # less than this is not a readable question
# Groq sits behind Cloudflare, which blocks the default "Python-urllib" agent
# with a 403 (error code 1010). A normal browser User-Agent avoids that.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SYSTEM_PROMPT = """You are an expert answering assistant for technical and aptitude questions.

HOW TO THINK
Work the problem out BEFORE you commit to an answer, and write that working down -
a model that states its answer first and justifies it afterwards gets aptitude
questions wrong. Keep the working terse: derive the answer, then check it.

ACCURACY RULES
- Derive the answer; never pattern-match on which option "looks" right.
- For multiple choice, test EVERY option against your derived rule.
  If two options fit or none fit, your rule is wrong - re-derive it.
- If the text you were given is garbled or incomplete, say so and state what you
  think it says, rather than guessing an answer.
- NEVER answer a question you had to invent. If the text has answer options but no
  actual question - no sentence ending in "?", no instruction such as "find",
  "which", "what" or "how many" - then the question line was lost in capture.
  Reply "The question text is missing", quote what you did receive, and stop. A
  premise on its own is not a question: a list of renamings, a code mapping or a
  set of statements tells you the rules, not what is being asked.
- Never invent an option letter that was not shown.

LOGICAL REASONING / APTITUDE PLAYBOOK
- Jumbled / scrambled words: unscramble EVERY word letter-by-letter before judging
  anything. Write out each solved word, check that the letters match exactly (same
  letters, same count), then find the category the majority share. The odd one out
  is the one outside that category. Example: RCA=CAR, USB=BUS, IKEB=BIKE, GDO=DOG
  -> three vehicles + one animal, so DOG is the odd one. Note that the category is
  only visible AFTER unscrambling - never judge the scrambled strings themselves.
- Odd one out (general): name the shared property of the majority explicitly, then
  confirm exactly one item lacks it.
- Number / letter series: compute successive differences, ratios, or alphabet
  positions; verify the rule against every given term before extending it.
- Coding-decoding: map letters to positions, find the shift or rule, apply to all
  letters, verify by re-encoding the given example.
- Blood relations / seating / puzzles: write out the chain or arrangement step by
  step; do not answer from the first plausible reading.
- Syllogisms: test each conclusion against the premises only; ignore real-world
  knowledge.
- "X is called Y" renaming puzzles: these need a real-world fact FIRST. Ask what
  colour or nature the object actually has in reality (bulb light is yellow, the
  clear sky is blue, blood is red, grass is green, turmeric is yellow, milk is
  white, coal is black). Then apply the renaming ONCE: whatever the object really
  is, the answer is what that thing "is called" in the puzzle. Do not follow the
  chain past one step, and do not pick the last colour in the list.
- Code-language questions ("564 means study very hard"): find a word that appears
  in exactly two of the statements, then intersect the digit sets of those two
  statements. The single digit they share is that word's code. Verify by checking
  a second word the same way.
- Analogies: state the exact relation in the first pair, then apply it literally.
- Arithmetic: show the computation and re-check it once.

OUTPUT FORMAT
- Multiple choice: at most 6 short lines of working (the derivation, plus the check
  of every option), then a final line that starts exactly with
  "Answer: <letter>) <option text>". The app moves that line to the top for the
  reader, so it must appear exactly once per question and must be the literal
  answer, not a reference to one.
- Coding problems: a one-line plan, then the complete runnable solution.
- Short answer / fill in the blank: one line of working, then the "Answer:" line.
- Multiple questions: handle them one at a time, each with its own "Answer:" line,
  numbered.
- No filler, no restating the question, no apologies."""
# Shown when the model was cut off mid-answer. It goes at the TOP of the reply:
# a truncated reasoning model dumps its scratch work, and a warning buried under
# that is a warning nobody reads.
_TRUNCATED_NOTE = "[Cut off at the token limit - this reply is incomplete. Ask again, or switch to a model with more room.]"

REQUEST_TIMEOUT_SECONDS = 60
MAX_IMAGE_DIM = 1600  # screenshots are OCR input: keep glyphs readable
MAX_BASE64_LENGTH = 3_500_000  # Groq rejects base64 images larger than ~4 MB
MAX_EXTRACTED_CHARS = 12000  # cap on window text sent as context

TRIGGER_KEY = "a"            # hold this key to summon the chat overlay
HOLD_SECONDS = 0.8          # how long the trigger key must be held
CLOSE_KEY = "q"             # press this key repeatedly to dismiss the overlay
CLOSE_REPEAT = 3            # number of presses...
CLOSE_WINDOW_SECONDS = 0.8  # ...required within this rolling time window

# Reasoning models wrap their scratch work in <think>...</think>; strip it, then
# lift the "Answer:" line to the top so the answer is readable at a glance.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_STRAY_THINK_RE = re.compile(r"</?think>", re.IGNORECASE)
_ANSWER_LINE_RE = re.compile(r"^[ \t]*(?:\*\*)?answer\s*[:\-].*$",
                             re.IGNORECASE | re.MULTILINE)


def _strip_think(text):
    """Remove scratch work, tolerating a <think> tag the model forgot to close."""
    cleaned = _THINK_RE.sub("", text or "")
    if "<think>" in cleaned.lower():
        # Unterminated block: the working ran straight into the answer.
        match = _ANSWER_LINE_RE.search(cleaned)
        if match:
            cleaned = cleaned[match.start():]
    return _STRAY_THINK_RE.sub("", cleaned).strip()


def _answer_first(text):
    """Move a single "Answer: ..." line to the top, keeping the working below.

    The model is told to derive before it answers, because answering first and
    justifying afterwards is what makes it fail aptitude questions. This puts the
    result back where a reader needs it without costing that accuracy. Replies
    with several answers (one per question) are left in their original order.
    """
    if not text:
        return text
    matches = _ANSWER_LINE_RE.findall(text)
    if len(matches) != 1:
        return text
    match = _ANSWER_LINE_RE.search(text)
    answer = match.group(0).strip()
    rest = (text[:match.start()] + text[match.end():]).strip()
    return f"{answer}\n\n{rest}" if rest else answer


# Options with no question line means the capture clipped the stem - the single
# most damaging failure mode, because the model will happily invent a question
# that fits the premise and answer that instead.
_OPTION_LINE_RE = re.compile(r"^\s*(?:\(?[a-dA-D][\).]|[1-4][\).])\s+\S", re.MULTILINE)
_QUESTION_HINT_RE = re.compile(
    r"\?|\b(find|which|what|when|where|who|how|choose|identify|select|complete|"
    r"odd one|coded|written|arranged|next in|related)\b", re.IGNORECASE)


def looks_incomplete(text):
    """True when the text offers answer options but never asks anything."""
    if not text:
        return False
    return bool(_OPTION_LINE_RE.search(text)) and not _QUESTION_HINT_RE.search(text)


# -- Windows UI Automation Text Extraction (No Screenshot) -------------------
def _extract_active_window_text():
    """Extract text content from the active foreground window without taking screenshots.
    Uses Win32 APIs and UIA node property retrieval.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()

        lines = []
        if title:
            lines.append(f"[Active Window: {title}]")

        seen = set()

        def add_text(t, prefix=""):
            if not t:
                return
            t = t.strip()
            if len(t) >= 2 and t not in seen:
                seen.add(t)
                lines.append(f"{prefix}{t}" if prefix else t)

        # 1. Try SendMessageW / GetWindowTextW for control texts
        WM_GETTEXT = 0x000D
        WM_GETTEXTLENGTH = 0x000E

        def enum_child_proc(child_hwnd, _lparam):
            try:
                txt_len = user32.SendMessageW(child_hwnd, WM_GETTEXTLENGTH, 0, 0)
                if 0 < txt_len < 30000:
                    c_buf = ctypes.create_unicode_buffer(txt_len + 1)
                    user32.SendMessageW(child_hwnd, WM_GETTEXT, txt_len + 1, c_buf)
                    add_text(c_buf.value)
                else:
                    c_len = user32.GetWindowTextLengthW(child_hwnd)
                    if 0 < c_len < 30000:
                        c_buf = ctypes.create_unicode_buffer(c_len + 1)
                        user32.GetWindowTextW(child_hwnd, c_buf, c_len + 1)
                        add_text(c_buf.value)
            except Exception:
                pass
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_proc), 0)

        # 2. Try UIAutomationCore for deep UIA text
        try:
            uiauto = ctypes.windll.UIAutomationCore
            node = ctypes.c_void_p()
            if uiauto.UiaNodeFromHandle(hwnd, ctypes.byref(node)) == 0 and node:
                class VARIANT(ctypes.Structure):
                    _fields_ = [("vt", ctypes.c_ushort), ("wReserved1", ctypes.c_ushort),
                                ("wReserved2", ctypes.c_ushort), ("wReserved3", ctypes.c_ushort),
                                ("bstrVal", ctypes.c_wchar_p), ("pad", ctypes.c_ulonglong)]

                for prop_id in (30045, 30005):  # UIA_ValueValuePropertyId, UIA_NamePropertyId
                    var = VARIANT()
                    if uiauto.UiaGetPropertyValue(node, prop_id, ctypes.byref(var)) == 0:
                        if var.vt == 8 and var.bstrVal:  # VT_BSTR
                            add_text(var.bstrVal)
                uiauto.UiaNodeRelease(node)
        except Exception:
            pass

        if lines:
            # Budget by characters, not by element count: capping at 50 elements
            # silently drops the question stem on a busy page.
            out, used = [], 0
            for line in lines:
                if used + len(line) > MAX_EXTRACTED_CHARS:
                    break
                out.append(line)
                used += len(line) + 1
            return "\n".join(out or lines[:1])
        return f"[Active Window: {title}]" if title else None
    except Exception as err:
        return f"Error reading window text: {err}"


# -- WDA Capture Protection --------------------------------------------------
_WDA_NONE = 0x00000000
_WDA_MONITOR = 0x00000001
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
_GA_ROOT = 2

# Win32 window style constants
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU = 0x00080000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_SWP_FRAMECHANGED = 0x0020
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_HWND_TOPMOST = -1

try:
    _user32 = ctypes.windll.user32
    _SetWindowDisplayAffinity = _user32.SetWindowDisplayAffinity
    _SetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
    _SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
    _GetWindowDisplayAffinity = _user32.GetWindowDisplayAffinity
    _GetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
    _GetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
    _GetAncestor = _user32.GetAncestor
    _GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
    _GetAncestor.restype = ctypes.wintypes.HWND
    _GetWindowLongW = _user32.GetWindowLongW
    _GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _GetWindowLongW.restype = ctypes.wintypes.LONG
    _SetWindowLongW = _user32.SetWindowLongW
    _SetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.LONG]
    _SetWindowLongW.restype = ctypes.wintypes.LONG
    _SetWindowPos = _user32.SetWindowPos
    _SetWindowPos.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint,
    ]
    _SetWindowPos.restype = ctypes.wintypes.BOOL
    _WDA_AVAILABLE = True
except Exception:
    _WDA_AVAILABLE = False


def _get_toplevel_hwnd(tk_widget):
    """Get the true Win32 HWND that DWM composites for a Tk widget."""
    tk_widget.update_idletasks()
    child = tk_widget.winfo_id()
    if not child:
        return None
    hwnd = _GetAncestor(child, _GA_ROOT)
    return hwnd if hwnd else child


def _make_borderless_wda_compatible(tk_widget):
    """Remove title bar/borders via Win32 styles and strip WS_EX_LAYERED
    so that SetWindowDisplayAffinity works.

    WDA_EXCLUDEFROMCAPTURE is incompatible with layered windows
    (WS_EX_LAYERED).  Tkinter sets WS_EX_LAYERED when you use
    ``-alpha`` or ``overrideredirect(True)`` in some builds, so we
    must clear it manually.
    """
    if not _WDA_AVAILABLE:
        return
    hwnd = _get_toplevel_hwnd(tk_widget)
    if not hwnd:
        return
    # Remove caption, thick frame, min/max/sys buttons
    style = _GetWindowLongW(hwnd, _GWL_STYLE)
    style &= ~(_WS_CAPTION | _WS_THICKFRAME | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX | _WS_SYSMENU)
    _SetWindowLongW(hwnd, _GWL_STYLE, style)
    # Remove WS_EX_LAYERED (incompatible with WDA) and WS_EX_APPWINDOW;
    # add WS_EX_TOOLWINDOW so it hides from taskbar/Alt-Tab
    exstyle = _GetWindowLongW(hwnd, _GWL_EXSTYLE)
    exstyle &= ~_WS_EX_LAYERED
    exstyle &= ~_WS_EX_APPWINDOW
    exstyle |= _WS_EX_TOOLWINDOW
    _SetWindowLongW(hwnd, _GWL_EXSTYLE, exstyle)
    # Tell the window manager styles changed
    _SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                  _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER)


def _apply_wda_protection(tk_widget):
    """Apply WDA_EXCLUDEFROMCAPTURE to a Tkinter Toplevel window.

    Excludes the window from all screen-capture pipelines so it appears
    as black / invisible in any screen share or recording while remaining
    fully visible on the physical display.
    """
    if not _WDA_AVAILABLE:
        return False
    try:
        hwnd = _get_toplevel_hwnd(tk_widget)
        if not hwnd:
            return False
        ok = _SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)
        if not ok:
            ok = _SetWindowDisplayAffinity(hwnd, _WDA_MONITOR)
        # Verify
        if ok:
            current = ctypes.wintypes.DWORD(0)
            _GetWindowDisplayAffinity(hwnd, ctypes.byref(current))
        return bool(ok)
    except Exception:
        return False


def _hide_console_window():
    """Hide the Python console window from taskbar and screen."""
    try:
        kernel32 = ctypes.windll.kernel32
        console_hwnd = kernel32.GetConsoleWindow()
        if console_hwnd:
            _SW_HIDE = 0
            ctypes.windll.user32.ShowWindow(console_hwnd, _SW_HIDE)
    except Exception:
        pass


def _hide_tk_from_taskbar(tk_widget):
    """Apply WS_EX_TOOLWINDOW to a Tk/Toplevel so it never shows in taskbar."""
    if not _WDA_AVAILABLE:
        return
    try:
        tk_widget.update_idletasks()
        hwnd = _get_toplevel_hwnd(tk_widget)
        if not hwnd:
            return
        exstyle = _GetWindowLongW(hwnd, _GWL_EXSTYLE)
        exstyle &= ~_WS_EX_APPWINDOW
        exstyle |= _WS_EX_TOOLWINDOW
        _SetWindowLongW(hwnd, _GWL_EXSTYLE, exstyle)
        _SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                      _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER)
    except Exception:
        pass


# -- Palette ----------------------------------------------------------------
COLOR_BACKDROP = "#0a0e17"
COLOR_CARD = "#171f2e"
COLOR_CONVO = "#0f1626"
COLOR_TEXT = "#e6edf7"
COLOR_MUTED = "#8a97ad"
COLOR_ACCENT = "#4c8dff"
COLOR_USER = "#7fd1ff"
COLOR_BOT = "#c9d6ea"
COLOR_ERROR = "#ff8a8a"


# A small local model needs more scaffolding than a frontier one: it follows an
# explicit procedure well, but drifts when told to "reason carefully". This is the
# same task as SYSTEM_PROMPT, rewritten as steps it can execute in order.
LOCAL_SYSTEM_PROMPT = """You answer technical and aptitude multiple-choice questions. Follow this procedure exactly.

STEP 1 - READ
Copy the question and every option exactly as given. If there are options but no
actual question, reply "The question text is missing" and stop.

STEP 2 - SOLVE, using the rule that matches the question type:
- Jumbled/scrambled words: unscramble each word one at a time. Write "SCRAMBLED = WORD"
  for every one. Check the letters match exactly. Then name the category most of the
  solved words share. The odd one is the one outside that category.
- Odd one out (letters): convert each group to alphabet positions (A=1, B=2 ... Z=26)
  and write the gaps between them. Four groups share one gap pattern; one does not.
- Number series: write the difference or ratio between each pair of terms. Confirm the
  same rule holds for every pair before using it.
- Coding-decoding: compare the code letter by letter with the original, write the shift
  for each position, then apply that shift to the new word letter by letter.
- Blood relations: write the family chain one link at a time.
- Technical questions (SQL, OOP, networking, complexity, OS): state the definition of
  the key term first, then match it to the options.
- "X is called Y" renaming puzzles: these need a real-world fact FIRST. Ask what
  colour or nature the object actually has in reality (bulb light is yellow, the
  clear sky is blue, blood is red, grass is green, turmeric is yellow, milk is
  white, coal is black). Then apply the renaming ONCE: whatever the object really
  is, the answer is what that thing "is called" in the puzzle. Do not follow the
  chain past one step, and do not pick the last colour in the list.
- Code-language questions ("564 means study very hard"): find a word that appears
  in exactly two of the statements, then intersect the digit sets of those two
  statements. The single digit they share is that word's code. Verify by checking
  a second word the same way.

STEP 3 - CHECK
Test every option against your rule. Exactly one must fit. If two fit or none fit, your
rule is wrong - go back to STEP 2 and try a different rule.

STEP 4 - REPLY
Keep the working to at most 5 short lines, then end with exactly one line:
Answer: <letter>) <option text>

- Never choose an option because it is "most plausible", "commonly the answer", or
  the only one left. If you cannot derive it, say you cannot derive it.

Never guess. Never skip STEP 3. Never write more than one "Answer:" line per question."""


# -- Providers ---------------------------------------------------------------
# Every provider here except Gemini speaks the OpenAI chat-completions format, so
# adding one is a table entry rather than new code. Point `endpoint` at the
# service, name its API_KEYS entry, and it can be added to a chain. Only Groq,
# Gemini and OCR+Groq are in the chains; the rest are defined but unused.
#
# `metering` records how the provider bills: by tokens, by whole requests, or
# not at all ("local", which is never put on cooldown). No provider is probed -
# a model is only ever called to answer a question.
PROVIDERS = {
    "groq": {
        "kind": "openai",
        "endpoint": GROQ_ENDPOINT,
        "key_name": "GROQ_API_KEY",
        "metering": "tokens",
        # Groq reserves prompt + max_tokens against its 8000/minute ceiling, so
        # this cap is a Groq constraint - not something to impose on providers
        # that do not bill that way, where it just truncates the answer.
        "max_tokens": 4096,
    },
    "gemini": {
        "kind": "gemini",
        "key_name": "GEMINI_API_KEY",
        "metering": "requests",
    },
    # Not a service of its own: OCR.space turns the screenshot into text, then
    # Groq answers it. See _call_ocr_groq.
    OCR_PROVIDER: {
        "kind": "ocr",
        "endpoint": GROQ_ENDPOINT,
        "key_name": "GROQ_OCR_API_KEY",
        "metering": "tokens",
        "max_tokens": 4096,
    },
    "cerebras": {
        "kind": "openai",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "key_name": "CEREBRAS_API_KEY",
        "metering": "tokens",
    },
    "openrouter": {
        "kind": "openai",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "key_name": "OPENROUTER_API_KEY",
        "metering": "requests",
        "headers": {"X-Title": "Interview Assistant"},
    },
    "github": {
        "kind": "openai",
        "endpoint": "https://models.github.ai/inference/chat/completions",
        "key_name": "GITHUB_MODELS_TOKEN",
        "metering": "requests",
    },
    "nvidia": {
        "kind": "openai",
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_name": "NVIDIA_API_KEY",
        "metering": "tokens",
        "timeout": 120,      # the free tier queues; 60s is not enough for a cold model
    },
    "ollama": {
        "kind": "openai",
        "endpoint": _env_or_registry("OLLAMA_ENDPOINT",
                                     "http://localhost:11434/v1/chat/completions"),
        "key_name": "OLLAMA_API_KEY",
        "key_optional": True,      # a local server authenticates nobody
        "metering": "local",       # no quota to run out of, so never cooled down
        "system_prompt": LOCAL_SYSTEM_PROMPT,
        # Context window, measured on an 8 GB RTX 4060 with qwen3.5:9b: 8192 runs
        # 100% on the GPU (5.6 GB); 12288 already pushes 14% onto the CPU and
        # 16384 pushes 25%, which made answers time out. Ollama's own default of
        # 4096 is too small the other way - the model thought for 3,405 tokens,
        # filled it, and was cut off before writing any answer.
        "num_ctx": 8192,
        # Room left for thinking plus the answer once the ~1,000-token prompt is in.
        "max_tokens": 7168,
        # Thinking stays on. Off, answers took 5-26s instead of 35-100s, but the
        # renaming puzzle came back wrong (Yellow, not Blue). This is the last
        # resort in the chain, so a right answer beats a fast one.
        "think": True,
        # A thinking model on a laptop GPU can take minutes on a hard puzzle, and
        # the first request after launch also loads it into VRAM.
        "timeout": 300,
    },
    "mistral": {
        "kind": "openai",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "key_name": "MISTRAL_API_KEY",
        "metering": "tokens",
    },
    "openai": {
        "kind": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "key_name": "OPENAI_API_KEY",
        "metering": "tokens",
    },
}

# Keys are read once at startup, from API_KEYS only.
for _name, _spec in PROVIDERS.items():
    if _spec.get("key_optional"):
        _spec["key"] = _api_key(_spec["key_name"], "local")
    elif _name == "groq":
        _spec["key"] = GROQ_API_KEY
    elif _name == "gemini":
        _spec["key"] = GEMINI_API_KEY
    elif _name == OCR_PROVIDER:
        # Works before the dedicated key is added, at the cost of sharing quota.
        _spec["key"] = _api_key(_spec["key_name"]) or GROQ_API_KEY
    else:
        _spec["key"] = _api_key(_spec["key_name"])


def provider_key(provider):
    spec = PROVIDERS.get(provider)
    return spec.get("key", "") if spec else ""


def provider_endpoint(provider):
    spec = PROVIDERS.get(provider) or {}
    return spec.get("endpoint", "")


def _models_url(provider):
    """The /v1/models endpoint that sits alongside a chat-completions URL."""
    endpoint = provider_endpoint(provider)
    marker = "/chat/completions"
    return endpoint[: -len(marker)] + "/models" if endpoint.endswith(marker) else ""


def list_provider_models(provider):
    """Ask a provider which model ids it accepts - used by `--models <provider>`."""
    url = _models_url(provider)
    if not url:
        raise RuntimeError(f"{provider} does not expose a models list.")
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {provider_key(provider)}")
    request.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return sorted(entry.get("id", "") for entry in body.get("data", []))


_LOCAL_CHECK_TTL = 30
_LOCAL_STATE = {}          # provider -> (checked_at, up, reason)


def _local_server_state(provider):
    """Is the local model server running?

    Checked against its version endpoint rather than by generating a token: a
    real completion would load the model into VRAM and take tens of seconds,
    which is far too slow for a status check that runs whenever the menu opens.
    """
    cached = _LOCAL_STATE.get(provider)
    if cached is not None and time.time() - cached[0] < _LOCAL_CHECK_TTL:
        return cached[1], cached[2]

    base = provider_endpoint(provider).split("/v1/")[0]
    try:
        with urllib.request.urlopen(f"{base}/api/version", timeout=3) as response:
            response.read()
        state = (True, "local, no quota")
    except Exception:
        state = (False, "server not running (start: ollama serve)")

    _LOCAL_STATE[provider] = (time.time(), state[0], state[1])
    return state


def local_models(provider="ollama"):
    """Model names already pulled on this machine."""
    base = provider_endpoint(provider).split("/v1/")[0]
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return [entry.get("name", "") for entry in body.get("models", [])]


# -- Model fallback chain ----------------------------------------------------
# Free tiers are metered per MODEL, not per key: when one model is out of quota
# the next entry still has a full budget. So instead of one configured model,
# the app walks an ordered chain and moves on when a model refuses.
#
# Ordered by measured accuracy first, then speed and budget. On the same test set
# (jumbled words, code-language, renaming, analogy, SQL, and a screenshot)
# qwen/qwen3.8-27b and gemini-3.5-flash both scored 6/6 - but qwen answered in
# 1-4s against Gemini's 5-15s, and Groq meters tokens (about 70-100 questions a
# day) where Gemini allows only 20 requests per model. qwen therefore leads, and
# Gemini's scarce requests are kept for when Groq's per-minute cap is hit.
#
# qwen is the ONLY Groq model that accepts images - every other model on the
# account rejects image content with a 400. Groq renames it with each release
# (3.6 -> 3.8); a stale id is healed automatically, see _find_successor.
VISION_CHAIN = [
    ("groq", "qwen/qwen3.8-27b"),
    ("gemini", "gemini-3.5-flash"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("gemini", "gemini-3.7-flash"),
    ("gemini", "gemini-3.6-flash"),
    ("gemini", "gemini-2.5-flash"),
]

# gpt-oss-120b sits behind Gemini: it is quick, but it gets the renaming type of
# question wrong ("colour of light from a bulb" -> it answers Yellow, not Blue).
TEXT_CHAIN = [
    ("groq", "qwen/qwen3.8-27b"),
    ("gemini", "gemini-3.5-flash"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("gemini", "gemini-3.7-flash"),
    ("gemini", "gemini-2.5-flash"),
    ("groq", "openai/gpt-oss-120b"),
]

# Model order for a local (Ollama) entry, should one be added to a chain.
_LOCAL_PREFERENCE = ("qwen3.5:9b", "qwen3.5:4b", "qwen3-vl:8b", "qwen3-vl:4b",
                     "gemma4:latest", "gemma4:e2b")


def _apply_override(chain, provider, configured):
    """Make an env-configured model its provider's first choice, in place.

    It used to be pushed to the front of the whole chain. A GROQ_VISION_MODEL set
    long ago then jumped ahead of every Gemini model - and when Groq retired that
    model, every screenshot started by hitting a model that no longer exists.
    """
    configured = (configured or "").strip()
    if not configured:
        return
    entry = (provider, configured)
    if entry in chain:
        chain.remove(entry)
    same_provider = [index for index, existing in enumerate(chain) if existing[0] == provider]
    chain.insert(same_provider[0] if same_provider else len(chain), entry)


# Only values the user actually set count - not the defaults above.
_apply_override(VISION_CHAIN, "groq", _env_or_registry("GROQ_VISION_MODEL", ""))
_apply_override(VISION_CHAIN, "gemini", _env_or_registry("GEMINI_MODEL", ""))
_apply_override(TEXT_CHAIN, "groq", _env_or_registry("GROQ_MODEL", ""))
_apply_override(TEXT_CHAIN, "gemini", _env_or_registry("GEMINI_MODEL", ""))

_OCR_ENTRIES = [(OCR_PROVIDER, model) for model in GROQ_OCR_MODELS]
VISION_CHAIN[:] = _OCR_ENTRIES + VISION_CHAIN if OCR_FIRST else VISION_CHAIN + _OCR_ENTRIES

_COOLDOWNS = {}          # (provider, model) -> epoch second it may be tried again; loaded below
_NO_VISION = set()       # entries that rejected an image outright
# Refusals that waiting will not fix - payment required, a model not in your plan,
# a model the provider retired. entry -> (reason, recheck_at). They are rechecked
# once a day, because plans change and a user may add billing.
_BLOCKED = {}
_BLOCK_RECHECK = 24 * 3600
# Renamed models: old entry -> new entry, learned from a 404 (see _find_successor).
_ALIASES = {}
PINNED_MODEL = None      # set from the header menu; None means "walk the chain"

_RETRY_RE = re.compile(r"([\d.]+)(ms|h|m|s)")
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_DEFAULT_COOLDOWN = 900          # unknown quota reset: re-check in 15 minutes
_DAILY_COOLDOWN = 3600           # a per-day quota will not free up sooner
_MAX_COOLDOWN = 6 * 3600


# Cooldowns outlive the process: a daily quota is still spent after a restart, so
# reloading them stops the app burning a request on a model it already knows is
# out. Stored beside the app's other state, and silently ignored if unreadable.
_COOLDOWN_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "InterviewAssistant", "model_cooldowns.json")


def _split_key(key):
    provider, _, model = str(key).partition("|")
    return (provider, model) if model else None


def _load_cooldowns():
    """Restore cooldowns, permanent refusals, and learned renames.

    None of these clear by restarting, so forgetting them meant every launch
    spent a request rediscovering each one.
    """
    try:
        with open(_COOLDOWN_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}

    now = time.time()
    if "cooldowns" in stored:
        cooldowns = stored["cooldowns"]
    elif "billing" in stored:            # the previous format
        cooldowns = {}
    else:                                # the original flat {key: timestamp} map
        cooldowns = stored
    for key in stored.get("billing") or []:
        entry = _split_key(key)
        if entry:
            _BLOCKED[entry] = ("needs billing (HTTP 402)", now + _BLOCK_RECHECK)
    for key, value in (stored.get("blocked") or {}).items():
        entry = _split_key(key)
        if entry and isinstance(value, list) and len(value) == 2 and value[1] > now:
            _BLOCKED[entry] = (str(value[0]), float(value[1]))
    for key, target in (stored.get("aliases") or {}).items():
        old, new = _split_key(key), _split_key(target)
        if old and new:
            _ALIASES[old] = new

    live = {}
    for key, until in cooldowns.items():
        entry = _split_key(key)
        if entry and isinstance(until, (int, float)) and until > now:
            live[entry] = float(until)
    return live


def _save_cooldowns():
    now = time.time()
    payload = {
        "cooldowns": {f"{provider}|{model}": until
                      for (provider, model), until in _COOLDOWNS.items() if until > now},
        "blocked": {f"{provider}|{model}": [reason, until]
                    for (provider, model), (reason, until) in _BLOCKED.items() if until > now},
        "aliases": {f"{old[0]}|{old[1]}": f"{new[0]}|{new[1]}" for old, new in _ALIASES.items()},
    }
    try:
        os.makedirs(os.path.dirname(_COOLDOWN_PATH), exist_ok=True)
        with open(_COOLDOWN_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        pass


class ProviderError(RuntimeError):
    """An API failure the router can reason about instead of just showing."""

    def __init__(self, message, status=None, kind="other", retry_after=None):
        super().__init__(message)
        self.status = status
        self.kind = kind            # quota | capability | auth | other
        self.retry_after = retry_after


def _parse_retry_seconds(detail):
    """Read Groq's 'Please try again in 22m17.04s' as a number of seconds."""
    marker = detail.find("try again in")
    if marker < 0:
        return None
    total = 0.0
    for amount, unit in _RETRY_RE.findall(detail[marker:marker + 60]):
        try:
            total += float(amount) * _UNIT_SECONDS[unit]
        except (ValueError, KeyError):
            continue
    return total or None


# Wording providers use when a model is outside the account's plan. These look
# like auth failures by status code, but waiting never fixes them. Deliberately
# not "billing" or "upgrade": Groq's ordinary daily-limit 429 ends with "Upgrade
# to Dev Tier ... /settings/billing", and that one DOES clear by waiting.
_PLAN_PHRASES = ("subscription tier", "not available in your", "payment required")
# Wording for a model id the provider no longer recognises.
_GONE_PHRASES = ("model_not_found", "does not exist", "invalid model", "not found",
                 "no longer available", "decommissioned")


def _retry_after_header(headers):
    try:
        return float(headers.get("retry-after", "")) or None
    except ValueError:
        return None


# Gemini states its wait as `"retryDelay": "37s"` in the body. Missing it meant a
# per-minute limit got the 15-minute default, idling the most accurate model.
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"')


def _retry_delay_field(detail):
    match = _RETRY_DELAY_RE.search(detail)
    return float(match.group(1)) if match else None


def _classify_http_error(label, status, detail, headers=None):
    """Turn an HTTP failure into something the chain can act on.

    The status code alone misleads. Mistral answers a plan with zero allowance
    with a 429 and a limit header of "0", and a model outside the plan with a 403
    - neither is a rate limit or a bad key, and waiting fixes neither.
    """
    text = detail.lower()
    headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    retry_after = (_parse_retry_seconds(detail) or _retry_delay_field(detail)
                   or _retry_after_header(headers))
    zero_allowance = any(key.startswith("x-ratelimit-limit") and value.strip() == "0"
                         for key, value in headers.items())

    rate_limited = status in (429, 413) or "rate_limit" in text or "resource_exhausted" in text

    if status == 402 or zero_allowance:
        kind = "plan"
    elif not rate_limited and any(phrase in text for phrase in _PLAN_PHRASES):
        kind = "plan"
    elif rate_limited:
        kind = "quota"
        if "perday" in text:
            # Gemini reports a 7s retryDelay even for a per-DAY quota, which would
            # send the chain straight back into the same wall.
            retry_after = _DAILY_COOLDOWN
        elif retry_after is None:
            # A per-minute window resets in a minute, not fifteen.
            per_minute = "perminute" in text or any("minute" in key for key in headers)
            retry_after = 60 if per_minute else _DEFAULT_COOLDOWN
    elif status in (401, 403):
        kind = "auth"
    elif status == 404 or (status == 400 and any(phrase in text for phrase in _GONE_PHRASES)):
        kind = "gone"
    elif status == 400 and ("must be a string" in text or "image" in text):
        kind = "capability"
    else:
        kind = "other"

    return ProviderError(f"{label} API error {status}: {detail[:300]}",
                         status=status, kind=kind, retry_after=retry_after)


def _cool_down(entry, seconds):
    _COOLDOWNS[entry] = time.time() + max(30.0, min(float(seconds), _MAX_COOLDOWN))
    _save_cooldowns()


def _block(entry, reason):
    """Record a refusal that waiting will not fix; rechecked after a day."""
    _BLOCKED[entry] = (reason, time.time() + _BLOCK_RECHECK)
    _save_cooldowns()


# -- Renamed models ----------------------------------------------------------
# Providers retire model ids with every release: Groq replaced qwen/qwen3.6-27b
# with qwen/qwen3.8-27b overnight, and every screenshot then failed with "model
# unavailable". A 404 now triggers a look at the provider's current catalogue for
# the newest model of the same family, and the rename is remembered.
_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_CATALOGUE_TTL = 600
_CATALOGUES = {}         # provider -> (fetched_at, [model ids])


def _family_regex(model):
    """qwen/qwen3.6-27b -> a pattern matching qwen/qwen<any version>-27b.

    Only dotted versions vary, so the size suffix (27b) and variant words
    (flash, lite) stay fixed - a missing 27b model never becomes a 4b one.
    """
    parts = _VERSION_RE.split(model)
    if len(parts) == 1:
        return None                      # nothing versioned to follow
    pattern = "".join(re.escape(part) if index % 2 == 0 else r"(\d+(?:\.\d+)*)"
                      for index, part in enumerate(parts))
    return re.compile("^" + pattern + "$")


def _version_key(model):
    return [tuple(int(piece) for piece in version.split("."))
            for version in _VERSION_RE.findall(model)]


def _gemini_catalogue():
    url = ("https://generativelanguage.googleapis.com/v1beta/models"
           f"?key={GEMINI_API_KEY}&pageSize=200")
    with urllib.request.urlopen(url, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    return [entry["name"].split("/", 1)[-1] for entry in body.get("models", [])
            if "generateContent" in entry.get("supportedGenerationMethods", [])]


def _catalogue(provider):
    """Model ids a provider offers right now, cached for ten minutes."""
    cached = _CATALOGUES.get(provider)
    if cached is not None and time.time() - cached[0] < _CATALOGUE_TTL:
        return cached[1]
    spec = PROVIDERS.get(provider) or {}
    try:
        if spec.get("metering") == "local":
            models = local_models(provider)
        elif spec.get("kind") == "gemini":
            models = _gemini_catalogue()
        else:
            models = list_provider_models(provider)
    except Exception:
        return []
    _CATALOGUES[provider] = (time.time(), models)
    return models


def _find_successor(entry):
    """The model that replaced a retired one, or None."""
    provider, model = entry
    available = [name for name in _catalogue(provider) if name != model]
    if not available:
        return None
    if (PROVIDERS.get(provider) or {}).get("metering") == "local":
        # Local names are not versioned families; use the best model pulled.
        for name in _LOCAL_PREFERENCE:
            if name in available:
                return (provider, name)
        return (provider, available[0])
    family = _family_regex(model)
    if family is None:
        return None
    candidates = [name for name in available if family.match(name)]
    return (provider, max(candidates, key=_version_key)) if candidates else None


def _adopt_successor(old, new):
    """Swap a retired model for its replacement everywhere, and remember it."""
    global PINNED_MODEL
    for chain in (TEXT_CHAIN, VISION_CHAIN):
        if old in chain:
            index = chain.index(old)
            chain.remove(old)
            if new not in chain:
                chain.insert(index, new)
    if PINNED_MODEL == old:
        PINNED_MODEL = new
    _ALIASES[old] = new
    _COOLDOWNS.pop(old, None)
    _save_cooldowns()


_COOLDOWNS.update(_load_cooldowns())
# Renames learned in earlier sessions still apply, even though the defaults and
# env overrides above may still name the retired model.
for _old, _new in list(_ALIASES.items()):
    _adopt_successor(_old, _new)


def _entry_state(entry, use_vision):
    """Return (usable, reason) for one chain entry."""
    provider, _model = entry
    spec = PROVIDERS.get(provider)
    if spec is None:
        return False, "unknown provider"
    if spec.get("metering") == "local":
        return _local_server_state(provider)

    key = provider_key(provider)
    if not key:
        return False, f"set {spec['key_name']}"
    # A key with a backslash or a space in it is a copy-paste accident (a path
    # glued to the front, a stray quote). Saying so beats a bare 401 later.
    if any(character.isspace() for character in key) or "\\" in key or "/" in key.split(":")[0][:8]:
        return False, f"{spec['key_name']} looks malformed"
    if spec.get("kind") == "ocr" and not OCR_SPACE_API_KEY:
        return False, "set OCR_SPACE_API_KEY"
    blocked = _BLOCKED.get(entry)
    if blocked is not None:
        if time.time() < blocked[1]:
            return False, blocked[0]
        del _BLOCKED[entry]              # a day has passed - give it another try
    if use_vision and entry in _NO_VISION:
        return False, "cannot read images"
    until = _COOLDOWNS.get(entry)
    if until and time.time() < until:
        remaining = int(until - time.time())
        return False, f"quota, {remaining // 60}m {remaining % 60}s left"
    return True, ""


def chain_for(use_vision):
    """The models that may be tried, in order.

    Pinned means pinned: exactly one model, and no silent fallback to another.
    If you chose a model, a wrong or slow answer from a different one is worse
    than an error saying yours could not run.
    """
    if PINNED_MODEL is not None:
        return [PINNED_MODEL]

    chain = list(VISION_CHAIN if use_vision else TEXT_CHAIN)
    if ACTIVE_PROVIDER == "gemini":
        # Stable sort: keeps chain order within each provider.
        chain.sort(key=lambda entry: 0 if entry[0] == "gemini" else 1)
    return chain


class NetworkError(RuntimeError):
    """The connection is down. No model is at fault, so none gets a cooldown."""


_NETWORK_RETRIES = 2
_NETWORK_RETRY_DELAY = 1.5
_NETWORK_MESSAGE = (
    "No internet connection - the API hosts could not be reached.\n"
    "Check your network and ask again. No quota was used, and no model was "
    "marked as unavailable."
)


def _plan_reason(provider, error):
    if error.status == 402:
        return f"needs billing at {provider.title()} (HTTP 402)"
    return f"not in your {provider.title()} plan"


def _note_failure(entry, error, use_vision, skipped):
    """Record why a model refused, in words, and how long to leave it alone."""
    provider = entry[0]
    if error.kind == "quota":
        wait = int(error.retry_after or _DEFAULT_COOLDOWN)
        detail = f"out of quota for {wait // 60}m {wait % 60}s" if wait < 3600 else "daily quota used up"
        _cool_down(entry, error.retry_after or _DEFAULT_COOLDOWN)
    elif error.kind == "plan":
        detail = _plan_reason(provider, error)
        _block(entry, detail)
    elif error.kind == "gone":
        detail = f"no longer offered by {provider.title()}"
        _block(entry, detail)
    elif error.kind == "capability":
        if use_vision:
            detail = "cannot read images"
            _NO_VISION.add(entry)
        else:
            detail = "model unavailable"
            _cool_down(entry, _DEFAULT_COOLDOWN)
    elif error.kind == "auth":
        detail = f"{provider.title()} rejected the API key"
        _cool_down(entry, _MAX_COOLDOWN)
    elif error.kind == "ocr":
        # The OCR step failed, not the model. An image with no text in it says
        # nothing about the next screenshot, so it gets no cooldown.
        detail = str(error)
        if error.retry_after:
            _cool_down(entry, error.retry_after)
    else:
        detail = str(error).split(":")[0].strip().lower() or "failed"
        _cool_down(entry, 60)
    skipped.append(f"{entry[1]}: {detail}")


def _ask_one(entry, history, use_vision, skipped, on_step):
    """Ask one model. Returns (reply, entry_used), or (None, entry) to move on.

    A dropped connection is retried here rather than being blamed on the model:
    walking the rest of the chain during an outage just repeats the same failure
    and puts healthy models on cooldown. A retired model is swapped for its
    successor and retried once, so a provider's rename costs one request, not a
    failed question.
    """
    renamed = False
    attempt = 0
    while True:
        provider, model = entry
        if on_step is not None:
            on_step(provider, model)
        try:
            # A text-only model (one that is not in the Watch chain) is only asked
            # about a screenshot when it is pinned. Sending it the image is a
            # guaranteed 400, so it gets the OCR text instead.
            text_only = use_vision and entry not in VISION_CHAIN
            return chat_completion(_ocr_history(history) if text_only else history,
                                   model, provider), entry
        except ProviderError as error:
            if error.kind == "gone" and not renamed:
                successor = _find_successor(entry)
                if successor is not None:
                    skipped.append(f"{model}: renamed by {provider.title()} to {successor[1]}")
                    _adopt_successor(entry, successor)
                    entry, renamed = successor, True
                    continue
            if error.kind != "network":
                _note_failure(entry, error, use_vision, skipped)
                return None, entry
            if attempt < _NETWORK_RETRIES:
                attempt += 1
                time.sleep(_NETWORK_RETRY_DELAY)
                continue
            raise NetworkError(_NETWORK_MESSAGE) from error
        except Exception as error:          # unexpected: let the next model try
            skipped.append(f"{model}: {error}")
            _cool_down(entry, 60)
            return None, entry


_UNFIXABLE_BY_WAITING = ("malformed", "not running", "unknown provider", "needs billing",
                         "not in your", "no longer offered")


def _needs_configuration(reason):
    """A reason waiting will not fix: no key, a bad key, a plan, a retired model.

    The menu greys these out instead of letting the user pin a dead end.
    """
    return reason.startswith("set ") or any(marker in reason for marker in _UNFIXABLE_BY_WAITING)


def _all_unavailable_message(skipped, chain):
    # Only count cooldowns on the models this request actually tried. Reporting the
    # soonest reset across every provider told the user to wait five hours when the
    # real problem was an unset API key.
    now = time.time()
    soonest = min((_COOLDOWNS[entry] for entry in chain
                   if entry in _COOLDOWNS and _COOLDOWNS[entry] > now), default=None)
    if PINNED_MODEL is not None:
        lines = [f"{PINNED_MODEL[1]} could not answer, and it is pinned.",
                 "Pick Auto from the menu to let other models take over."]
    else:
        lines = ["No model could answer right now."]
    if soonest is not None:
        wait = int(soonest - time.time())
        lines.append(f"Quota frees up in about {wait // 60}m {wait % 60}s.")
    lines.extend("  " + note for note in skipped)
    return "\n".join(lines)


def dispatch_chat(history, use_vision, on_step=None):
    """Ask each model in turn until one answers.

    Returns (reply, provider, model, skipped) - `skipped` explains which models
    were passed over, so the UI can say why the answer came from where it did.
    Raises NetworkError if the connection is down, which is not a model problem.
    """
    skipped = []
    chain = chain_for(use_vision)
    for entry in chain:
        usable, reason = _entry_state(entry, use_vision)
        if not usable:
            skipped.append(f"{entry[1]}: {reason}")
            continue

        reply, used = _ask_one(entry, history, use_vision, skipped, on_step)
        if reply is not None:
            return reply, used[0], used[1], skipped

    raise RuntimeError(_all_unavailable_message(skipped, chain))


def _call_ollama_native(history, model, spec):
    """Send a local request through Ollama's own API, never its OpenAI shim.

    The shim fails in two ways that only show up on real questions:
    - it accepts an `image_url` part and silently drops it, so the model says it
      cannot see any image. Native /api/chat takes images as bare base64 strings.
    - it cannot set the context window, and Ollama defaults every model to 4096
      tokens. A thinking model fills that with reasoning and is cut off before it
      writes an answer - measured: 3,405 tokens of thinking, zero of answer.
    """
    messages = [{"role": "system", "content": spec.get("system_prompt") or SYSTEM_PROMPT}]
    for message in history:
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(part.get("text", "") for part in content
                             if isinstance(part, dict) and part.get("type") == "text")
            images = [part["image_url"]["url"].split(",", 1)[-1] for part in content
                      if isinstance(part, dict) and part.get("type") == "image_url"]
            entry = {"role": message["role"], "content": text}
            if images:
                entry["images"] = images
            messages.append(entry)
        else:
            messages.append({"role": message["role"], "content": content})

    base = provider_endpoint("ollama").split("/v1/")[0]
    payload = {"model": model, "stream": False, "messages": messages,
               "think": spec.get("think", True),
               "options": {"temperature": 0,
                           "num_predict": spec.get("max_tokens", 4096),
                           "num_ctx": spec.get("num_ctx", 16384)}}
    request = urllib.request.Request(f"{base}/api/chat",
                                     data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(
                request, timeout=spec.get("timeout", REQUEST_TIMEOUT_SECONDS)) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = (body.get("message") or {}).get("content") or ""
        reply = _answer_first(_strip_think(content) or content.strip())
        if body.get("done_reason") == "length":
            reply = _TRUNCATED_NOTE + "\n\n" + reply if reply else _TRUNCATED_NOTE
        return reply
    except urllib.error.HTTPError as error:
        raise _classify_http_error("Ollama", error.code,
                                   error.read().decode("utf-8", "replace"), error.headers)
    except urllib.error.URLError as error:
        slow = isinstance(error.reason, (TimeoutError, socket.timeout))
        raise ProviderError(f"{'Timed out' if slow else 'Network error'}: {error.reason}",
                            kind="other" if slow else "network")
    except (TimeoutError, socket.timeout) as error:
        raise ProviderError(f"Timed out: {error}", kind="other")


def _has_image(history):
    return any(isinstance(message.get("content"), list)
               and any(isinstance(part, dict) and part.get("type") == "image_url"
                       for part in message["content"])
               for message in history)


def chat_completion(history, model, provider):
    """Send one request to whichever provider the chain picked."""
    spec = PROVIDERS.get(provider) or {}
    if spec.get("kind") == "gemini":
        return _call_gemini_api(history, model)
    if spec.get("kind") == "ocr":
        return _call_ocr_groq(history, model)
    # Local models always go through Ollama's own API: see _call_ollama_native.
    if spec.get("metering") == "local":
        return _call_ollama_native(history, model, spec)
    return _call_openai_compatible(history, model, provider)


def _fit_for_ocr(data_url):
    """Return the image as a data URL small enough for OCR.space's free plan."""
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    if len(raw) <= OCR_MAX_FILE_BYTES:
        return data_url
    if not _PIL_OK:
        raise ProviderError("screenshot is over OCR.space's 1 MB limit", kind="ocr")

    # Greyscale PNG first: it keeps glyph edges lossless and is usually enough
    # for a screenshot. JPEG and then a smaller image only if it is not.
    image = Image.open(io.BytesIO(raw)).convert("L")
    resample = getattr(Image, "Resampling", Image).LANCZOS
    while True:
        for mime, options in (("png", {"format": "PNG", "optimize": True}),
                              ("jpeg", {"format": "JPEG", "quality": 90}),
                              ("jpeg", {"format": "JPEG", "quality": 75})):
            buffer = io.BytesIO()
            image.save(buffer, **options)
            if buffer.tell() <= OCR_MAX_FILE_BYTES:
                return f"data:image/{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"
        width, height = image.size
        image = image.resize((max(1, int(width * 0.8)), max(1, int(height * 0.8))), resample)


def _ocr_space_error(message, status=None):
    """Classify an OCR.space refusal. All of them are kind "ocr": the Groq model
    behind this entry is not at fault, so its own quota state is left alone."""
    text = message.lower()
    if "api key" in text or "apikey" in text or status == 401:
        return ProviderError("OCR.space rejected OCR_SPACE_API_KEY", status=status,
                             kind="ocr", retry_after=300)
    if "size" not in text and (status in (403, 429) or "times within" in text
                               or "rate limit" in text or "quota" in text):
        return ProviderError("OCR.space request limit reached", status=status,
                             kind="ocr", retry_after=_DAILY_COOLDOWN)
    return ProviderError(f"OCR.space could not read the image ({message[:120].strip()})",
                         status=status, kind="ocr")


_OCR_CACHE = {}          # hash of the image -> text, so a second model does not pay for OCR again


def _ocr_space(data_url):
    """Read the text in one image with OCR.space. Returns "" if it found none."""
    cache_key = hash(data_url)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]
    if not OCR_SPACE_API_KEY:
        raise ProviderError("OCR_SPACE_API_KEY is not set, so the screenshot cannot be read",
                            kind="ocr")

    fields = {
        "base64Image": _fit_for_ocr(data_url),
        "language": OCR_SPACE_LANGUAGE,
        "OCREngine": OCR_SPACE_ENGINE,
        "isOverlayRequired": "false",
        "scale": "true",
        # Keeps each line of the screen on its own line, so answer options and
        # code do not run together.
        "isTable": "true",
    }
    request = urllib.request.Request(
        OCR_SPACE_ENDPOINT, data=urllib.parse.urlencode(fields).encode("ascii"), method="POST")
    request.add_header("apikey", OCR_SPACE_API_KEY)
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    request.add_header("User-Agent", USER_AGENT)

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        raise _ocr_space_error(error.read().decode("utf-8", "replace"), error.code)
    except urllib.error.URLError as error:
        slow = isinstance(error.reason, (TimeoutError, socket.timeout))
        raise ProviderError(f"OCR.space {'timed out' if slow else 'network error'}: {error.reason}",
                            kind="ocr" if slow else "network")
    except (TimeoutError, socket.timeout):
        raise ProviderError("OCR.space timed out", kind="ocr")
    except ConnectionError as error:
        raise ProviderError(f"Network error: {error}", kind="network")
    except ValueError:
        raise ProviderError("OCR.space sent an unreadable response", kind="ocr")

    # A refused request can come back as a bare JSON string instead of an object.
    if not isinstance(body, dict):
        raise _ocr_space_error(str(body))
    if body.get("IsErroredOnProcessing"):
        message = body.get("ErrorMessage") or body.get("ErrorDetails") or "unknown error"
        if isinstance(message, list):
            message = " ".join(str(part) for part in message)
        raise _ocr_space_error(str(message))

    text = "\n".join((page.get("ParsedText") or "") for page in body.get("ParsedResults") or []
                     if isinstance(page, dict))
    text = "\n".join(line.rstrip() for line in text.replace("\r", "").split("\n")).strip()
    if len(_OCR_CACHE) >= 8:
        _OCR_CACHE.clear()
    _OCR_CACHE[cache_key] = text
    return text


_OCR_NOTE = (
    "[No image is attached. The screenshot was converted to text by OCR and that "
    "text is below - treat it as what the screenshot shows. OCR can misread single "
    "characters (0/O, 1/l/I, missing symbols) and drops pictures and diagrams. If "
    "the text is too garbled to answer, or the question depends on a figure that is "
    "not here, say so instead of guessing.]"
)


def _ocr_history(history):
    """Replace every screenshot in the conversation with the text OCR read in it."""
    converted = []
    for message in history:
        content = message.get("content")
        if not isinstance(content, list):
            converted.append(message)
            continue
        typed = [part.get("text", "") for part in content
                 if isinstance(part, dict) and part.get("type") == "text"]
        pages = [_ocr_space(part["image_url"]["url"]) for part in content
                 if isinstance(part, dict) and part.get("type") == "image_url"]
        if pages:
            read = "\n\n".join(page for page in pages if page)
            if len(read) < OCR_MIN_CHARS:
                raise ProviderError("OCR found no readable text in the screenshot", kind="ocr")
            typed += [_OCR_NOTE, "--- Screenshot text (OCR) ---\n" + read[:MAX_EXTRACTED_CHARS]]
        converted.append({"role": message["role"],
                          "content": "\n\n".join(part for part in typed if part)})
    return converted


def _call_ocr_groq(history, model):
    """Answer a screenshot without a vision model: OCR.space reads it, Groq answers."""
    return _call_openai_compatible(_ocr_history(history), model, OCR_PROVIDER)


def _call_openai_compatible(history, model, provider="groq"):
    """Call any OpenAI chat-completions API (Groq, Cerebras, OpenRouter, ...)."""
    spec = PROVIDERS.get(provider) or {}
    key = provider_key(provider)
    if not key:
        raise ProviderError(
            f"{spec.get('key_name', provider.upper() + '_API_KEY')} is not set. "
            f"Paste it into API_KEYS in overlay_alert.py and restart.",
            kind="auth",
        )

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": spec.get("system_prompt") or SYSTEM_PROMPT}] + history,
        "stream": False,
        # These questions have exactly one correct answer, so sampling noise is
        # pure downside.
        "temperature": 0,
        "top_p": 1,
        # Too low and a reasoning model is cut off mid-derivation and never emits
        # its answer at all - Groq's own default of 2048 does exactly that. The
        # ceiling is per provider: see PROVIDERS.
        "max_tokens": spec.get("max_tokens", 8192),
    }
    request = urllib.request.Request(
        provider_endpoint(provider),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", f"Bearer {key}")
    for header, value in spec.get("headers", {}).items():
        request.add_header(header, value)

    try:
        with urllib.request.urlopen(
                request, timeout=spec.get("timeout", REQUEST_TIMEOUT_SECONDS)) as response:
            body = json.loads(response.read().decode("utf-8"))
            choice = body["choices"][0]
            message = choice["message"]
            # Some reasoning models leave content empty and put everything in
            # "reasoning" instead.
            content = message.get("content") or message.get("reasoning") or ""
            reply = _answer_first(_strip_think(content) or content.strip())
            if choice.get("finish_reason") == "length":
                reply = _TRUNCATED_NOTE + "\n\n" + reply if reply else _TRUNCATED_NOTE
            return reply
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise _classify_http_error(provider.title(), error.code, detail, error.headers)
    except urllib.error.URLError as error:
        # A name-resolution failure means the connection itself is down, so the
        # chain should stop. A read timeout means only THIS provider is slow -
        # blaming the network there would abort a chain that still has working
        # models in it.
        slow = isinstance(error.reason, (TimeoutError, socket.timeout))
        raise ProviderError(f"{'Timed out' if slow else 'Network error'}: {error.reason}",
                            kind="other" if slow else "network")
    except (TimeoutError, socket.timeout) as error:
        raise ProviderError(f"Timed out: {error}", kind="other")
    except ConnectionError as error:
        raise ProviderError(f"Network error: {error}", kind="network")
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unexpected API response: {error}")


def _call_gemini_api(history, model):
    """Call the Google Gemini GenAI REST API."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Paste it into API_KEYS in overlay_alert.py and restart."
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    contents = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        parts = []
        if isinstance(msg["content"], str):
            parts.append({"text": msg["content"]})
        elif isinstance(msg["content"], list):
            for item in msg["content"]:
                if item.get("type") == "text":
                    parts.append({"text": item.get("text")})
                elif item.get("type") == "image_url":
                    data_uri = item["image_url"]["url"]
                    mime = data_uri.split(";")[0].split(":")[1]
                    b64 = data_uri.split(",")[1]
                    parts.append({
                        "inline_data": {
                            "mime_type": mime,
                            "data": b64
                        }
                    })
        contents.append({"role": role, "parts": parts})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        # The REST API reads "generationConfig" - "config" is the Python SDK's name
        # and is not recognised here. thinkingBudget -1 means "think as long as the
        # question needs"; 0 disables reasoning and wrecks aptitude accuracy.
        "generationConfig": {
            "temperature": 0,
            "topP": 1,
            "maxOutputTokens": 8192,
            "thinkingConfig": {
                "thinkingBudget": -1
            },
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
            # With thinking on, the answer is not always parts[0]: the model can
            # emit thought parts first. Join every non-thought text part.
            candidate = body["candidates"][0]
            parts = candidate["content"]["parts"]
            content = "".join(
                part.get("text", "") for part in parts if not part.get("thought")
            )
            reply = _answer_first(_strip_think(content) or content.strip())
            if candidate.get("finishReason") == "MAX_TOKENS":
                reply = _TRUNCATED_NOTE + "\n\n" + reply if reply else _TRUNCATED_NOTE
            return reply
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise _classify_http_error("Gemini", error.code, detail, error.headers)
    except urllib.error.URLError as error:
        # A name-resolution failure means the connection itself is down, so the
        # chain should stop. A read timeout means only THIS provider is slow -
        # blaming the network there would abort a chain that still has working
        # models in it.
        slow = isinstance(error.reason, (TimeoutError, socket.timeout))
        raise ProviderError(f"{'Timed out' if slow else 'Network error'}: {error.reason}",
                            kind="other" if slow else "network")
    except (TimeoutError, socket.timeout) as error:
        raise ProviderError(f"Timed out: {error}", kind="other")
    except ConnectionError as error:
        raise ProviderError(f"Network error: {error}", kind="network")
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unexpected API response: {error}")


class GroqOverlay(tk.Tk):
    """Background app: a global hotkey summons a full-screen Groq chat overlay."""

    def __init__(self):
        super().__init__()
        self.withdraw()  # background app - only the overlay is ever shown
        self.title(APP_TITLE)

        # Hide the Python console window from taskbar/screen
        _hide_console_window()
        # Hide the root Tk window from taskbar
        self.after(10, lambda: _hide_tk_from_taskbar(self))

        self._ui_queue = queue.Queue()   # callables marshalled to the Tk thread
        self._history = []               # conversation context
        self._overlay_visible = False
        self._waiting = False            # a chat request is in flight
        self._pending_image = None       # data URL of a screenshot to send next
        self._vision_mode = False        # latched once any image enters the chat
        self._attach_chip = None         # the "screenshot attached" UI chip

        # Chat-hotkey state (mutated from listener / timer threads).
        self._trigger_down = False
        self._hold_timer = None
        self._close_presses = []

        self._build_overlay()
        self._start_listener()
        self.after(40, self._pump)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    # -- UI construction ----------------------------------------------------
    def _build_overlay(self):
        overlay = tk.Toplevel(self)
        overlay.withdraw()
        overlay.title(APP_TITLE)
        overlay.configure(bg=COLOR_BACKDROP)
        # DO NOT use overrideredirect(True) or -alpha:
        # they set WS_EX_LAYERED which makes WDA_EXCLUDEFROMCAPTURE fail.
        # Instead we strip the title bar / borders via Win32 style flags
        # in show_overlay() after the HWND is created.
        overlay.attributes("-topmost", True)
        overlay.bind("<Escape>", lambda _event: self.hide_overlay())
        self.overlay = overlay
        self._wda_applied = False

        # Immediately hide from taskbar while still withdrawn
        _hide_tk_from_taskbar(overlay)

        card = tk.Frame(overlay, bg=COLOR_CARD)
        card.place(x=0, y=0, relwidth=1.0, relheight=1.0)  # full screen
        self._card = card

        header = tk.Frame(card, bg=COLOR_CARD, padx=20, pady=14)
        header.pack(fill="x")
        self.provider_btn = tk.Button(
            header, text="Groq ▾", font=("Segoe UI", 16, "bold"),
            fg=COLOR_TEXT, bg=COLOR_CARD, activebackground=COLOR_CARD, activeforeground=COLOR_TEXT,
            relief="flat", borderwidth=0, cursor="hand2", command=self._open_model_menu
        )
        self.provider_btn.pack(side="left")
        self.model_label = tk.Label(header, text="", font=("Segoe UI", 9),
                                    fg=COLOR_MUTED, bg=COLOR_CARD)
        self.model_label.pack(side="left", padx=(10, 0))
        self._refresh_model_label()
        tk.Label(header, text="type  q q q  or Esc  to close", font=("Segoe UI", 9),
                 fg=COLOR_MUTED, bg=COLOR_CARD).pack(side="right")

        body = tk.Frame(card, bg=COLOR_CARD, padx=20)
        body.pack(fill="both", expand=True)

        convo_wrap = tk.Frame(body, bg=COLOR_CONVO)
        convo_wrap.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(convo_wrap)
        scroll.pack(side="right", fill="y")
        self.convo = tk.Text(
            convo_wrap, font=("Segoe UI", 11), bg=COLOR_CONVO, fg=COLOR_BOT,
            wrap="word", relief="flat", padx=16, pady=14, borderwidth=0,
            highlightthickness=0, yscrollcommand=scroll.set, spacing3=4,
        )
        self.convo.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.convo.yview)
        self.convo.tag_configure("user_label", foreground=COLOR_USER, font=("Segoe UI", 9, "bold"), spacing1=8)
        self.convo.tag_configure("user", foreground=COLOR_TEXT)
        self.convo.tag_configure("bot_label", foreground=COLOR_ACCENT, font=("Segoe UI", 9, "bold"), spacing1=8)
        self.convo.tag_configure("bot", foreground=COLOR_BOT)
        self.convo.tag_configure("note", foreground=COLOR_MUTED, font=("Segoe UI", 9, "italic"))
        self.convo.tag_configure("error", foreground=COLOR_ERROR)
        self.convo.config(state="disabled")

        input_outer = tk.Frame(card, bg=COLOR_CARD, padx=20, pady=16)
        input_outer.pack(fill="x")

        self.attach_bar = tk.Frame(input_outer, bg=COLOR_CARD)  # holds the attachment chip
        self.attach_bar.pack(fill="x")

        input_frame = tk.Frame(input_outer, bg=COLOR_CARD)
        input_frame.pack(fill="x", pady=(6, 0))

        self.send_button = tk.Button(
            input_frame, text="Send", command=self._send, width=9,
            font=("Segoe UI", 11, "bold"), fg="white", bg=COLOR_ACCENT,
            activebackground="#3a78e6", activeforeground="white",
            relief="flat", borderwidth=0, cursor="hand2",
        )
        self.send_button.pack(side="right", fill="y", padx=(12, 0))

        self.watch_button = tk.Button(
            input_frame, text="Watch", command=self.watch_screen, width=8,
            font=("Segoe UI", 11, "bold"), fg=COLOR_TEXT, bg="#26324a",
            activebackground="#31405e", activeforeground=COLOR_TEXT,
            relief="flat", borderwidth=0, cursor="hand2",
        )
        self.watch_button.pack(side="right", fill="y", padx=(12, 0))

        self.read_button = tk.Button(
            input_frame, text="⚡ Read", command=self.read_active_window, width=8,
            font=("Segoe UI", 11, "bold"), fg=COLOR_TEXT, bg="#26324a",
            activebackground="#31405e", activeforeground=COLOR_TEXT,
            relief="flat", borderwidth=0, cursor="hand2",
        )
        self.read_button.pack(side="right", fill="y", padx=(12, 0))

        self.attach_button = tk.Button(
            input_frame, text="📎", command=self.attach_image, width=3,
            font=("Segoe UI", 13), fg=COLOR_TEXT, bg="#1b2436",
            activebackground="#26324a", activeforeground=COLOR_TEXT,
            relief="flat", borderwidth=0, cursor="hand2",
        )
        self.attach_button.pack(side="right", fill="y", padx=(12, 0))

        self.input_box = tk.Text(
            input_frame, font=("Segoe UI", 13), height=3, bg="#1b2436",
            fg="#ffffff", insertbackground="#ffffff", insertwidth=2,
            selectbackground=COLOR_ACCENT, selectforeground="#ffffff", wrap="word",
            relief="flat", padx=12, pady=10, borderwidth=0, highlightthickness=1,
            highlightbackground="#33415e", highlightcolor=COLOR_ACCENT,
        )
        self.input_box.pack(side="left", fill="both", expand=True)
        self.input_box.bind("<Return>", self._send)
        self.input_box.bind("<Shift-Return>", lambda _event: None)  # allow newline
        self.input_box.bind("<Control-v>", self._on_paste)          # paste a screenshot

        self.status_var = tk.StringVar(value="")
        tk.Label(card, textvariable=self.status_var, font=("Segoe UI", 9),
                 fg=COLOR_MUTED, bg=COLOR_CARD, anchor="w", padx=22).pack(fill="x", pady=(0, 10))

        greeting = ("Ready. Ask me anything.   Attach a screenshot with 📎 or Ctrl+V, "
                    "or click Watch to read your current screen (e.g. a terminal error).")
        if not GROQ_API_KEY and not GEMINI_API_KEY:
            greeting += "   (Heads up: GROQ_API_KEY and GEMINI_API_KEY are not set - see setup notes.)"
        self._append_note(greeting)

    def _refresh_model_label(self, provider=None, model=None):
        """Header shows what answered, or what will be tried next."""
        if PINNED_MODEL is not None:
            self.provider_btn.config(text=f"{PINNED_MODEL[0].title()} \u25be")
            self.model_label.config(text=f"pinned: {PINNED_MODEL[1]}")
            return
        if model:
            self.provider_btn.config(text=f"{provider.title()} \u25be")
            self.model_label.config(text=f"model: {model}")
            return
        upcoming = next((e for e in chain_for(False) if _entry_state(e, False)[0]), None)
        if upcoming is None:
            self.provider_btn.config(text="Auto \u25be")
            self.model_label.config(text="every model is cooling down")
        else:
            self.provider_btn.config(text=f"{upcoming[0].title()} \u25be")
            self.model_label.config(text=f"auto: {upcoming[1]}")

    def _open_model_menu(self):
        """The header dropdown: the whole chain, with each model's quota state."""
        menu = tk.Menu(self, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT,
                       activebackground=COLOR_ACCENT, activeforeground="white",
                       borderwidth=0, font=("Segoe UI", 9))
        menu.add_command(label="Auto - first model with quota left",
                         command=lambda: self._pin_model(None))
        menu.add_separator()

        listed = []
        for entry in VISION_CHAIN + TEXT_CHAIN:
            if entry in listed:
                continue
            listed.append(entry)
            usable, reason = _entry_state(entry, entry in VISION_CHAIN)
            label = f"{'  ' if usable else 'x '}{entry[0]} - {entry[1]}"
            if entry in VISION_CHAIN:
                label += "  [reads images]"
            elif OCR_SPACE_API_KEY:
                label += "  [screenshots via OCR]"
            if not usable:
                label += f"  ({reason})"
            # A model that is merely out of quota can still be pinned - that clears
            # its cooldown and forces a retry. One with no key cannot work at all,
            # so it is greyed out rather than left as a trap.
            menu.add_command(label=label, state="disabled" if _needs_configuration(reason) else "normal",
                             command=lambda e=entry: self._pin_model(e))

        try:
            menu.tk_popup(self.provider_btn.winfo_rootx(),
                          self.provider_btn.winfo_rooty() + self.provider_btn.winfo_height())
        finally:
            menu.grab_release()

    def _pin_model(self, entry):
        """Pin one model, or go back to walking the chain."""
        global PINNED_MODEL, ACTIVE_PROVIDER
        PINNED_MODEL = entry
        if entry is None:
            # No probing here: a health check spends a request per model just to
            # ask whether it is there. Known cooldowns already steer the chain.
            self._set_status("Auto - first model with quota left")
            self._refresh_model_label()
        else:
            usable, reason = _entry_state(entry, entry in VISION_CHAIN)
            if not usable and _needs_configuration(reason):
                PINNED_MODEL = None
                self._set_status(f"Cannot use {entry[1]}: {reason}")
                self._refresh_model_label()
                return
            ACTIVE_PROVIDER = entry[0]
            _COOLDOWNS.pop(entry, None)   # asked for explicitly, so give it a chance
            self._set_status(f"Pinned {entry[1]}")
            self._refresh_model_label()

    # -- Global hotkey listener --------------------------------------------
    def _start_listener(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    @staticmethod
    def _key_char(key):
        try:
            return key.char.lower() if key.char else None
        except AttributeError:
            return None

    def _on_press(self, key):
        if getattr(self, '_suppress_listener', False):
            return
        char = self._key_char(key)
        if char == TRIGGER_KEY:
            if not self._trigger_down:
                self._trigger_down = True
                self._hold_timer = threading.Timer(HOLD_SECONDS, self._hold_elapsed)
                self._hold_timer.daemon = True
                self._hold_timer.start()
        elif char == CLOSE_KEY:
            self._register_close_press()

    def _on_release(self, key):
        if self._key_char(key) == TRIGGER_KEY:
            self._trigger_down = False
            if self._hold_timer is not None:
                self._hold_timer.cancel()
                self._hold_timer = None

    def _hold_elapsed(self):
        if self._trigger_down and not self._overlay_visible:
            self._ui_queue.put(self.show_overlay)

    def _register_close_press(self):
        if not self._overlay_visible:
            return
        now = time.monotonic()
        self._close_presses = [t for t in self._close_presses if now - t <= CLOSE_WINDOW_SECONDS]
        self._close_presses.append(now)
        if len(self._close_presses) >= CLOSE_REPEAT:
            self._close_presses.clear()
            self._ui_queue.put(self.hide_overlay)

    # -- Thread bridge ------------------------------------------------------
    def _pump(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception as error:  # never let the pump loop die
            self._set_status(f"Internal error: {error}")
        finally:
            self.after(40, self._pump)

    # -- Overlay visibility -------------------------------------------------
    def show_overlay(self):
        self._overlay_visible = True
        self._close_presses.clear()
        overlay = self.overlay
        overlay.deiconify()
        overlay.attributes("-topmost", True)
        overlay.geometry(f"{overlay.winfo_screenwidth()}x{overlay.winfo_screenheight()}+0+0")
        overlay.lift()
        overlay.focus_force()
        # Apply borderless style + WDA protection (needs mapped HWND)
        if not self._wda_applied:
            overlay.after(80, self._apply_protection)
        overlay.after(10, self.input_box.focus_force)

    def _apply_protection(self):
        """Make the overlay borderless via Win32 styles and apply WDA."""
        _make_borderless_wda_compatible(self.overlay)
        ok = _apply_wda_protection(self.overlay)
        if ok:
            self._wda_applied = True
            self._set_status("WDA capture protection active.")
        else:
            self._set_status("WDA protection could not be applied.")

    def hide_overlay(self):
        self._overlay_visible = False
        self.overlay.withdraw()

    # -- Chat ---------------------------------------------------------------
    def _send(self, _event=None):
        if self._waiting:
            return "break"
        text = self.input_box.get("1.0", "end-1c").strip()
        if not text and self._pending_image is None:
            return "break"
        self.input_box.delete("1.0", "end")

        if self._pending_image is not None:
            content = []
            if text:
                content.append({"type": "text", "text": text})
            content.append({"type": "image_url", "image_url": {"url": self._pending_image}})
            self._history.append({"role": "user", "content": content})
            self._vision_mode = True
            self._clear_attachment()
            display = f"{text}   📎 screenshot" if text else "📎 screenshot"
        else:
            self._history.append({"role": "user", "content": text})
            display = text

        self._append("You", display, "user")
        self._waiting = True
        self.send_button.config(state="disabled")
        self._set_status("Thinking...")
        threading.Thread(target=self._call_api, daemon=True).start()
        return "break"

    def _call_api(self):
        # Use vision model only if latest message contains an image payload
        use_vision = False
        if self._history:
            last_content = self._history[-1].get("content")
            if isinstance(last_content, list):
                for item in last_content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        use_vision = True
                        break

        # Strip images from older turns to prevent context bloat and cap limits
        filtered_history = []
        for i, msg in enumerate(self._history):
            if i == len(self._history) - 1:
                filtered_history.append(msg)
            else:
                if isinstance(msg["content"], list):
                    text_parts = [p.get("text", "") for p in msg["content"] if isinstance(p, dict) and p.get("type") == "text"]
                    if text_parts:
                        filtered_history.append({"role": msg["role"], "content": "\n".join(text_parts)})
                else:
                    filtered_history.append(msg)

        # Walk the fallback chain: the first model with quota left answers. Groq is
        # tried first (it is the fastest), and the chain continues into Gemini,
        # whose per-model daily budgets are separate from Groq's.
        def announce(provider, model):
            asking = "Reading the screenshot with OCR, then asking" if provider == OCR_PROVIDER else "Asking"
            self._ui_queue.put(lambda: self._set_status(f"{asking} {model}..."))

        try:
            reply, provider, model, skipped = dispatch_chat(
                filtered_history, use_vision, on_step=announce)
        except Exception as error:
            message = str(error)
            self._ui_queue.put(lambda: self._on_error(message))
            return
        self._ui_queue.put(lambda: self._on_reply(reply, provider, model, skipped))

    def _on_reply(self, reply, provider="groq", model="", skipped=()):
        self._history.append({"role": "assistant", "content": reply})
        self._append(model or provider, reply, "bot")
        self._waiting = False
        self._vision_mode = False
        self.send_button.config(state="normal")
        self._refresh_model_label(provider, model)
        # Say so when the chain had to move on, otherwise a slower or weaker
        # answer looks like the app misbehaving.
        self._set_status(f"{len(skipped)} model(s) skipped - answered by {model}" if skipped else "")

    def _on_error(self, message):
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._append("Error", message, "error")
        self._waiting = False
        self.send_button.config(state="normal")
        self._set_status("Request failed. Try again.")

    def _append(self, who, text, role):
        self.convo.config(state="normal")
        self.convo.insert("end", f"{who}\n", (role + "_label",))
        self.convo.insert("end", f"{text}\n", (role,))
        self.convo.config(state="disabled")
        self.convo.see("end")

    def _append_note(self, text):
        self.convo.config(state="normal")
        self.convo.insert("end", f"{text}\n", ("note",))
        self.convo.config(state="disabled")
        self.convo.see("end")

    def _set_status(self, text):
        self.status_var.set(text)

    # -- Screenshot / image attach ------------------------------------------
    def _on_paste(self, _event=None):
        img = self._grab_clipboard_image()
        if img is not None:
            self._attach(img)
            return "break"   # consumed as an image paste
        return None          # otherwise let the Text widget paste clipboard text

    def attach_image(self):
        if not _PIL_OK:
            self._set_status("Install Pillow for screenshots:  pip install pillow")
            return
        img = self._grab_clipboard_image() or self._pick_image_file()
        if img is None:
            self._set_status("No image found. Snip a screenshot (Win+Shift+S), then click 📎 or press Ctrl+V.")
            return
        self._attach(img)

    def _grab_clipboard_image(self):
        if not _PIL_OK:
            return None
        try:
            clip = ImageGrab.grabclipboard()
        except Exception:
            return None
        if isinstance(clip, Image.Image):
            return clip
        if isinstance(clip, list) and clip:  # clipboard held file paths
            try:
                return Image.open(clip[0])
            except Exception:
                return None
        return None

    def _pick_image_file(self):
        from tkinter import filedialog
        self.overlay.attributes("-topmost", False)  # let the dialog come to front
        try:
            path = filedialog.askopenfilename(
                title="Choose an image",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                           ("All files", "*.*")],
            )
        finally:
            self.overlay.attributes("-topmost", True)
        if not path:
            return None
        try:
            return Image.open(path)
        except Exception:
            return None

    def _attach(self, img):
        try:
            self._pending_image = self._encode_image(img)
        except Exception as error:
            self._set_status(f"Could not read image: {error}")
            return
        self._show_attachment()
        self._set_status("Screenshot attached - type a question and press Send.")
        self.input_box.focus_force()

    @staticmethod
    def _encode_image(img):
        img = img.convert("RGB")
        width, height = img.size
        scale = min(1.0, MAX_IMAGE_DIM / max(width, height))
        if scale < 1.0:
            # Use LANCZOS if available, otherwise ANTIALIAS
            resample = getattr(Image, "Resampling", Image).LANCZOS
            img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))), resample)
        # PNG first: lossless glyph edges. JPEG ringing around small text is what
        # makes a model misread a scrambled word or a digit.
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        if len(encoded) <= MAX_BASE64_LENGTH:
            return f"data:image/png;base64,{encoded}"

        for quality in (92, 85):
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            encoded = base64.b64encode(buffer.getvalue()).decode()
            if len(encoded) <= MAX_BASE64_LENGTH:
                break
        return f"data:image/jpeg;base64,{encoded}"

    def _show_attachment(self):
        if self._attach_chip is not None:
            self._attach_chip.destroy()
        chip = tk.Frame(self.attach_bar, bg="#22304a")
        chip.pack(side="left")
        tk.Label(chip, text="📎 screenshot attached", bg="#22304a", fg=COLOR_TEXT,
                 font=("Segoe UI", 9), padx=8, pady=3).pack(side="left")
        tk.Button(chip, text="✕", command=self._clear_attachment, bg="#22304a",
                  fg=COLOR_MUTED, activebackground="#22304a", activeforeground=COLOR_ERROR,
                  relief="flat", borderwidth=0, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self._attach_chip = chip

    def _clear_attachment(self):
        self._pending_image = None
        if self._attach_chip is not None:
            self._attach_chip.destroy()
            self._attach_chip = None

    # -- Watch / Read active window ------------------------------------------
    def read_active_window(self, _event=None):
        """Extract text from active foreground window by reading the clipboard."""
        if self._waiting:
            return
        
        typed = self.input_box.get("1.0", "end-1c").strip()
        self.input_box.delete("1.0", "end")

        # Read the clipboard directly
        text_context = None
        try:
            text_context = self.clipboard_get()
        except Exception:
            pass

        # If clipboard was empty, fall back to basic UIA extraction
        if not text_context or len(text_context.strip()) < 5:
            text_context = _extract_active_window_text()

        # If we still have no text, or just a window title, warn the user
        if not text_context or len(text_context.strip()) < 5 or text_context.startswith("[Active Window:"):
            self._set_status("Please COPY (Ctrl+C) the text first, or use Watch!")
            return

        # Smart analysis prompt that detects question type and answers directly
        read_instruction = (
            "The text below was extracted from my screen. Identify what it is and "
            "DIRECTLY ANSWER it - multiple choice: give the correct option; coding "
            "problem: give the full solution; error or stack trace: root cause plus "
            "exact fix; question of any other kind: answer it. If it contains several "
            "questions, answer every one of them. Do not just summarize what you read."
        )

        # A rule this specific has to sit next to the content. The same instruction
        # in the system prompt gets ignored: a premise plus four options looks so
        # answerable that the model invents the missing question and answers that.
        if looks_incomplete(text_context):
            read_instruction += (
                "\n\nSTOP - the text below has answer options but NO question line; "
                "the screen capture lost it. Do not guess what was asked and do not "
                "answer. Reply exactly: The question text is missing - copy the full "
                "question and try again. Then quote the text you received.")

        if typed:
            full_prompt = f"{read_instruction}\n\nUser's additional instruction: {typed}\n\n--- Extracted Text ---\n{text_context}"
        else:
            full_prompt = f"{read_instruction}\n\n--- Extracted Text ---\n{text_context}"

        self._history.append({"role": "user", "content": full_prompt})
        self._append("You", f"{typed}   ⚡ read" if typed else "⚡ read active window", "user")

        self._waiting = True
        self.send_button.config(state="disabled")
        self._set_status(
            "Options found but no question line - copy the full question"
            if looks_incomplete(text_context) else "Analyzing...")
        threading.Thread(target=self._call_api, daemon=True).start()

    def watch_screen(self, _event=None):
        """Grab whatever is behind the overlay and ask the vision model to read it."""
        if not _PIL_OK:
            self._set_status("Install Pillow to use Watch:  pip install pillow")
            return
        if self._waiting:
            return
        self._set_status("Watching the screen...")
        # Hide the overlay so the capture shows what's behind it
        self.overlay.withdraw()
        self.overlay.update_idletasks()
        self.after(180, self._capture_and_send)

    def _capture_and_send(self):
        try:
            # Capture the primary display for crisp 1:1 text legibility
            image = ImageGrab.grab(all_screens=False)
        except Exception:
            try:
                image = ImageGrab.grab()
            except Exception as error:
                self.show_overlay()
                self._set_status(f"Could not capture screen: {error}")
                return

        self.show_overlay()  # bring assistant back

        try:
            data_url = self._encode_image(image)
        except Exception as error:
            self._set_status(f"Could not process capture: {error}")
            return

        typed = self.input_box.get("1.0", "end-1c").strip()
        self.input_box.delete("1.0", "end")

        watch_instruction = (
            "Read this screenshot of my screen and DIRECTLY ANSWER whatever it "
            "contains.\n\n"
            "First transcribe, character by character, any question text and all "
            "answer options exactly as they appear - scrambled words, code and numbers "
            "must be copied letter for letter, since a single misread character changes "
            "the answer. If a character is genuinely unreadable, say so instead of "
            "guessing.\n\n"
            "Then solve it: multiple choice -> state the correct option; coding problem "
            "-> write the full solution; error or stack trace -> root cause plus the "
            "exact fix; anything else -> answer it directly. If several questions are "
            "visible, answer all of them. Do not merely describe the screenshot."
        )

        question = f"{watch_instruction}\n\nUser note: {typed}" if typed else watch_instruction
        content = [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        self._history.append({"role": "user", "content": content})
        self._vision_mode = True
        self._append("You", f"{typed}   👁 watch screen" if typed else "👁 watch screen", "user")

        self._waiting = True
        self.send_button.config(state="disabled")
        self._set_status("Analyzing screen capture...")
        threading.Thread(target=self._call_api, daemon=True).start()

    # -- Shutdown -----------------------------------------------------------
    def quit_app(self):
        try:
            self._listener.stop()
        except Exception:
            pass
        self.destroy()


def _print_provider_models(provider):
    """`--models <provider>`: list the model ids a provider will accept."""
    if provider not in PROVIDERS:
        print(f"Unknown provider '{provider}'. Known: {', '.join(sorted(PROVIDERS))}")
        return 1
    if not provider_key(provider):
        print(f"{PROVIDERS[provider]['key_name']} is not set.")
        return 1
    try:
        for model in list_provider_models(provider):
            print(model)
    except Exception as error:
        print(f"Could not list models for {provider}: {error}")
        return 1
    return 0


def _print_ocr_text(path):
    """`--ocr <image>`: show what OCR.space reads in an image file."""
    if not OCR_SPACE_API_KEY:
        print("OCR_SPACE_API_KEY is not set.")
        return 1
    mime = "jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "png"
    try:
        with open(path, "rb") as handle:
            data_url = f"data:image/{mime};base64," + base64.b64encode(handle.read()).decode()
        print(_ocr_space(data_url) or "(OCR found no text)")
    except Exception as error:
        print(f"OCR failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--models":
        sys.exit(_print_provider_models(sys.argv[2] if len(sys.argv) > 2 else ""))
    if len(sys.argv) >= 3 and sys.argv[1] == "--ocr":
        sys.exit(_print_ocr_text(sys.argv[2]))
    GroqOverlay().mainloop()
