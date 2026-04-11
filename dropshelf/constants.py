import os

from AppKit import NSColor


SHELF_WIDTH = 320
SHELF_ITEM_HEIGHT = 72
SHELF_PADDING = 8
SHELF_HEADER_HEIGHT = 36
SHELF_MAX_VISIBLE_ITEMS = 6
CORNER_RADIUS = 14
WINDOW_BORDER_WIDTH = 0.5
WINDOW_BORDER_ALPHA = 0.15
DRAG_THRESHOLD = 5
REORDER_DRAG_THRESHOLD = 4
REORDER_VERTICAL_BIAS = 0.9
SHAKE_POLL_INTERVAL = 0.016
PREVIEW_SIZE = 44
SECTION_HEADER_HEIGHT = 24
SECTION_GAP = 6
ITEM_GAP = 4
CLEAR_ALL_STAGGER = 0.03
CLEAR_ALL_DURATION = 0.18
TOAST_DURATION = 1.55
REVEAL_PULSE_DELAY = 0.08
MARQUEE_START_DELAY = 0.45
MARQUEE_EDGE_PAUSE = 0.6
MARQUEE_POINTS_PER_SECOND = 28.0
MARQUEE_RETURN_DURATION = 0.22
TOAST_SHOW_DURATION = 0.22
TOAST_HIDE_DURATION = 0.18
# Gap between the shelf edge and the toast banner.  Must be > 0 to
# prevent the toast from sitting flush against the shelf, which causes
# a visible clipping artifact during the slide animation.
TOAST_BODY_GAP = 6
TOAST_RETRACT_DISTANCE = 8
TOAST_WINDOW_TOP_INSET = 0
TOAST_SHELF_OVERLAP = 0
TOAST_BODY_HEIGHT = 28
TOAST_MIN_WIDTH = 156
TOAST_TEXT_PADDING = 18
TOAST_TEXT_VERTICAL_OFFSET = 1
# Height of the transparent gutter below the shelf that holds the toast.
TOAST_GUTTER_HEIGHT = 32

# Sensitivity presets: (direction_changes, time_window_s, min_segment_px)
# Tuned so that normal cursor movement between UI elements does NOT
# false-trigger, while a deliberate horizontal shake still registers.
SENSITIVITY_PRESETS = {
    "low": (5, 0.4, 28),
    "medium": (4, 0.5, 22),
    "high": (3, 0.55, 15),
}

SETTINGS_PATH = os.path.expanduser("~/.dropshelf/settings.json")
DEFAULT_SETTINGS = {
    "position": "top-right",
    "sensitivity": "medium",
    "auto_organize": False,
    "pinned_folders": [],
}

# Folder panel constants
FOLDER_PANEL_WIDTH = 180
FOLDER_ITEM_HEIGHT = 56
FOLDER_PANEL_PADDING = 6
FOLDER_PANEL_ITEM_GAP = 4
FOLDER_ADD_BUTTON_HEIGHT = 44
FOLDER_TAB_VISIBLE_WIDTH = 18
FOLDER_TAB_DOCK_OVERLAP = 10
FOLDER_PANEL_SHELF_GAP = 4
FOLDER_TAB_HEIGHT_RATIO = 0.35
FOLDER_TAB_MIN_HEIGHT = 36
FOLDER_PANEL_MIN_HEIGHT = (
    SHELF_HEADER_HEIGHT
    + FOLDER_ITEM_HEIGHT
    + FOLDER_PANEL_ITEM_GAP
    + FOLDER_ADD_BUTTON_HEIGHT
    + FOLDER_PANEL_PADDING * 3
)

TYPE_SECTIONS = [
    ("Images", "images"),
    ("Documents", "documents"),
    ("Code", "code"),
    ("Videos", "videos"),
    ("Other", "other"),
]

SECTION_COLORS = {
    "Pinned": NSColor.systemOrangeColor(),
    "Images": NSColor.systemBlueColor(),
    "Documents": NSColor.systemGrayColor(),
    "Code": NSColor.systemGreenColor(),
    "Videos": NSColor.colorWithRed_green_blue_alpha_(0.94, 0.48, 0.19, 1.0),
    "Other": NSColor.systemPurpleColor(),
}
