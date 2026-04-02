# DropShelf

A **free, lightweight Dropover alternative** for macOS. Provides a floating drag-and-drop shelf to temporarily hold files while you work.

## Features

- **Floating shelf window** — always-on-top, translucent, macOS-native vibrancy
- **Drag & drop files** onto the shelf from Finder or any app
- **Click any item** to open it
- **Remove items** individually (×) or clear all at once
- **Menubar icon** to show/hide the shelf
- **Installs as a real `DropShelf.app`** in `/Applications` when writable
- **Auto-launches at login** as a normal macOS login item
- **Zero cost** — no subscription, no App Store purchase

## Requirements

- macOS 11+ (Big Sur or later)
- Python 3.8+
- No Xcode needed!

## Quick Install

Open Terminal and run:

```bash
cd /path/to/dropshelf
chmod +x install.sh
bash install.sh
```

The installer will:
1. Verify Python 3 is available
2. Install the required PyObjC packages
3. Build a proper app icon and `DropShelf.app`
4. Install the app bundle to `/Applications/` when possible
5. Register the app as a macOS login item

## Usage

| Action | How |
|---|---|
| **Open shelf** | Open `DropShelf.app` or click the menubar item → "Show / Hide Shelf" |
| **Add files** | Drag files from Finder onto the shelf |
| **Open a file** | Click on it in the shelf |
| **Remove one file** | Click the × button on that item |
| **Clear everything** | Click "Clear All" in the shelf header |
| **Quit** | Click the menubar item → "Quit" |

## Run Manually

```bash
open /Applications/DropShelf.app
```

## Uninstall

```bash
bash /path/to/dropshelf/uninstall.sh
```

This removes the app bundle, support files, and the login item.

## How It Works

DropShelf uses **PyObjC** to create a native macOS app entirely in Python — no Xcode or Swift needed. It uses:

- `NSWindow` with borderless style for the floating shelf
- `NSVisualEffectView` for the native macOS blur/vibrancy
- `NSStatusBar` for the menubar icon
- Drag-and-drop via `registerForDraggedTypes` / `performDragOperation`
- a generated `.app` bundle with a compiled launcher and `.icns` app icon
- a standard macOS login item for auto-start

## License

Free to use and modify. Do whatever you want with it!
