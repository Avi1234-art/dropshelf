import hashlib
import os
import subprocess
import tempfile

from AppKit import NSColor, NSEvent, NSImage, NSScreen, NSWorkspace
from Foundation import NSMakeSize

from .constants import PREVIEW_SIZE, SHELF_WIDTH


def find_icon():
    """Find a bundled menu icon next to the runtime package, launcher, or in ~/.dropshelf/."""
    package_dir = os.path.dirname(os.path.abspath(__file__))
    base_dirs = [
        package_dir,
        os.path.dirname(package_dir),
        os.path.expanduser("~/.dropshelf"),
    ]
    candidates = []
    for base_dir in base_dirs:
        candidates.extend(
            [
                os.path.join(base_dir, "DropshelfMenuIcon.png"),
                os.path.join(base_dir, "DropshelfIcon.png"),
                os.path.join(base_dir, "output-onlinepngtools.png"),
            ]
        )
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def make_status_item_image():
    for symbol_name in ("tray.full.fill", "shippingbox.fill", "folder.fill"):
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol_name, "DropShelf"
            )
        except Exception:
            img = None
        if img:
            img.setSize_(NSMakeSize(18, 18))
            img.setTemplate_(True)
            return img

    icon_path = find_icon()
    if icon_path:
        img = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if img:
            img.setSize_(NSMakeSize(18, 18))
            img.setTemplate_(True)
            return img
    return None


_THUMB_DIR = os.path.join(tempfile.gettempdir(), "dropshelf_thumbs")


def _thumbnail_output_dir(path, ql_size):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    key_src = f"{os.path.abspath(path)}:{mtime}:{ql_size}".encode(
        "utf-8", "surrogatepass"
    )
    key = hashlib.sha1(key_src).hexdigest()[:20]
    out_dir = os.path.join(_THUMB_DIR, key)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def get_file_thumbnail(path, size=PREVIEW_SIZE):
    """Get a Quick Look thumbnail for the file via qlmanage."""
    ql_size = max(size * 2, 128)
    out_dir = _thumbnail_output_dir(path, ql_size)
    thumb_name = os.path.basename(path) + ".png"
    thumb_path = os.path.join(out_dir, thumb_name)

    if os.path.exists(thumb_path):
        img = NSImage.alloc().initWithContentsOfFile_(thumb_path)
        if img and img.isValid():
            img.setSize_(NSMakeSize(size, size))
            return img

    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", str(ql_size), "-o", out_dir, path],
            capture_output=True,
            timeout=3,
        )
        if os.path.exists(thumb_path):
            img = NSImage.alloc().initWithContentsOfFile_(thumb_path)
            if img and img.isValid():
                img.setSize_(NSMakeSize(size, size))
                return img
    except (subprocess.TimeoutExpired, OSError):
        pass
    workspace = NSWorkspace.sharedWorkspace()
    icon = workspace.iconForFile_(path)
    icon.setSize_(NSMakeSize(size, size))
    return icon


def get_file_icon(path):
    workspace = NSWorkspace.sharedWorkspace()
    icon = workspace.iconForFile_(path)
    icon.setSize_(NSMakeSize(48, 48))
    return icon


def human_readable_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_file_size_bytes(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def normalize_shelf_path(path):
    return os.path.abspath(os.path.expanduser(str(path)))


def file_identity(path):
    normalized_path = normalize_shelf_path(path)
    try:
        stat = os.stat(normalized_path)
        return ("inode", stat.st_dev, stat.st_ino)
    except OSError:
        return ("path", normalized_path)


def size_badge_style(size_bytes):
    if size_bytes < 1024 * 1024:
        color = NSColor.systemGrayColor()
    elif size_bytes < 100 * 1024 * 1024:
        color = NSColor.systemBlueColor()
    elif size_bytes < 1024 * 1024 * 1024:
        color = NSColor.colorWithRed_green_blue_alpha_(0.95, 0.66, 0.18, 1.0)
    else:
        color = NSColor.systemOrangeColor()
    return color, color.colorWithAlphaComponent_(0.12)


def classify_file_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".heic",
        ".svg",
        ".bmp",
        ".tiff",
        ".tif",
        ".icns",
        ".psd",
        ".avif",
    }:
        return "images"
    if ext in {
        ".pdf",
        ".doc",
        ".docx",
        ".pages",
        ".txt",
        ".rtf",
        ".md",
        ".csv",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".key",
        ".numbers",
        ".odt",
    }:
        return "documents"
    if ext in {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".html",
        ".css",
        ".scss",
        ".swift",
        ".java",
        ".rb",
        ".go",
        ".rs",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".sh",
        ".zsh",
        ".bash",
        ".yml",
        ".yaml",
        ".toml",
        ".xml",
        ".php",
        ".cs",
        ".kt",
        ".sql",
        ".m",
        ".mm",
    }:
        return "code"
    if ext in {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mkv",
        ".webm",
        ".wmv",
        ".mpg",
        ".mpeg",
        ".3gp",
        ".flv",
    }:
        return "videos"
    return "other"


def _format_location_label(root_label, child_parts, preposition="in"):
    if child_parts:
        return f"{preposition} {root_label} -> {child_parts[0]}"
    return f"{preposition} {root_label}"


def describe_file_location(path):
    abs_path = os.path.abspath(os.path.expanduser(path))
    home_dir = os.path.expanduser("~")
    try:
        rel_to_home = os.path.relpath(abs_path, home_dir)
    except ValueError:
        rel_to_home = None

    if rel_to_home and not rel_to_home.startswith(".."):
        parts = rel_to_home.split(os.sep)
        if parts[0] in {"Downloads", "Documents"}:
            return _format_location_label(parts[0], parts[1:-1], "in")
        if parts[0] == "Desktop":
            return _format_location_label("Desktop", parts[1:-1], "on")
        if parts[0] == "OneDrive" or parts[0].startswith("OneDrive - "):
            return _format_location_label("OneDrive", parts[1:-1], "in")
        if (
            len(parts) >= 3
            and parts[0] == "Library"
            and parts[1] == "CloudStorage"
            and parts[2].startswith("OneDrive")
        ):
            return _format_location_label("OneDrive", parts[3:-1], "in")
        if (
            len(parts) >= 3
            and parts[0] == "Library"
            and parts[1] == "Mobile Documents"
            and parts[2] == "com~apple~CloudDocs"
        ):
            return _format_location_label("iCloud Drive", parts[3:-1], "in")
        if parts[0]:
            return _format_location_label(parts[0], parts[1:-1], "in")

    parent = os.path.basename(os.path.dirname(abs_path))
    if parent:
        return f"in {parent}"
    return ""


def compute_position(position_name, content_h):
    mouse = NSEvent.mouseLocation()
    screen = None
    for candidate in NSScreen.screens():
        frame = candidate.frame()
        if (
            frame.origin.x <= mouse.x < frame.origin.x + frame.size.width
            and frame.origin.y <= mouse.y < frame.origin.y + frame.size.height
        ):
            screen = candidate
            break
    if screen is None:
        screen = NSScreen.mainScreen() or NSScreen.screens()[0]
    sf = screen.visibleFrame()
    margin = 20
    if position_name == "near-cursor":
        x, y = mouse.x - SHELF_WIDTH / 2, mouse.y - content_h - margin
    elif position_name == "top-left":
        x, y = sf.origin.x + margin, sf.origin.y + sf.size.height - content_h - margin
    elif position_name == "bottom-right":
        x, y = (
            sf.origin.x + sf.size.width - SHELF_WIDTH - margin,
            sf.origin.y + margin,
        )
    elif position_name == "bottom-left":
        x, y = sf.origin.x + margin, sf.origin.y + margin
    else:
        x, y = (
            sf.origin.x + sf.size.width - SHELF_WIDTH - margin,
            sf.origin.y + sf.size.height - content_h - margin,
        )
    max_x = sf.origin.x + sf.size.width - SHELF_WIDTH - 10
    min_x = sf.origin.x + 10
    max_y = sf.origin.y + sf.size.height - content_h - 10
    min_y = sf.origin.y + 10
    return max(min_x, min(x, max_x)), max(min_y, min(y, max_y))
