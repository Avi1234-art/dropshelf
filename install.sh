#!/bin/bash
# DropShelf Installer
# Builds a proper macOS app bundle and configures launch-at-login.

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

APP_NAME="DropShelf"
APP_ID="com.dropshelf.app"
SYSTEM_APP_DIR="/Applications"
USER_APP_DIR="$HOME/Applications"
if [ -w "$SYSTEM_APP_DIR" ]; then
    APP_DIR="$SYSTEM_APP_DIR"
else
    APP_DIR="$USER_APP_DIR"
fi
APP_BUNDLE="$APP_DIR/${APP_NAME}.app"
LEGACY_APP_BUNDLE="$HOME/Applications/${APP_NAME}.app"
SUPPORT_DIR="$HOME/.dropshelf"
PLIST_PATH="$HOME/Library/LaunchAgents/${APP_ID}.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_SOURCE="$SUPPORT_DIR/${APP_NAME}AppIcon.png"
LAUNCHER_SOURCE="$SCRIPT_DIR/app_launcher.c"
APP_RESOURCES_DIR="$APP_BUNDLE/Contents/Resources"
APP_MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
APP_EXECUTABLE="$APP_MACOS_DIR/$APP_NAME"
ICON_ICNS="$APP_RESOURCES_DIR/AppIcon.icns"

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔═══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║        DropShelf Installer           ║${NC}"
    echo -e "${CYAN}${BOLD}╚═══════════════════════════════════════╝${NC}"
    echo ""
}

require_command() {
    local cmd="$1"
    local message="$2"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo -e "${RED}✗ ${message}${NC}"
        exit 1
    fi
}

build_bundle_icon() {
    "$PYTHON3_PATH" "$SCRIPT_DIR/build_icns.py" "$ICON_SOURCE" "$ICON_ICNS"
}

build_app_launcher() {
    rm -f "$APP_EXECUTABLE"
    clang $(python3-config --embed --cflags --ldflags) "$LAUNCHER_SOURCE" -o "$APP_EXECUTABLE"
}

write_info_plist() {
    cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${APP_ID}</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0</string>
    <key>CFBundleVersion</key>
    <string>2.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
EOF
}

stop_existing_agent() {
    launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || \
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
}

remove_launch_agent() {
    stop_existing_agent
    rm -f "$PLIST_PATH"
}

remove_login_item() {
    osascript <<EOF >/dev/null 2>&1 || true
tell application "System Events"
    repeat while exists login item "${APP_NAME}"
        delete login item "${APP_NAME}"
    end repeat
end tell
EOF
}

create_login_item() {
    osascript <<EOF >/dev/null
tell application "System Events"
    repeat while exists login item "${APP_NAME}"
        delete login item "${APP_NAME}"
    end repeat
    make login item at end with properties {name:"${APP_NAME}", path:"${APP_BUNDLE}", hidden:false}
end tell
EOF
}

refresh_launch_services() {
    local lsregister
    lsregister="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if [ -x "$lsregister" ]; then
        "$lsregister" -f "$APP_BUNDLE" >/dev/null 2>&1 || true
    fi
}

print_header

echo -e "${BOLD}[1/5]${NC} Checking macOS tools..."
require_command python3 "Python 3 not found. Install it from python.org or Homebrew first."
require_command python3-config "python3-config is missing."
require_command clang "clang is missing."
require_command codesign "codesign is missing."
PYTHON3_PATH="$(command -v python3)"
echo -e "  ${GREEN}✓${NC} Found $(python3 --version 2>&1)"

echo -e "${BOLD}[2/5]${NC} Verifying Python dependencies..."
if "$PYTHON3_PATH" -c 'import AppKit, Quartz' >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} PyObjC is already installed"
else
    "$PYTHON3_PATH" -m pip install --quiet pyobjc-framework-Cocoa pyobjc-framework-Quartz 2>/dev/null || \
    "$PYTHON3_PATH" -m pip install --quiet --user pyobjc-framework-Cocoa pyobjc-framework-Quartz
    echo -e "  ${GREEN}✓${NC} Dependencies installed"
fi

echo -e "${BOLD}[3/5]${NC} Building the app icon..."
mkdir -p "$SUPPORT_DIR"
"$PYTHON3_PATH" "$SCRIPT_DIR/build_app_icon.py" "$ICON_SOURCE"
rm -f "$SUPPORT_DIR/dropshelf.py" \
      "$SUPPORT_DIR/DropShelfAppIcon.rsrc" \
      "$SUPPORT_DIR/DropshelfMenuIcon.png" \
      "$SUPPORT_DIR/DropshelfIcon.png" \
      "$SUPPORT_DIR/output-onlinepngtools.png"
echo -e "  ${GREEN}✓${NC} Generated $ICON_SOURCE"

echo -e "${BOLD}[4/5]${NC} Installing ${APP_NAME}.app to $APP_DIR..."
mkdir -p "$APP_DIR"
rm -rf "$APP_BUNDLE"
if [ "$APP_BUNDLE" != "$LEGACY_APP_BUNDLE" ]; then
    rm -rf "$LEGACY_APP_BUNDLE"
fi
mkdir -p "$APP_RESOURCES_DIR" "$APP_MACOS_DIR"
cp "$SCRIPT_DIR/dropshelf.py" "$APP_RESOURCES_DIR/dropshelf.py"
cp -R "$SCRIPT_DIR/dropshelf" "$APP_RESOURCES_DIR/dropshelf"
cp "$SCRIPT_DIR/build_app_icon.py" "$APP_RESOURCES_DIR/build_app_icon.py"
cp "$SCRIPT_DIR/build_icns.py" "$APP_RESOURCES_DIR/build_icns.py"
cp "$LAUNCHER_SOURCE" "$APP_RESOURCES_DIR/app_launcher.c"

if [ -f "$SCRIPT_DIR/DropshelfMenuIcon.png" ]; then
    cp "$SCRIPT_DIR/DropshelfMenuIcon.png" "$APP_RESOURCES_DIR/DropshelfMenuIcon.png"
fi

build_app_launcher
build_bundle_icon
write_info_plist
codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null
refresh_launch_services
echo -e "  ${GREEN}✓${NC} Installed $APP_BUNDLE"

echo -e "${BOLD}[5/5]${NC} Setting up launch at login..."
remove_launch_agent
remove_login_item
create_login_item
open -g "$APP_BUNDLE" >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓${NC} Login item created"

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  DropShelf installed successfully!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}App bundle:${NC}        $APP_BUNDLE"
echo -e "  ${BOLD}Open now:${NC}          open \"$APP_BUNDLE\""
echo -e "  ${BOLD}Auto-starts:${NC}       Yes, as a macOS login item"
echo -e "  ${BOLD}Settings/logs:${NC}     $SUPPORT_DIR"
echo ""
echo -e "  ${YELLOW}To uninstall:${NC}      bash $SCRIPT_DIR/uninstall.sh"
echo ""
