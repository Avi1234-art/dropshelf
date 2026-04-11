# DropShelf

A free Dropover alternative for macOS. Pure Python/PyObjC — no Xcode or Swift.

## Running & Installing

```bash
# Run directly
python3 dropshelf.py

# Install as .app to /Applications (sets up login item)
bash install.sh

# Remove
bash uninstall.sh
```

After `install.sh`, launch with `open /Applications/DropShelf.app`. The app runs as a menu-bar accessory (no dock icon).

## Project Structure

```
dropshelf.py              # Entry point (calls dropshelf.main)
dropshelf/
  main.py                 # NSApplication setup, activation policy
  app_delegate.py         # Menu bar icon, shake detector, settings menus
  shelf_window.py         # Core shelf: window, layout, drag/drop, animations, toast
  ui_components.py        # NSView subclasses: ShelfItemView, DropTargetView,
                          #   ToastBannerView, MarqueeLabelView, SectionHeaderView, etc.
  constants.py            # All sizing, timing, color constants
  file_utils.py           # Thumbnails (qlmanage), file classification, positioning
  settings.py             # JSON load/save (~/.dropshelf/settings.json)
install.sh / uninstall.sh # App bundle creation and login item setup
build_app_icon.py         # Generates the app icon PNG
build_icns.py             # Converts PNG to .icns for the bundle
app_launcher.c            # Compiled C stub used as the .app executable
```

## Architecture

- **ShelfWindow** (`shelf_window.py`) is the central class. It owns the `NSWindow`, the vibrancy background (`NSVisualEffectView`), the header bar, scroll view, and all item management. It handles drag-and-drop (`_beginDropAnimation`, `_updateDropAnimation`, `_endDropAnimation`), file insertion with animated layout, clear-all with staggered animations, and the toast notification system.

- **Toast system** uses a transparent gutter below the shelf. The main window is `shelf_height + TOAST_GUTTER_HEIGHT` tall. The bg (vibrancy view) is offset upward by the gutter height. The toast view sits in the gutter as a subview of the content view, added *before* the bg so it draws behind it — the shelf's border is always visible on top. Toast position is fixed relative to the window, so it never shifts during resize.

- **ShakeDetector** (`app_delegate.py`) polls cursor position via `NSTimer`. It only triggers during active file drags (checks the drag pasteboard `changeCount` against an idle snapshot). Button-held debounce (150ms) prevents false triggers from clicks.

- **Thumbnails** are loaded asynchronously. `_setup_ui` shows `NSWorkspace.iconForFile_` instantly, then `_load_thumbnail_async` runs `qlmanage` on a background thread and applies the result on the main thread via `performSelectorOnMainThread_`.

## Known Gotchas

- **NSTextField vs NSButton text baselines don't match.** Even with identical y/height/font, the two controls render text at different vertical positions. The header count label was converted to a borderless disabled NSButton to guarantee alignment with the Clear All button. If adding new text to the header, use NSButton for consistency.

- **NSTextField eats width inside badges.** NSTextField has internal cell margins (~3px/side) that reduce the actual text drawing area. Size badge padding must account for this (currently `text_size.width + 20`). If badge text appears truncated, increase padding — don't just match the measured text width.

- **`_endDropAnimation(restore_layout=False)`** skips the window height restoration and content frame animation. Used in `performDragOperation_` to avoid a visible double-resize (shrink to pre-drop height, then re-expand for new items). Other callers (draggingExited_, clear_all) should use the default `restore_layout=True`.

## Key Patterns

- **Generation counters** (`_toast_generation`, `_show_hide_generation`) invalidate stale animation callbacks. Every show/hide/toast bumps the counter; the callback checks it before acting.

- **ActionProxy** (in `ui_components.py`) is an `NSObject` subclass that wraps a Python callable, used as the target for `NSTimer`, `NSButton`, and `NSMenuItem` actions. Store proxies in instance variables to prevent garbage collection.

- **`_apply_window_height(total_height, animated=False)`** is the single method that resizes the window, bg, header, and scroll view. All callers pass the *shelf* height; the method adds `TOAST_GUTTER_HEIGHT` internally for the window frame.

- **`_pre_drop_window_height`** stores the shelf height (window height minus gutter) so `_endDropAnimation` can restore it correctly.

## Settings

Stored at `~/.dropshelf/settings.json`. Keys: `position` (top-right, top-left, bottom-right, bottom-left, near-cursor), `sensitivity` (low, medium, high), `auto_organize` (bool).

## Testing Changes

No test suite. After modifying code:
1. `python3 -m py_compile dropshelf/shelf_window.py` (and any other changed file)
2. `bash install.sh && open /Applications/DropShelf.app`
3. Manually verify: drop files, clear all, check toast, resize, shake detection
