#!/bin/bash
# DropShelf Uninstaller

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

APP_NAME="DropShelf"
APP_ID="com.dropshelf.app"
SYSTEM_APP_BUNDLE="/Applications/${APP_NAME}.app"
USER_APP_BUNDLE="$HOME/Applications/${APP_NAME}.app"
SUPPORT_DIR="$HOME/.dropshelf"
PLIST_PATH="$HOME/Library/LaunchAgents/${APP_ID}.plist"

echo ""
echo -e "${CYAN}${BOLD}Uninstalling DropShelf...${NC}"
echo ""

if [ -f "$PLIST_PATH" ]; then
    launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || \
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
    rm -f "$PLIST_PATH"
    echo -e "  ${GREEN}✓${NC} Launch agent removed"
fi

osascript <<EOF >/dev/null 2>&1 || true
tell application "System Events"
    repeat while exists login item "${APP_NAME}"
        delete login item "${APP_NAME}"
    end repeat
end tell
EOF
echo -e "  ${GREEN}✓${NC} Login item removed"

if [ -d "$SYSTEM_APP_BUNDLE" ]; then
    rm -rf "$SYSTEM_APP_BUNDLE"
    echo -e "  ${GREEN}✓${NC} System app bundle removed"
fi

if [ -d "$USER_APP_BUNDLE" ]; then
    rm -rf "$USER_APP_BUNDLE"
    echo -e "  ${GREEN}✓${NC} App bundle removed"
fi

if [ -d "$SUPPORT_DIR" ]; then
    rm -rf "$SUPPORT_DIR"
    echo -e "  ${GREEN}✓${NC} Support files removed"
fi

echo ""
echo -e "${GREEN}${BOLD}  DropShelf has been uninstalled.${NC}"
echo ""
