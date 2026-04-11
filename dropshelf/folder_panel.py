import os
import shutil

import objc
from AppKit import (
    NSAnimationContext,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSButton,
    NSColor,
    NSDragOperationCopy,
    NSDragOperationMove,
    NSDragOperationNone,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSOpenPanel,
    NSPasteboardTypeFileURL,
    NSScreen,
    NSScrollView,
    NSTextField,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSView,
    NSVisualEffectView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from Foundation import NSMakePoint, NSMakeSize, NSMutableDictionary, NSObject, NSTimer, NSURL

from .constants import (
    CORNER_RADIUS,
    FOLDER_ADD_BUTTON_HEIGHT,
    FOLDER_ITEM_HEIGHT,
    FOLDER_PANEL_ITEM_GAP,
    FOLDER_PANEL_MIN_HEIGHT,
    FOLDER_PANEL_PADDING,
    FOLDER_PANEL_WIDTH,
    FOLDER_TAB_DOCK_OVERLAP,
    FOLDER_TAB_HEIGHT_RATIO,
    FOLDER_TAB_MIN_HEIGHT,
    FOLDER_TAB_VISIBLE_WIDTH,
    SHELF_HEADER_HEIGHT,
    SHELF_WIDTH,
    TOAST_GUTTER_HEIGHT,
    WINDOW_BORDER_ALPHA,
    WINDOW_BORDER_WIDTH,
)
from .settings import save_settings
from .ui_components import ActionProxy


ICON_SIZE = 48
DRAWER_REVEAL_OFFSET = 18


def _count_files_in_folder(path):
    try:
        return len([f for f in os.listdir(path) if not f.startswith(".")])
    except OSError:
        return 0


class FolderItemView(NSView):
    """A single folder row — horizontal: icon left, name + count right."""

    @classmethod
    def make_item(cls, folder_path, remove_callback, move_callback):
        item_w = FOLDER_PANEL_WIDTH - 16
        view = cls.alloc().initWithFrame_(
            NSMakeRect(0, 0, item_w, FOLDER_ITEM_HEIGHT)
        )
        view._folder_path = folder_path
        view._remove_callback = remove_callback
        view._move_callback = move_callback
        view._hovered = False
        view._drop_targeted = False
        view._setup_ui(item_w)
        view._setup_tracking()
        view.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        return view

    def isFlipped(self):
        return True

    def _setup_ui(self, item_w):
        path = self._folder_path
        name = os.path.basename(path) or path

        icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
        icon.setSize_(NSMakeSize(ICON_SIZE, ICON_SIZE))
        icon_y = (FOLDER_ITEM_HEIGHT - ICON_SIZE) // 2
        iv = NSImageView.alloc().initWithFrame_(NSMakeRect(8, icon_y, ICON_SIZE, ICON_SIZE))
        iv.setImage_(icon)
        iv.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.addSubview_(iv)

        text_x = 8 + ICON_SIZE + 10
        text_w = item_w - text_x - 4

        if len(name) > 14:
            name = name[:12] + "…"
        name_lbl = NSTextField.labelWithString_(name)
        name_lbl.setFrame_(NSMakeRect(text_x, 16, text_w, 20))
        name_lbl.setFont_(NSFont.systemFontOfSize_weight_(14, 0.5))
        name_lbl.setTextColor_(NSColor.labelColor())
        name_lbl.setDrawsBackground_(False)
        name_lbl.setBezeled_(False)
        name_lbl.setEditable_(False)
        name_lbl.setSelectable_(False)
        self.addSubview_(name_lbl)

        count = _count_files_in_folder(path)
        count_str = f"{count} file{'s' if count != 1 else ''}"
        count_lbl = NSTextField.labelWithString_(count_str)
        count_lbl.setFrame_(NSMakeRect(text_x, 38, text_w, 16))
        count_lbl.setFont_(NSFont.systemFontOfSize_(12))
        count_lbl.setTextColor_(NSColor.secondaryLabelColor())
        count_lbl.setDrawsBackground_(False)
        count_lbl.setBezeled_(False)
        count_lbl.setEditable_(False)
        count_lbl.setSelectable_(False)
        self.addSubview_(count_lbl)

    def _setup_tracking(self):
        self._tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking_area)

    def mouseEntered_(self, event):
        self._hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hovered = False
        self.setNeedsDisplay_(True)

    def rightMouseDown_(self, event):
        menu = NSMenu.alloc().init()
        proxy = ActionProxy.alloc().initWithCallback_(
            lambda: self._remove_callback(self._folder_path)
        )
        self._menu_proxy = proxy
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Remove", b"invoke:", "")
        item.setTarget_(proxy)
        menu.addItem_(item)
        NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)

    def drawRect_(self, rect):
        bounds = self.bounds()
        r = NSMakeRect(2, 2, bounds.size.width - 4, bounds.size.height - 4)
        if self._drop_targeted:
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.25).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 8, 8).fill()
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.6).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 8, 8).stroke()
        elif self._hovered:
            NSColor.colorWithWhite_alpha_(0.5, 0.1).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 8, 8).fill()

    # --- NSDraggingDestination ---
    def draggingEntered_(self, sender):
        pb = sender.draggingPasteboard()
        if pb.types() and NSPasteboardTypeFileURL in pb.types():
            self._drop_targeted = True
            self.setNeedsDisplay_(True)
            return NSDragOperationMove
        return NSDragOperationNone

    def draggingUpdated_(self, sender):
        if self._drop_targeted:
            return NSDragOperationMove
        return NSDragOperationNone

    def draggingExited_(self, sender):
        self._drop_targeted = False
        self.setNeedsDisplay_(True)

    def performDragOperation_(self, sender):
        self._drop_targeted = False
        self.setNeedsDisplay_(True)
        pb = sender.draggingPasteboard()
        urls = pb.readObjectsForClasses_options_(
            [objc.lookUpClass("NSURL")],
            {"NSPasteboardURLReadingFileURLsOnlyKey": True},
        )
        if not urls:
            return False
        paths = [str(url.path()) for url in urls if url.path()]
        if paths:
            self._move_callback(paths, self._folder_path)
        return True


class FlippedView(NSView):
    def isFlipped(self):
        return True


class DrawerChevronView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(DrawerChevronView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._direction = "left"
        return self

    def isFlipped(self):
        return True

    def hitTest_(self, point):
        return None

    def setDirection_(self, direction):
        direction = direction if direction in {"left", "right"} else "left"
        if direction == self._direction:
            return
        self._direction = direction
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        cx = bounds.size.width / 2
        cy = bounds.size.height / 2
        half_w = 3.0
        half_h = 5.0
        path = NSBezierPath.bezierPath()
        if self._direction == "left":
            path.moveToPoint_(NSMakePoint(cx + half_w, cy - half_h))
            path.lineToPoint_(NSMakePoint(cx - half_w, cy))
            path.lineToPoint_(NSMakePoint(cx + half_w, cy + half_h))
        else:
            path.moveToPoint_(NSMakePoint(cx - half_w, cy - half_h))
            path.lineToPoint_(NSMakePoint(cx + half_w, cy))
            path.lineToPoint_(NSMakePoint(cx - half_w, cy + half_h))
        path.setLineWidth_(1.8)
        path.setLineCapStyle_(1)
        path.setLineJoinStyle_(1)
        NSColor.whiteColor().colorWithAlphaComponent_(0.92).set()
        path.stroke()


class AddFolderView(NSView):
    """Dashed border '+' button with 'New Folder' text."""

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        bounds = self.bounds()
        # Dashed icon area
        icon_rect = NSMakeRect(8, 8, ICON_SIZE, ICON_SIZE)
        dash_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(icon_rect, 8, 8)
        dash_path.setLineWidth_(1.5)
        dash_path.setLineDash_count_phase_([4.0, 3.0], 2, 0)
        NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.5).set()
        dash_path.stroke()

        # "+" in the center of the dashed box
        plus_attrs = NSMutableDictionary.alloc().init()
        plus_attrs[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(22, 0.2)
        plus_attrs[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
        plus_str = NSAttributedString.alloc().initWithString_attributes_("+", plus_attrs)
        text_size = plus_str.size()
        plus_x = icon_rect.origin.x + (icon_rect.size.width - text_size.width) / 2
        plus_y = icon_rect.origin.y + (icon_rect.size.height - text_size.height) / 2
        plus_str.drawAtPoint_(NSMakePoint(plus_x, plus_y))

        # "New Folder" text
        text_x = 8 + ICON_SIZE + 10
        label_attrs = NSMutableDictionary.alloc().init()
        label_attrs[NSFontAttributeName] = NSFont.systemFontOfSize_(13)
        label_attrs[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
        label_str = NSAttributedString.alloc().initWithString_attributes_("New Folder", label_attrs)
        label_size = label_str.size()
        label_y = (bounds.size.height - label_size.height) / 2
        label_str.drawAtPoint_(NSMakePoint(text_x, label_y))


class FolderPanelContentView(NSView):
    """Scrollable content view that also accepts folder drops."""

    def isFlipped(self):
        return True

    def draggingEntered_(self, sender):
        pb = sender.draggingPasteboard()
        if pb.types() and NSPasteboardTypeFileURL in pb.types():
            urls = pb.readObjectsForClasses_options_(
                [objc.lookUpClass("NSURL")],
                {"NSPasteboardURLReadingFileURLsOnlyKey": True},
            )
            if urls:
                for url in urls:
                    p = str(url.path())
                    if os.path.isdir(p):
                        return NSDragOperationCopy
        return NSDragOperationNone

    def performDragOperation_(self, sender):
        pb = sender.draggingPasteboard()
        urls = pb.readObjectsForClasses_options_(
            [objc.lookUpClass("NSURL")],
            {"NSPasteboardURLReadingFileURLsOnlyKey": True},
        )
        if not urls:
            return False
        added = False
        for url in urls:
            p = str(url.path())
            if os.path.isdir(p):
                self._panel_ref.add_folder(p)
                added = True
        return added


class FolderPanel:
    """Manages the lip tab and collapsible folder panel."""

    def __init__(self, shelf_window, settings):
        self._shelf_window = shelf_window
        self._settings = settings
        self._panel_open = False
        self._folder_views = []
        self._proxies = []
        self._panel_content_height = 0
        self._drawer_side = "left"
        self._build_lip()
        self._build_panel()
        self._refresh_folders()

    def _apply_surface_chrome(self, view, radius):
        view.setBlendingMode_(1)
        view.setMaterial_(6)
        view.setState_(1)
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(radius)
        view.layer().setMasksToBounds_(True)
        view.layer().setBorderWidth_(WINDOW_BORDER_WIDTH)
        view.layer().setBorderColor_(
            NSColor.colorWithWhite_alpha_(1.0, WINDOW_BORDER_ALPHA).CGColor()
        )

    def _build_lip(self):
        total_w = FOLDER_TAB_VISIBLE_WIDTH
        initial_h = FOLDER_TAB_MIN_HEIGHT

        self._lip_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, total_w, initial_h),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._lip_window.setLevel_(NSFloatingWindowLevel)
        self._lip_window.setOpaque_(False)
        self._lip_window.setBackgroundColor_(NSColor.clearColor())
        self._lip_window.setHasShadow_(False)
        self._lip_window.setHidesOnDeactivate_(False)
        self._lip_window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
        self._lip_total_width = total_w
        self._lip_height = initial_h

        cv = self._lip_window.contentView()
        body = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, total_w, initial_h)
        )
        self._apply_surface_chrome(body, CORNER_RADIUS)
        body.layer().setBorderColor_(
            NSColor.whiteColor().colorWithAlphaComponent_(0.24).CGColor()
        )
        cv.addSubview_(body)
        self._lip_bg = body

        self._lip_toggle_proxy = ActionProxy.alloc().initWithCallback_(self.toggle_panel)
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, total_w, initial_h))
        btn.setBordered_(False)
        btn.setTitle_("")
        btn.setTarget_(self._lip_toggle_proxy)
        btn.setAction_(b"invoke:")
        cv.addSubview_(btn)
        self._lip_btn = btn

        chevron = DrawerChevronView.alloc().initWithFrame_(
            NSMakeRect(0, 0, total_w, initial_h)
        )
        cv.addSubview_(chevron)
        self._lip_chevron = chevron
        self._sync_tab_symbol()

    def _build_panel(self):
        panel_h = FOLDER_PANEL_MIN_HEIGHT
        self._panel_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, panel_h),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._panel_window.setLevel_(NSFloatingWindowLevel)
        self._panel_window.setOpaque_(False)
        self._panel_window.setBackgroundColor_(NSColor.clearColor())
        self._panel_window.setHasShadow_(True)
        self._panel_window.setHidesOnDeactivate_(False)
        self._panel_window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

        cv = self._panel_window.contentView()

        bg = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, panel_h)
        )
        self._apply_surface_chrome(bg, CORNER_RADIUS)
        cv.addSubview_(bg)
        self._panel_bg = bg

        container = FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, panel_h)
        )
        bg.addSubview_(container)
        self._panel_container = container

        hdr = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, SHELF_HEADER_HEIGHT)
        )
        title = NSTextField.labelWithString_("Folders")
        title.setFrame_(NSMakeRect(14, 8, 120, 20))
        title.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5))
        title.setTextColor_(NSColor.labelColor())
        title.setDrawsBackground_(False)
        title.setBezeled_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        hdr.addSubview_(title)
        container.addSubview_(hdr)
        self._panel_header = hdr

        add_view = AddFolderView.alloc().initWithFrame_(
            NSMakeRect(
                FOLDER_PANEL_PADDING,
                panel_h - FOLDER_PANEL_PADDING - FOLDER_ADD_BUTTON_HEIGHT,
                FOLDER_PANEL_WIDTH - FOLDER_PANEL_PADDING * 2,
                FOLDER_ADD_BUTTON_HEIGHT,
            )
        )
        self._add_click_proxy = ActionProxy.alloc().initWithCallback_(self._pick_folder)
        add_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(
                0,
                0,
                FOLDER_PANEL_WIDTH - FOLDER_PANEL_PADDING * 2,
                FOLDER_ADD_BUTTON_HEIGHT,
            )
        )
        add_btn.setBordered_(False)
        add_btn.setTransparent_(True)
        add_btn.setTarget_(self._add_click_proxy)
        add_btn.setAction_(b"invoke:")
        add_view.addSubview_(add_btn)
        container.addSubview_(add_view)
        self._add_folder_view = add_view

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(
                0,
                SHELF_HEADER_HEIGHT,
                FOLDER_PANEL_WIDTH,
                max(0, panel_h - SHELF_HEADER_HEIGHT),
            )
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        self._panel_scroll = scroll

        content = FolderPanelContentView.alloc().initWithFrame_(
            NSMakeRect(
                0,
                0,
                FOLDER_PANEL_WIDTH,
                max(0, panel_h - SHELF_HEADER_HEIGHT),
            )
        )
        content._panel_ref = self
        content.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        scroll.setDocumentView_(content)
        container.addSubview_(scroll)
        self._panel_content = content

    def _refresh_folders(self):
        for v in self._folder_views:
            v.removeFromSuperview()
        self._folder_views.clear()

        folders = [f for f in self._settings.get("pinned_folders", []) if os.path.isdir(f)]
        item_w = FOLDER_PANEL_WIDTH - FOLDER_PANEL_PADDING * 2
        y = FOLDER_PANEL_PADDING
        for folder_path in folders:
            fv = FolderItemView.make_item(
                folder_path, self.remove_folder, self._move_files_to_folder
            )
            fv.setFrame_(NSMakeRect(FOLDER_PANEL_PADDING, y, item_w, FOLDER_ITEM_HEIGHT))
            self._panel_content.addSubview_(fv)
            self._folder_views.append(fv)
            y += FOLDER_ITEM_HEIGHT + FOLDER_PANEL_ITEM_GAP

        if folders:
            y += FOLDER_PANEL_PADDING - FOLDER_PANEL_ITEM_GAP
        self._panel_content_height = y
        self._update_panel_height()

    def _update_panel_height(self):
        visible = self._screen_visible_frame()
        max_panel_h = max(
            FOLDER_PANEL_MIN_HEIGHT,
            visible.size.height - 20,
        )
        desired_h = max(
            FOLDER_PANEL_MIN_HEIGHT,
            SHELF_HEADER_HEIGHT
            + self._panel_content_height
            + FOLDER_ADD_BUTTON_HEIGHT
            + FOLDER_PANEL_PADDING,
        )
        panel_h = min(desired_h, max_panel_h)
        add_y = panel_h - FOLDER_PANEL_PADDING - FOLDER_ADD_BUTTON_HEIGHT
        scroll_h = max(0, add_y - SHELF_HEADER_HEIGHT)
        document_h = max(self._panel_content_height, scroll_h)

        self._panel_window.setContentSize_(NSMakeSize(FOLDER_PANEL_WIDTH, panel_h))
        self._panel_bg.setFrame_(NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, panel_h))
        self._panel_container.setFrame_(NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, panel_h))
        self._panel_header.setFrame_(NSMakeRect(0, 0, FOLDER_PANEL_WIDTH, SHELF_HEADER_HEIGHT))
        self._add_folder_view.setFrame_(
            NSMakeRect(
                FOLDER_PANEL_PADDING,
                add_y,
                FOLDER_PANEL_WIDTH - FOLDER_PANEL_PADDING * 2,
                FOLDER_ADD_BUTTON_HEIGHT,
            )
        )
        self._panel_scroll.setFrame_(
            NSMakeRect(0, SHELF_HEADER_HEIGHT, FOLDER_PANEL_WIDTH, scroll_h)
        )
        self._panel_content.setFrameSize_(NSMakeSize(FOLDER_PANEL_WIDTH, document_h))
        self.update_position()

    def _pick_folder(self):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setAllowsMultipleSelection_(True)
        panel.setMessage_("Choose folders to add to Quick Folders")
        if panel.runModal() == 1:
            for url in panel.URLs():
                self.add_folder(str(url.path()))

    def add_folder(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        folders = self._settings.get("pinned_folders", [])
        if path not in folders and os.path.isdir(path):
            folders.append(path)
            self._settings["pinned_folders"] = folders
            save_settings(self._settings)
            self._refresh_folders()

    def remove_folder(self, path):
        folders = self._settings.get("pinned_folders", [])
        if path in folders:
            folders.remove(path)
            self._settings["pinned_folders"] = folders
            save_settings(self._settings)
            self._refresh_folders()

    def _move_files_to_folder(self, file_paths, dest_folder):
        moved = []
        for src in file_paths:
            if not os.path.exists(src):
                continue
            name = os.path.basename(src)
            dest = os.path.join(dest_folder, name)
            if os.path.exists(dest):
                base, ext = os.path.splitext(name)
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(dest_folder, f"{base} ({counter}){ext}")
                    counter += 1
            try:
                shutil.move(src, dest)
                moved.append(src)
            except OSError:
                try:
                    shutil.copy2(src, dest)
                    moved.append(src)
                except OSError:
                    pass

        if moved:
            shelf = self._shelf_window
            indices_to_remove = []
            for i, fp in enumerate(shelf._files):
                if fp in moved:
                    indices_to_remove.append(i)
            if indices_to_remove:
                shelf._remove_file_indices(indices_to_remove)
                shelf._refresh()

            folder_name = os.path.basename(dest_folder)
            if len(moved) == 1:
                shelf.show_toast(f"Moved to {folder_name}", "celebrate")
            else:
                shelf.show_toast(f"Moved {len(moved)} files to {folder_name}", "celebrate")

    def _shelf_geometry(self):
        f = self._shelf_window._window.frame()
        shelf_x = f.origin.x
        shelf_y = f.origin.y + TOAST_GUTTER_HEIGHT
        shelf_w = SHELF_WIDTH
        shelf_h = f.size.height - TOAST_GUTTER_HEIGHT
        return shelf_x, shelf_y, shelf_w, shelf_h

    def _screen_visible_frame(self):
        main = self._shelf_window._window
        screen = main.screen() or NSScreen.mainScreen()
        if screen is None:
            screens = NSScreen.screens()
            screen = screens[0] if screens else None
        return screen.visibleFrame() if screen is not None else main.frame()

    def _choose_drawer_side(self):
        visible = self._screen_visible_frame()
        safe_left = visible.origin.x + 10
        safe_right = visible.origin.x + visible.size.width - 10
        shelf_x, _, shelf_w, _ = self._shelf_geometry()
        shelf_right = shelf_x + shelf_w

        left_panel_x = (
            shelf_x - FOLDER_PANEL_WIDTH - self._lip_total_width + FOLDER_TAB_DOCK_OVERLAP
        )
        right_panel_x = (
            shelf_right + self._lip_total_width - FOLDER_TAB_DOCK_OVERLAP
        )

        left_fits = left_panel_x >= safe_left
        right_fits = right_panel_x + FOLDER_PANEL_WIDTH <= safe_right
        if left_fits:
            return "left"
        if right_fits:
            return "right"

        left_overflow = max(0, safe_left - left_panel_x)
        right_overflow = max(0, right_panel_x + FOLDER_PANEL_WIDTH - safe_right)
        return "left" if left_overflow <= right_overflow else "right"

    def _tab_symbol(self, side):
        if side == "left":
            return "\u203a" if self._panel_open else "\u2039"
        return "\u2039" if self._panel_open else "\u203a"

    def _sync_tab_symbol(self):
        self._update_lip_surface_frames(self._drawer_side)
        direction = "right" if self._tab_symbol(self._drawer_side) == "\u203a" else "left"
        self._lip_chevron.setDirection_(direction)

    def _update_lip_surface_frames(self, side):
        h = self._lip_height
        w = self._lip_total_width
        self._lip_bg.setFrame_(NSMakeRect(0, 0, w, h))
        # Center chevron in the visible portion only (not hidden behind shelf)
        visible_w = w - FOLDER_TAB_DOCK_OVERLAP
        if side == "left":
            self._lip_chevron.setFrame_(NSMakeRect(0, 0, visible_w, h))
        else:
            self._lip_chevron.setFrame_(NSMakeRect(FOLDER_TAB_DOCK_OVERLAP, 0, visible_w, h))

    def _resize_lip(self, height):
        height = int(height)
        if height == self._lip_height:
            return
        self._lip_height = height
        w = self._lip_total_width
        self._lip_window.setContentSize_(NSMakeSize(w, height))
        self._lip_bg.setFrame_(NSMakeRect(0, 0, w, height))
        self._lip_btn.setFrame_(NSMakeRect(0, 0, w, height))
        self._update_lip_surface_frames(self._drawer_side)

    def _layout_frames(self, side=None):
        side = side or self._choose_drawer_side()
        shelf_x, shelf_y, shelf_w, shelf_h = self._shelf_geometry()
        visible = self._screen_visible_frame()
        shelf_right = shelf_x + shelf_w
        panel_h = self._panel_window.frame().size.height

        # Dynamic tab height: ~32% of shelf, vertically centered
        tab_h = max(FOLDER_TAB_MIN_HEIGHT, int(shelf_h * FOLDER_TAB_HEIGHT_RATIO))
        self._resize_lip(tab_h)

        tab_y = shelf_y + (shelf_h - tab_h) / 2
        panel_y = shelf_y + shelf_h - panel_h
        panel_y = max(visible.origin.y + 10, panel_y)
        panel_y = min(
            panel_y,
            visible.origin.y + visible.size.height - panel_h - 10,
        )

        if side == "left":
            tab_x = shelf_x - self._lip_total_width + FOLDER_TAB_DOCK_OVERLAP
            panel_x = tab_x - FOLDER_PANEL_WIDTH
            hidden_panel_x = panel_x + DRAWER_REVEAL_OFFSET
        else:
            tab_x = shelf_right - FOLDER_TAB_DOCK_OVERLAP
            panel_x = tab_x + self._lip_total_width
            hidden_panel_x = panel_x - DRAWER_REVEAL_OFFSET

        return {
            "side": side,
            "tab": NSMakeRect(tab_x, tab_y, self._lip_total_width, tab_h),
            "panel": NSMakeRect(panel_x, panel_y, FOLDER_PANEL_WIDTH, panel_h),
            "hidden_panel": NSMakeRect(
                hidden_panel_x, panel_y, FOLDER_PANEL_WIDTH, panel_h
            ),
        }

    def _position_windows(self):
        layout = self._layout_frames()
        self._drawer_side = layout["side"]
        self._sync_tab_symbol()
        self._lip_window.setFrameOrigin_(
            NSMakePoint(layout["tab"].origin.x, layout["tab"].origin.y)
        )
        if self._panel_open:
            self._panel_window.setFrameOrigin_(
                NSMakePoint(layout["panel"].origin.x, layout["panel"].origin.y)
            )
        return layout

    def _attach_child_window(self, child, ordered=1):
        main = self._shelf_window._window
        if child in (main.childWindows() or []):
            main.removeChildWindow_(child)
        main.addChildWindow_ordered_(child, ordered)

    def show(self):
        layout = self._position_windows()
        # Lip renders behind the shelf so the shelf edge sits on top
        self._attach_child_window(self._lip_window, ordered=-1)
        self._lip_window.orderFront_(None)
        if self._panel_open:
            self._panel_window.setAlphaValue_(1.0)
            self._panel_window.setFrameOrigin_(
                NSMakePoint(layout["panel"].origin.x, layout["panel"].origin.y)
            )
            self._attach_child_window(self._panel_window)
            self._panel_window.orderFront_(None)

    def hide(self):
        self._lip_window.orderOut_(None)
        self._panel_window.orderOut_(None)
        main = self._shelf_window._window
        if self._lip_window in (main.childWindows() or []):
            main.removeChildWindow_(self._lip_window)
        if self._panel_window in (main.childWindows() or []):
            main.removeChildWindow_(self._panel_window)

    def toggle_panel(self):
        if self._panel_open:
            self._close_panel()
        else:
            self._open_panel()

    def _open_panel(self):
        self._panel_open = True
        self._refresh_folders()
        layout = self._layout_frames()
        self._drawer_side = layout["side"]
        self._sync_tab_symbol()
        self._lip_window.setFrameOrigin_(
            NSMakePoint(layout["tab"].origin.x, layout["tab"].origin.y)
        )
        self._panel_window.setFrame_display_(layout["hidden_panel"], False)
        self._panel_window.setAlphaValue_(0.0)
        self._attach_child_window(self._panel_window)
        self._panel_window.orderFront_(None)

        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.2)
        self._panel_window.animator().setFrameOrigin_(
            NSMakePoint(layout["panel"].origin.x, layout["panel"].origin.y)
        )
        self._panel_window.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()

    def _close_panel(self):
        layout = self._layout_frames(side=self._drawer_side)
        self._panel_open = False
        self._sync_tab_symbol()

        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.18)
        self._panel_window.animator().setFrameOrigin_(
            NSMakePoint(
                layout["hidden_panel"].origin.x,
                layout["hidden_panel"].origin.y,
            )
        )
        self._panel_window.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

        self._close_proxy = ActionProxy.alloc().initWithCallback_(self._finish_close)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.20, self._close_proxy, b"invoke:", None, False
        )

    def _finish_close(self):
        if self._panel_open:
            return
        self._panel_window.orderOut_(None)
        main = self._shelf_window._window
        if self._panel_window in (main.childWindows() or []):
            main.removeChildWindow_(self._panel_window)

    def update_position(self):
        if self._lip_window.isVisible() or self._panel_window.isVisible():
            self._position_windows()
