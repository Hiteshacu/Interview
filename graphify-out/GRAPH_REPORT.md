# Graph Report - C:\Users\HP\Downloads\Advance_breakdown-main\Advance_breakdown-main  (2026-04-27)

## Corpus Check
- 5 files · ~4,571 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 78 nodes · 108 edges · 11 communities detected
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 10 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]

## God Nodes (most connected - your core abstractions)
1. `OverlayWindow` - 16 edges
2. `MainWindow` - 12 edges
3. `GlobalKeyboardHook` - 10 edges
4. `OverlayWindow` - 10 edges
5. `KeyboardMonitor` - 10 edges
6. `main()` - 4 edges
7. `App` - 2 edges
8. `OverlayAlert` - 1 edges
9. `OverlayAlert` - 1 edges
10. `OverlayAlert` - 1 edges

## Surprising Connections (you probably didn't know these)
- `MainWindow` --inherits--> `Window`  [EXTRACTED]
  C:\Users\HP\Downloads\Advance_breakdown-main\Advance_breakdown-main\MainWindow.xaml.cs →   _Bridges community 1 → community 3_
- `main()` --calls--> `OverlayWindow`  [EXTRACTED]
  C:\Users\HP\Downloads\Advance_breakdown-main\Advance_breakdown-main\overlay_alert.py → C:\Users\HP\Downloads\Advance_breakdown-main\Advance_breakdown-main\overlay_alert.py  _Bridges community 4 → community 2_

## Communities

### Community 0 - "Community 0"
Cohesion: 0.2
Nodes (3): GlobalKeyboardHook, OverlayAlert, IDisposable

### Community 1 - "Community 1"
Cohesion: 0.21
Nodes (2): MainWindow, OverlayAlert

### Community 2 - "Community 2"
Cohesion: 0.18
Nodes (6): KeyboardMonitor, main(), overlay_alert.py — ADVANCED Cybersecurity Demo Overlay =========================, Automatically type the overlay content character by character - BYPASS COPY/PAST, Global keyboard hook with cycle support., Trigger auto-typing when [B] held for 0.8 seconds.

### Community 3 - "Community 3"
Cohesion: 0.27
Nodes (3): OverlayAlert, OverlayWindow, Window

### Community 4 - "Community 4"
Cohesion: 0.4
Nodes (3): OverlayWindow, Advanced overlay with multiple bypass techniques., Force window to top - called repeatedly.

### Community 5 - "Community 5"
Cohesion: 0.33
Nodes (2): Select all text in both columns., Show right-click context menu with copy/select options.

### Community 6 - "Community 6"
Cohesion: 0.5
Nodes (3): App, OverlayAlert, Application

### Community 7 - "Community 7"
Cohesion: 0.5
Nodes (2): Split content into two columns., Switch to next alert type.

### Community 8 - "Community 8"
Cohesion: 1.0
Nodes (1): Capture screenshot of the overlay - bypass screenshot detection.

### Community 9 - "Community 9"
Cohesion: 1.0
Nodes (1): Copy selected text or all content to clipboard.

### Community 10 - "Community 10"
Cohesion: 1.0
Nodes (1): Save overlay content to file.

## Knowledge Gaps
- **17 isolated node(s):** `OverlayAlert`, `OverlayAlert`, `OverlayAlert`, `OverlayAlert`, `overlay_alert.py — ADVANCED Cybersecurity Demo Overlay =========================` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 8`** (2 nodes): `._take_screenshot()`, `Capture screenshot of the overlay - bypass screenshot detection.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 9`** (2 nodes): `._copy_text()`, `Copy selected text or all content to clipboard.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 10`** (2 nodes): `._save_content()`, `Save overlay content to file.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OverlayWindow` connect `Community 4` to `Community 2`, `Community 5`, `Community 7`, `Community 8`, `Community 9`, `Community 10`?**
  _High betweenness centrality (0.433) - this node is a cross-community bridge._
- **Why does `MainWindow` connect `Community 1` to `Community 0`, `Community 3`?**
  _High betweenness centrality (0.255) - this node is a cross-community bridge._
- **Why does `OverlayWindow` connect `Community 3` to `Community 1`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **What connects `OverlayAlert`, `OverlayAlert`, `OverlayAlert` to the rest of the system?**
  _17 weakly-connected nodes found - possible documentation gaps or missing edges._