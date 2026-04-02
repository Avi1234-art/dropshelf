import os
import time

import objc
from AppKit import (
    NSAnimationContext,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSOffState,
    NSOnState,
    NSScrollView,
    NSScreen,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakePoint, NSMakeSize, NSMutableDictionary, NSTimer

from .constants import (
    CLEAR_ALL_DURATION,
    CLEAR_ALL_STAGGER,
    CORNER_RADIUS,
    ITEM_GAP,
    REVEAL_PULSE_DELAY,
    SECTION_COLORS,
    SECTION_GAP,
    SECTION_HEADER_HEIGHT,
    SHELF_HEADER_HEIGHT,
    SHELF_ITEM_HEIGHT,
    SHELF_MAX_VISIBLE_ITEMS,
    SHELF_PADDING,
    SHELF_WIDTH,
    TOAST_BODY_HEIGHT,
    TOAST_DURATION,
    TOAST_GUTTER_HEIGHT,
    TOAST_HIDE_DURATION,
    TOAST_SHOW_DURATION,
    TYPE_SECTIONS,
)
from .file_utils import (
    classify_file_type,
    compute_position,
    file_identity,
    get_file_size_bytes,
    get_file_thumbnail,
    human_readable_size,
    normalize_shelf_path,
)
from .settings import save_settings
from .ui_components import (
    ActionProxy,
    DropPlaceholderView,
    DropTargetView,
    SectionHeaderView,
    ShelfItemView,
    ToastBannerView,
)


class ShelfWindow:
    def __init__(self, settings):
        self._files = []
        self._item_views = []
        self._content_views = []
        self._settings = settings
        self._last_toggle = 0.0
        self._shake_detector = None  # set by AppDelegate after creation
        self._new_files = set()
        self._drop_highlight = False
        self._drop_indicator_view = None
        self._drop_gap_index = None
        self._pre_drop_content_frames = {}
        self._pre_drop_doc_height = None
        self._pre_drop_window_height = None
        self._pre_drop_scroll_origin_y = 0.0
        self._highlight_proxy = None
        self._selected_indices = set()
        self._last_selected_index = None
        self._sort_order = "date-added"
        self._sort_proxies = []
        self._pinned_indices = set()
        self._auto_organize = bool(self._settings.get("auto_organize", False))
        self._collapsed_sections = set()
        self._reorder_dragged_index = None
        self._reorder_drag_view = None
        self._reorder_slot_frames = {}
        self._reorder_drag_offset_y = 0.0
        self._reorder_group_indices = []
        self._reorder_target_pos = None
        self._reorder_indicator_y = None
        self._hover_preview_window = None
        self._hover_preview_owner = None
        self._clear_in_progress = False
        self._clear_animation_proxies = []
        self._toast_generation = 0
        self._toast_hide_proxy = None
        self._reveal_proxy = None
        self._show_hide_generation = 0
        self._show_hide_proxy = None
        self._animating_show_hide = False
        self._build_window()

    def _build_window(self):
        h = 160
        window_h = h + TOAST_GUTTER_HEIGHT
        x, y = compute_position(self._settings["position"], window_h)

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, SHELF_WIDTH, window_h),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setMovableByWindowBackground_(True)
        self._window.setAlphaValue_(1.0)
        self._window.setHidesOnDeactivate_(False)
        self._window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

        cv = self._window.contentView()
        cv.setWantsLayer_(True)

        # Toast is added first so it draws behind the bg.
        toast = ToastBannerView.make_toast()
        toast.setAlphaValue_(0.0)
        toast.setWantsLayer_(True)
        toast.setAttachment_("below")
        cv.addSubview_(toast)
        self._toast_view = toast

        bg = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, TOAST_GUTTER_HEIGHT, SHELF_WIDTH, h)
        )
        bg.setAutoresizingMask_(0)
        bg.setBlendingMode_(1)
        bg.setMaterial_(6)
        bg.setState_(1)
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(CORNER_RADIUS)
        bg.layer().setMasksToBounds_(True)
        bg.layer().setBorderWidth_(0.5)
        bg.layer().setBorderColor_(
            NSColor.colorWithWhite_alpha_(1.0, 0.15).CGColor()
        )
        cv.addSubview_(bg)
        self._bg = bg

        hdr = NSView.alloc().initWithFrame_(
            NSMakeRect(0, h - SHELF_HEADER_HEIGHT, SHELF_WIDTH, SHELF_HEADER_HEIGHT)
        )
        bg.addSubview_(hdr)
        self._header = hdr

        self._close_proxy = ActionProxy.alloc().initWithCallback_(self.hide)
        close_btn = NSButton.alloc().initWithFrame_(NSMakeRect(8, 8, 22, 22))
        close_btn.setBordered_(False)
        ca = NSMutableDictionary.alloc().init()
        ca[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
        ca[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(16, 0.3)
        close_btn.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_("×", ca))
        close_btn.setTarget_(self._close_proxy)
        close_btn.setAction_(b"invoke:")
        hdr.addSubview_(close_btn)

        title = NSTextField.labelWithString_("DropShelf")
        title.setFrame_(NSMakeRect(32, 8, 100, 20))
        title.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5))
        title.setTextColor_(NSColor.labelColor())
        title.setDrawsBackground_(False)
        title.setBezeled_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        hdr.addSubview_(title)

        self._sort_btn_proxy = ActionProxy.alloc().initWithCallback_(self._showSortMenu)
        sort_btn = NSButton.alloc().initWithFrame_(NSMakeRect(104, 8, 22, 22))
        sort_btn.setBordered_(False)
        sa = NSMutableDictionary.alloc().init()
        sa[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
        sa[NSFontAttributeName] = NSFont.systemFontOfSize_(13)
        sort_btn.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_("↕", sa))
        sort_btn.setTarget_(self._sort_btn_proxy)
        sort_btn.setAction_(b"invoke:")
        hdr.addSubview_(sort_btn)
        self._sort_btn = sort_btn

        self._count_label = NSTextField.labelWithString_("0 items")
        self._count_label.setFrame_(NSMakeRect(128, 8, 112, 20))
        self._count_label.setFont_(NSFont.systemFontOfSize_(11))
        self._count_label.setTextColor_(NSColor.secondaryLabelColor())
        self._count_label.setDrawsBackground_(False)
        self._count_label.setBezeled_(False)
        self._count_label.setEditable_(False)
        self._count_label.setSelectable_(False)
        self._count_label.setAlignment_(2)
        hdr.addSubview_(self._count_label)

        self._clear_proxy = ActionProxy.alloc().initWithCallback_(self.clear_all)
        clr = NSButton.alloc().initWithFrame_(NSMakeRect(SHELF_WIDTH - 78, 8, 65, 20))
        clr.setBordered_(False)
        ra = NSMutableDictionary.alloc().init()
        ra[NSForegroundColorAttributeName] = NSColor.colorWithRed_green_blue_alpha_(
            1.0, 0.45, 0.45, 0.85
        )
        ra[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(11, 0.3)
        clr.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_("Clear All", ra))
        clr.setTarget_(self._clear_proxy)
        clr.setAction_(b"invoke:")
        hdr.addSubview_(clr)
        self._clear_btn = clr

        dh = h - SHELF_HEADER_HEIGHT
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, SHELF_WIDTH, dh))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        self._scroll_view = scroll

        self._drop_view = DropTargetView.make_view(NSMakeRect(0, 0, SHELF_WIDTH, dh), self)
        self._scroll_view.setDocumentView_(self._drop_view)
        bg.addSubview_(self._scroll_view)


    def show(self):
        self._show_hide_generation += 1
        generation = self._show_hide_generation
        h = self._window.frame().size.height
        x, y = compute_position(self._settings["position"], h)
        self._window.setAlphaValue_(0.0)
        self._window.setFrameOrigin_(NSMakePoint(x, y - 12))
        self._window.orderFront_(None)
        self._last_toggle = time.monotonic()
        self._animating_show_hide = True
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.2)
        self._window.animator().setAlphaValue_(1.0)
        self._window.animator().setFrameOrigin_(NSMakePoint(x, y))
        NSAnimationContext.endGrouping()
        self._show_hide_proxy = ActionProxy.alloc().initWithCallback_(
            lambda g=generation: self._finish_show_animation(g)
        )
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.22, self._show_hide_proxy, b"invoke:", None, False
        )

    def show_in_place(self):
        self._show_hide_generation += 1
        generation = self._show_hide_generation
        frame = self._window.frame()
        target_x, target_y = frame.origin.x, frame.origin.y
        self._window.setAlphaValue_(0.0)
        self._window.setFrameOrigin_(NSMakePoint(target_x, target_y - 12))
        self._window.orderFront_(None)
        self._last_toggle = time.monotonic()
        self._animating_show_hide = True
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.2)
        self._window.animator().setAlphaValue_(1.0)
        self._window.animator().setFrameOrigin_(NSMakePoint(target_x, target_y))
        NSAnimationContext.endGrouping()
        self._show_hide_proxy = ActionProxy.alloc().initWithCallback_(
            lambda g=generation: self._finish_show_animation(g)
        )
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.22, self._show_hide_proxy, b"invoke:", None, False
        )

    def _max_list_height(self):
        visible_row_capacity = SHELF_MAX_VISIBLE_ITEMS * (SHELF_ITEM_HEIGHT + ITEM_GAP)
        return visible_row_capacity + SHELF_PADDING * 2 + SECTION_HEADER_HEIGHT

    def _apply_window_height(self, total_height, animated=False):
        frame = self._window.frame()
        old_top = frame.origin.y + frame.size.height
        window_height = total_height + TOAST_GUTTER_HEIGHT
        new_frame = NSMakeRect(frame.origin.x, old_top - window_height, SHELF_WIDTH, window_height)
        bg_frame = NSMakeRect(0, TOAST_GUTTER_HEIGHT, SHELF_WIDTH, total_height)
        header_frame = NSMakeRect(0, total_height - SHELF_HEADER_HEIGHT, SHELF_WIDTH, SHELF_HEADER_HEIGHT)
        scroll_frame = NSMakeRect(0, 0, SHELF_WIDTH, total_height - SHELF_HEADER_HEIGHT)

        if animated and not self._animating_show_hide:
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.15)
            self._window.animator().setFrame_display_(new_frame, True)
            self._bg.animator().setFrame_(bg_frame)
            self._header.animator().setFrame_(header_frame)
            self._scroll_view.animator().setFrame_(scroll_frame)
            NSAnimationContext.endGrouping()
        else:
            self._window.setFrame_display_(new_frame, True)
            self._bg.setFrame_(bg_frame)
            self._header.setFrame_(header_frame)
            self._scroll_view.setFrame_(scroll_frame)

    def _scroll_gap_into_view(self, y, height):
        target_y = max(0.0, y - ITEM_GAP)
        target_h = max(1.0, height + ITEM_GAP * 2)
        self._drop_view.scrollRectToVisible_(NSMakeRect(0, target_y, SHELF_WIDTH, target_h))

    def hide(self):
        self.hide_hover_preview()
        self._show_hide_generation += 1
        generation = self._show_hide_generation
        self._last_toggle = time.monotonic()
        self._animating_show_hide = True
        frame = self._window.frame()
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.2)
        self._window.animator().setAlphaValue_(0.0)
        self._window.animator().setFrameOrigin_(
            NSMakePoint(frame.origin.x, frame.origin.y - 12)
        )
        NSAnimationContext.endGrouping()
        self._show_hide_proxy = ActionProxy.alloc().initWithCallback_(
            lambda g=generation: self._finish_hide_animation(g)
        )
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.22, self._show_hide_proxy, b"invoke:", None, False
        )
        if self._shake_detector:
            self._shake_detector._cooldown_(3.0)

    def toggle(self):
        if self._window.isVisible():
            self.hide()
        else:
            self.show()

    def toggle_in_place(self):
        if self._window.isVisible():
            self.hide()
        else:
            self.show_in_place()

    def recently_toggled(self):
        return time.monotonic() - self._last_toggle < 1.0

    def _finish_show_animation(self, generation):
        if generation != self._show_hide_generation:
            return
        self._animating_show_hide = False

    def _finish_hide_animation(self, generation):
        if generation != self._show_hide_generation:
            return
        self._animating_show_hide = False
        self._window.orderOut_(None)
        frame = self._window.frame()
        self._window.setFrameOrigin_(NSMakePoint(frame.origin.x, frame.origin.y + 12))
        self._window.setAlphaValue_(1.0)

    def add_file(self, path):
        self.add_files([path])

    def add_files(self, paths, gap_idx=None):
        if self._clear_in_progress:
            return {"added_count": 0, "duplicate_paths": []}

        normalized = []
        seen_batch = set()
        for path in paths:
            if not path:
                continue
            normalized_path = normalize_shelf_path(path)
            identity = file_identity(normalized_path)
            if identity in seen_batch:
                continue
            seen_batch.add(identity)
            normalized.append((normalized_path, identity))

        existing_by_identity = {
            file_identity(existing_path): existing_path for existing_path in self._files
        }
        duplicate_paths = []
        duplicate_targets = []
        new_paths = []
        for path, identity in normalized:
            existing_path = existing_by_identity.get(identity)
            if existing_path is not None:
                duplicate_paths.append(path)
                duplicate_targets.append(existing_path)
            else:
                new_paths.append(path)
                existing_by_identity[identity] = path

        added_count = 0
        if new_paths:
            if gap_idx is not None and self._supports_drop_insertion_slot():
                if self._insert_files_at_drop_gap(new_paths, gap_idx):
                    added_count = len(new_paths)
            if added_count == 0:
                self._files.extend(new_paths)
                self._new_files = set(new_paths)
                self._refresh()
                self._new_files = set()
                added_count = len(new_paths)

        if duplicate_paths:
            self._focus_existing_path(duplicate_targets[0])
            if len(duplicate_paths) == 1:
                self.show_toast("Already on shelf", "duplicate")
            else:
                self.show_toast(f"{len(duplicate_paths)} files already on shelf", "duplicate")

        return {"added_count": added_count, "duplicate_paths": duplicate_paths}

    def should_draw_empty_hint(self):
        return not self._files and self._drop_indicator_view is None

    def _center_toast(self):
        """Position the toast centered horizontally in the gutter, behind the bg."""
        size = self._toast_view.frame().size
        x = (SHELF_WIDTH - size.width) / 2
        # Overlap 1px into the bg so the shelf border draws on top with no seam.
        y = TOAST_GUTTER_HEIGHT - size.height + 1
        self._toast_view.setFrame_(NSMakeRect(x, y, size.width, size.height))

    def _remove_file_indices(self, indices):
        removal = sorted({i for i in indices if 0 <= i < len(self._files)})
        if not removal:
            return []

        removed = set(removal)
        new_files = []
        new_pinned = set()
        new_selected = set()
        new_last_selected = None

        for old_index, path in enumerate(self._files):
            if old_index in removed:
                continue
            new_index = len(new_files)
            new_files.append(path)
            if old_index in self._pinned_indices:
                new_pinned.add(new_index)
            if old_index in self._selected_indices:
                new_selected.add(new_index)
            if old_index == self._last_selected_index:
                new_last_selected = new_index

        self._files = new_files
        self._pinned_indices = new_pinned
        self._selected_indices = new_selected
        self._last_selected_index = new_last_selected
        return removal

    def show_toast(self, message, style="celebrate", duration=TOAST_DURATION):
        self._toast_generation += 1
        generation = self._toast_generation
        self._toast_view.setMessage_style_(message, style)
        self._center_toast()
        self._toast_view.setAlphaValue_(0.0)
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(TOAST_SHOW_DURATION)
        self._toast_view.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()
        self._toast_view.play_pop_animation()
        self._toast_hide_proxy = ActionProxy.alloc().initWithCallback_(
            lambda current_generation=generation: self._hide_toast(current_generation)
        )
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            duration, self._toast_hide_proxy, b"invoke:", None, False
        )

    def _hide_toast(self, generation):
        if generation != self._toast_generation:
            return
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(TOAST_HIDE_DURATION)
        self._toast_view.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

    def _focus_existing_path(self, path):
        try:
            index = self._files.index(path)
        except ValueError:
            return
        section_key = self._section_key_for_index(index)
        if section_key in self._collapsed_sections:
            self._collapsed_sections.discard(section_key)
            self._refresh()
            try:
                index = self._files.index(path)
            except ValueError:
                return
        self._reveal_proxy = ActionProxy.alloc().initWithCallback_(
            lambda target_index=index: self._scroll_and_pulse_item(target_index)
        )
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            REVEAL_PULSE_DELAY, self._reveal_proxy, b"invoke:", None, False
        )

    def _section_key_for_index(self, index):
        if not (0 <= index < len(self._files)):
            return None
        if index in self._pinned_indices:
            return "Pinned"
        if not self._auto_organize:
            return None
        file_type = classify_file_type(self._files[index])
        for title, key in TYPE_SECTIONS:
            if key == file_type:
                return title
        return None

    def _scroll_and_pulse_item(self, index):
        item_view = next((iv for iv in self._item_views if iv._index == index), None)
        if item_view is None:
            return
        frame = item_view.frame()
        reveal_rect = NSMakeRect(
            0,
            max(0.0, frame.origin.y - ITEM_GAP * 2),
            SHELF_WIDTH,
            frame.size.height + ITEM_GAP * 4,
        )
        self._drop_view.scrollRectToVisible_(reveal_rect)
        self._scroll_view.reflectScrolledClipView_(self._scroll_view.contentView())
        item_view.pulse_attention()

    def _set_clear_button_enabled(self, enabled):
        self._clear_btn.setEnabled_(enabled)
        self._clear_btn.setAlphaValue_(1.0 if enabled else 0.55)

    def _supports_drop_insertion_slot(self):
        return (
            not self._clear_in_progress
            and not self._auto_organize
            and self._sort_order in {"date-added", "manual"}
            and not self._pinned_indices
        )

    def _insert_files_at_drop_gap(self, paths, gap_idx):
        if gap_idx is None or not self._supports_drop_insertion_slot() or not paths:
            return False

        ordered_paths = [self._files[i] for i in self._flat_visible_indices()]
        insert_at = max(0, min(gap_idx, len(ordered_paths)))
        self._files = ordered_paths[:insert_at] + list(paths) + ordered_paths[insert_at:]
        self._sort_order = "manual"
        if not self._apply_inserted_item_layout(insert_at, paths):
            self._new_files = set(paths)
            self._refresh()
            self._new_files = set()
        return True

    def remove_file(self, index):
        if self._clear_in_progress:
            return
        if 0 <= index < len(self._files):
            self._remove_file_indices([index])
            self._refresh()

    def clear_all(self):
        if self._clear_in_progress or not self._files:
            return
        self.hide_hover_preview()
        self.cancel_reorder()
        self._endDropAnimation()
        self._drop_highlight = False
        self._drop_view.setNeedsDisplay_(True)
        self._start_clear_all_animation()

    def _start_clear_all_animation(self):
        self._clear_in_progress = True
        self._set_clear_button_enabled(False)
        self._window.setIgnoresMouseEvents_(True)

        animated_views = [view for view in self._content_views if view.superview() is self._drop_view]
        if not animated_views:
            self._finish_clear_all_animation()
            return

        animated_views.sort(key=lambda view: (-view.frame().origin.y, view.frame().origin.x))
        self._clear_animation_proxies = []
        last_order = len(animated_views) - 1
        for order, view in enumerate(animated_views):
            is_last = order == last_order
            proxy = ActionProxy.alloc().initWithCallback_(
                lambda current=view, last=is_last: self._animate_clear_all_view(current, last)
            )
            self._clear_animation_proxies.append(proxy)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                order * CLEAR_ALL_STAGGER, proxy, b"invoke:", None, False
            )

    def _animate_clear_all_view(self, view, is_last=False):
        if not self._clear_in_progress or view.superview() is None:
            return

        is_header = isinstance(view, SectionHeaderView)
        target_frame = self._clear_target_frame(view.frame(), is_header)
        view.setWantsLayer_(True)
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(CLEAR_ALL_DURATION * (0.9 if is_header else 1.0))
        if is_last:
            ctx.setCompletionHandler_(self._finish_clear_all_animation)
        view.animator().setFrame_(target_frame)
        view.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

    def _clear_target_frame(self, frame, is_header):
        scale = 0.92 if is_header else 0.86
        drift_x = -10 if is_header else -18
        drift_y = 8 if is_header else 14
        target_w = max(24.0, frame.size.width * scale)
        target_h = max(12.0, frame.size.height * scale)
        center_x = frame.origin.x + frame.size.width / 2 + drift_x
        center_y = frame.origin.y + frame.size.height / 2 + drift_y
        return NSMakeRect(
            center_x - target_w / 2,
            center_y - target_h / 2,
            target_w,
            target_h,
        )

    def _finish_clear_all_animation(self):
        if not self._clear_in_progress:
            return

        self.hide_hover_preview()
        self.cancel_reorder()
        self._files.clear()
        self._pinned_indices.clear()
        self._selected_indices.clear()
        self._last_selected_index = None
        self._new_files = set()
        self._refresh()

        self._clear_in_progress = False
        self._clear_animation_proxies = []
        self._set_clear_button_enabled(True)
        self._window.setIgnoresMouseEvents_(False)
        self._drop_view.setNeedsDisplay_(True)
        self.show_toast("Shelf cleared", "celebrate")

    def can_reorder_items(self):
        return (
            not self._clear_in_progress
            and not self._auto_organize
            and self._sort_order in {"date-added", "manual"}
        )

    def point_is_inside_reorder_area(self, window_point):
        if self._clear_in_progress:
            return False
        local = self._scroll_view.convertPoint_fromView_(window_point, None)
        bounds = self._scroll_view.bounds()
        return 0 <= local.x <= bounds.size.width and 0 <= local.y <= bounds.size.height

    def begin_reorder(self, dragged_index, window_point):
        if not self.can_reorder_items():
            return
        visible = self._flat_visible_indices()
        if dragged_index not in visible:
            return
        dragged_pinned = dragged_index in self._pinned_indices
        self._reorder_dragged_index = dragged_index
        self._reorder_group_indices = [
            i for i in visible if (i in self._pinned_indices) == dragged_pinned
        ]
        group_views = [iv for iv in self._item_views if iv._index in self._reorder_group_indices]
        self._reorder_slot_frames = {iv._index: iv.frame() for iv in group_views}
        self._reorder_drag_view = next(
            (iv for iv in group_views if iv._index == dragged_index), None
        )
        if self._reorder_drag_view is not None:
            local = self._drop_view.convertPoint_fromView_(window_point, None)
            self._reorder_drag_offset_y = local.y - self._reorder_drag_view.frame().origin.y
            self._reorder_drag_view.setAlphaValue_(0.92)
            if self._reorder_drag_view.layer():
                self._reorder_drag_view.layer().setZPosition_(25)
                self._reorder_drag_view.layer().setShadowColor_(NSColor.blackColor().CGColor())
                self._reorder_drag_view.layer().setShadowOpacity_(0.22)
                self._reorder_drag_view.layer().setShadowRadius_(12)
                self._reorder_drag_view.layer().setShadowOffset_(NSMakeSize(0, -4))
        self._reorder_target_pos = self._reorder_group_indices.index(dragged_index)
        self._update_reorder_indicator(group_views)

    def update_reorder(self, window_point):
        if self._reorder_dragged_index is None or not self._reorder_group_indices:
            return False
        local = self._drop_view.convertPoint_fromView_(window_point, None)
        group_views = [iv for iv in self._item_views if iv._index in self._reorder_group_indices]
        if not group_views:
            return False

        target_pos = len(group_views)
        for pos, view in enumerate(group_views):
            snap_y = view.frame().origin.y + view.frame().size.height * 0.4
            if local.y < snap_y:
                target_pos = pos
                break
        self._reorder_target_pos = target_pos
        self._update_reorder_live_layout(local, group_views)
        self._update_reorder_indicator(group_views)
        return True

    def finish_reorder(self):
        if self._reorder_dragged_index is None or not self._reorder_group_indices:
            self.cancel_reorder()
            return

        group = list(self._reorder_group_indices)
        visible = self._flat_visible_indices()
        if self._reorder_dragged_index not in group or group[0] not in visible:
            self.cancel_reorder()
            return

        from_pos = group.index(self._reorder_dragged_index)
        to_pos = self._reorder_target_pos if self._reorder_target_pos is not None else from_pos
        to_pos = max(0, min(to_pos, len(group)))
        if to_pos > from_pos:
            to_pos -= 1

        if to_pos == from_pos:
            self.cancel_reorder()
            return

        group.pop(from_pos)
        group.insert(to_pos, self._reorder_dragged_index)

        start = visible.index(self._reorder_group_indices[0])
        end = start + len(self._reorder_group_indices)
        new_visible = visible[:start] + group + visible[end:]

        reordered = [(self._files[i], i in self._pinned_indices) for i in new_visible]
        self._files = [path for path, _ in reordered]
        self._pinned_indices = {i for i, (_, pinned) in enumerate(reordered) if pinned}
        self._sort_order = "manual"
        self.cancel_reorder(restore_frames=False)
        if not self._apply_reordered_item_layout(new_visible):
            self._refresh()

    def cancel_reorder(self, restore_frames=True):
        if restore_frames and self._reorder_slot_frames:
            for view in self._item_views:
                if view._index in self._reorder_slot_frames:
                    view.setFrame_(self._reorder_slot_frames[view._index])
        if self._reorder_drag_view is not None:
            self._reorder_drag_view.setAlphaValue_(1.0)
            if self._reorder_drag_view.layer():
                self._reorder_drag_view.layer().setZPosition_(0)
                self._reorder_drag_view.layer().setShadowOpacity_(0.0)
                self._reorder_drag_view.layer().setShadowRadius_(0.0)
        self._reorder_dragged_index = None
        self._reorder_drag_view = None
        self._reorder_slot_frames = {}
        self._reorder_drag_offset_y = 0.0
        self._reorder_group_indices = []
        self._reorder_target_pos = None
        self._reorder_indicator_y = None
        self._drop_view.setNeedsDisplay_(True)

    def _apply_reordered_item_layout(self, previous_indices):
        if self._auto_organize or len(previous_indices) != len(self._item_views):
            return False

        views_by_old_index = {view._index: view for view in self._item_views}
        ordered_views = []
        for old_index in previous_indices:
            view = views_by_old_index.get(old_index)
            if view is None:
                return False
            ordered_views.append(view)

        self.hide_hover_preview()
        self._selected_indices.clear()
        self._last_selected_index = None

        for view in ordered_views:
            view.removeFromSuperview()
            self._drop_view.addSubview_(view)

        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.08)
        y = SHELF_PADDING
        for new_index, view in enumerate(ordered_views):
            target_frame = NSMakeRect(
                SHELF_PADDING,
                y,
                SHELF_WIDTH - SHELF_PADDING * 2,
                SHELF_ITEM_HEIGHT,
            )
            view._index = new_index
            view._selected = False
            view.animator().setFrame_(target_frame)
            view.animator().setAlphaValue_(1.0)
            view.setNeedsDisplay_(True)
            y += SHELF_ITEM_HEIGHT + ITEM_GAP
        NSAnimationContext.endGrouping()

        self._item_views = ordered_views
        self._content_views = list(ordered_views)
        self._update_count_label()
        self._drop_view.setNeedsDisplay_(True)
        return True

    def _apply_inserted_item_layout(self, insert_at, new_paths):
        if (
            self._auto_organize
            or self._pinned_indices
            or len(self._content_views) != len(self._item_views)
            or insert_at < 0
            or insert_at > len(self._item_views)
        ):
            return False

        existing_views = list(self._item_views)
        inserted_views = []
        for offset, path in enumerate(new_paths):
            view = ShelfItemView.make_item(path, insert_at + offset, self.remove_file, self)
            view.setWantsLayer_(True)
            inserted_views.append(view)

        ordered_views = existing_views[:insert_at] + inserted_views + existing_views[insert_at:]
        self.hide_hover_preview()
        self._selected_indices.clear()
        self._last_selected_index = None
        self._update_count_label()

        rows = self._build_render_rows()
        total_height = (
            160
            if not self._files
            else SHELF_HEADER_HEIGHT + min(self._content_height_for_rows(rows), self._max_list_height())
        )
        self._apply_window_height(total_height)

        document_height = max(total_height - SHELF_HEADER_HEIGHT, self._content_height_for_rows(rows))
        self._drop_view.setFrame_(NSMakeRect(0, 0, SHELF_WIDTH, document_height))

        for view in existing_views:
            view.removeFromSuperview()

        y = SHELF_PADDING
        for new_index, view in enumerate(ordered_views):
            view._index = new_index
            view._selected = False
            if view in inserted_views:
                view.setFrame_(
                    NSMakeRect(
                        SHELF_PADDING,
                        y + 12,
                        SHELF_WIDTH - SHELF_PADDING * 2,
                        SHELF_ITEM_HEIGHT,
                    )
                )
                view.setAlphaValue_(0.0)
            self._drop_view.addSubview_(view)
            y += SHELF_ITEM_HEIGHT + ITEM_GAP

        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.12)
        y = SHELF_PADDING
        for view in ordered_views:
            target_frame = NSMakeRect(
                SHELF_PADDING,
                y,
                SHELF_WIDTH - SHELF_PADDING * 2,
                SHELF_ITEM_HEIGHT,
            )
            view.animator().setFrame_(target_frame)
            view.animator().setAlphaValue_(1.0)
            view.setNeedsDisplay_(True)
            y += SHELF_ITEM_HEIGHT + ITEM_GAP
        NSAnimationContext.endGrouping()

        self._item_views = ordered_views
        self._content_views = list(ordered_views)
        self._drop_view.setNeedsDisplay_(True)
        return True

    def _flat_visible_indices(self):
        return [row["index"] for row in self._build_render_rows() if row["kind"] == "item"]

    def _update_reorder_indicator(self, group_views=None):
        if self._reorder_dragged_index is None or self._reorder_target_pos is None:
            self._reorder_indicator_y = None
            self._drop_view.setNeedsDisplay_(True)
            return
        if group_views is None:
            group_views = [iv for iv in self._item_views if iv._index in self._reorder_group_indices]
        if not group_views:
            self._reorder_indicator_y = None
            self._drop_view.setNeedsDisplay_(True)
            return

        target_pos = max(0, min(self._reorder_target_pos, len(group_views)))
        if target_pos == len(group_views):
            last = group_views[-1].frame()
            y = last.origin.y + last.size.height + ITEM_GAP / 2
        else:
            frame = group_views[target_pos].frame()
            y = frame.origin.y - ITEM_GAP / 2
        self._reorder_indicator_y = y
        self._drop_view.setNeedsDisplay_(True)

    def _update_reorder_live_layout(self, local_point, group_views):
        if self._reorder_drag_view is None:
            return

        dragged_index = self._reorder_dragged_index
        group = list(self._reorder_group_indices)
        from_pos = group.index(dragged_index)
        to_pos = max(
            0,
            min(
                self._reorder_target_pos if self._reorder_target_pos is not None else from_pos,
                len(group),
            ),
        )
        if to_pos > from_pos:
            to_pos -= 1
        group.pop(from_pos)
        group.insert(to_pos, dragged_index)

        slot_frames = [self._reorder_slot_frames[idx] for idx in self._reorder_group_indices]
        for slot_pos, idx in enumerate(group):
            if idx == dragged_index:
                continue
            target_frame = slot_frames[slot_pos]
            for view in group_views:
                if view._index == idx:
                    view.setFrame_(target_frame)
                    view.setAlphaValue_(1.0)
                    break

        first_slot = slot_frames[0]
        last_slot = slot_frames[-1]
        min_y = first_slot.origin.y - 6
        max_y = last_slot.origin.y + 6
        drag_y = min(max(local_point.y - self._reorder_drag_offset_y, min_y), max_y)
        base_frame = self._reorder_slot_frames[dragged_index]
        self._reorder_drag_view.setFrame_(
            NSMakeRect(
                base_frame.origin.x - 4,
                drag_y - 3,
                base_frame.size.width + 8,
                base_frame.size.height + 6,
            )
        )

    def _beginDropAnimation(self, window_point):
        if not self._supports_drop_insertion_slot():
            self._drop_highlight = True
            self._drop_view.setNeedsDisplay_(True)
            return
        if self._drop_indicator_view is not None:
            self._updateDropAnimation(window_point)
            return
        self._pre_drop_content_frames = {}
        for cv in self._content_views:
            self._pre_drop_content_frames[id(cv)] = cv.frame()
        self._pre_drop_doc_height = self._drop_view.frame().size.height
        self._pre_drop_window_height = self._window.frame().size.height - TOAST_GUTTER_HEIGHT
        self._pre_drop_scroll_origin_y = self._scroll_view.contentView().bounds().origin.y
        self._drop_indicator_view = DropPlaceholderView.make_placeholder()
        self._drop_indicator_view.setWantsLayer_(True)
        self._drop_indicator_view.setAlphaValue_(0.0)
        self._drop_view.addSubview_(self._drop_indicator_view)
        self._drop_gap_index = None
        self._updateDropAnimation(window_point)

    def _updateDropAnimation(self, window_point):
        if not self._supports_drop_insertion_slot() or self._drop_indicator_view is None:
            return
        local = self._drop_view.convertPoint_fromView_(window_point, None)
        gap_index = len(self._item_views)
        for pos, iv in enumerate(self._item_views):
            orig = self._pre_drop_content_frames.get(id(iv), iv.frame())
            mid_y = orig.origin.y + orig.size.height / 2
            if local.y < mid_y:
                gap_index = pos
                break
        if gap_index == self._drop_gap_index:
            return
        self._drop_gap_index = gap_index
        gap_h = SHELF_ITEM_HEIGHT + ITEM_GAP
        if not self._item_views:
            placeholder_y = SHELF_PADDING
        elif gap_index < len(self._item_views):
            orig = self._pre_drop_content_frames.get(id(self._item_views[gap_index]))
            placeholder_y = orig.origin.y if orig else SHELF_PADDING
        else:
            last_iv = self._item_views[-1]
            orig = self._pre_drop_content_frames.get(id(last_iv), last_iv.frame())
            placeholder_y = orig.origin.y + orig.size.height + ITEM_GAP
        new_doc_h = (self._pre_drop_doc_height or 160) + gap_h
        visible_list_h = min(new_doc_h, self._max_list_height())
        self._apply_window_height(SHELF_HEADER_HEIGHT + visible_list_h)
        self._drop_view.setFrameSize_(NSMakeSize(SHELF_WIDTH, max(new_doc_h, visible_list_h)))
        context_h = SHELF_ITEM_HEIGHT
        if gap_index < len(self._item_views):
            context_h += ITEM_GAP + SHELF_ITEM_HEIGHT
        self._scroll_gap_into_view(placeholder_y, context_h)
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(0.2)
        ctx.setAllowsImplicitAnimation_(True)
        try:
            CAMediaTimingFunction = objc.lookUpClass("CAMediaTimingFunction")
            ctx.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeInEaseOut"))
        except Exception:
            pass
        self._drop_indicator_view.animator().setFrame_(
            NSMakeRect(
                SHELF_PADDING,
                placeholder_y,
                SHELF_WIDTH - SHELF_PADDING * 2,
                SHELF_ITEM_HEIGHT,
            )
        )
        self._drop_indicator_view.animator().setAlphaValue_(1.0)
        for cv in self._content_views:
            orig = self._pre_drop_content_frames.get(id(cv))
            if orig is None:
                continue
            if orig.origin.y >= placeholder_y:
                cv.animator().setFrameOrigin_(NSMakePoint(orig.origin.x, orig.origin.y + gap_h))
            else:
                cv.animator().setFrameOrigin_(NSMakePoint(orig.origin.x, orig.origin.y))
        NSAnimationContext.endGrouping()

    def _endDropAnimation(self):
        if not self._supports_drop_insertion_slot():
            self._drop_highlight = False
            self._drop_view.setNeedsDisplay_(True)
            return
        if self._drop_indicator_view is not None:
            indicator = self._drop_indicator_view
            self._drop_indicator_view = None
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.1)
            indicator.animator().setAlphaValue_(0.0)
            NSAnimationContext.endGrouping()
            self._end_drop_indicator_proxy = ActionProxy.alloc().initWithCallback_(
                lambda v=indicator: v.removeFromSuperview()
            )
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.12, self._end_drop_indicator_proxy, b"invoke:", None, False
            )
        if self._pre_drop_content_frames:
            NSAnimationContext.beginGrouping()
            ctx = NSAnimationContext.currentContext()
            ctx.setDuration_(0.15)
            try:
                CAMediaTimingFunction = objc.lookUpClass("CAMediaTimingFunction")
                ctx.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeInEaseOut"))
            except Exception:
                pass
            for cv in self._content_views:
                orig = self._pre_drop_content_frames.get(id(cv))
                if orig:
                    cv.animator().setFrame_(orig)
            NSAnimationContext.endGrouping()
        if self._pre_drop_window_height is not None:
            self._apply_window_height(self._pre_drop_window_height)
        if self._pre_drop_doc_height is not None:
            self._drop_view.setFrameSize_(NSMakeSize(SHELF_WIDTH, self._pre_drop_doc_height))
        clip = self._scroll_view.contentView()
        visible_h = clip.bounds().size.height
        max_origin_y = max(0.0, self._drop_view.frame().size.height - visible_h)
        restored_origin_y = max(0.0, min(self._pre_drop_scroll_origin_y, max_origin_y))
        clip.scrollToPoint_(NSMakePoint(0, restored_origin_y))
        self._scroll_view.reflectScrolledClipView_(clip)
        self._drop_gap_index = None
        self._pre_drop_content_frames = {}
        self._pre_drop_doc_height = None
        self._pre_drop_window_height = None
        self._pre_drop_scroll_origin_y = 0.0
        self._drop_view.setNeedsDisplay_(True)

    def show_hover_preview(self, item_view):
        if self._hover_preview_owner is item_view and self._hover_preview_window is not None:
            return
        self.hide_hover_preview()

        preview_w = 240
        preview_h = 300
        card_w = preview_w + 12
        card_h = preview_h + 12
        thumb_rect = item_view.convertRect_toView_(item_view._thumb_frame, None)
        thumb_rect = self._window.convertRectToScreen_(thumb_rect)
        visible = (
            self._window.screen().visibleFrame()
            if self._window.screen()
            else NSScreen.mainScreen().visibleFrame()
        )
        x = max(visible.origin.x + 14, self._window.frame().origin.x - card_w - 16)
        centered_y = thumb_rect.origin.y + (thumb_rect.size.height / 2) - (card_h / 2)
        min_y = visible.origin.y + 14
        max_y = visible.origin.y + visible.size.height - card_h - 14
        y = min(max(centered_y, min_y), max_y)

        preview_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, card_w, card_h),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        preview_window.setLevel_(NSFloatingWindowLevel)
        preview_window.setOpaque_(False)
        preview_window.setBackgroundColor_(NSColor.clearColor())
        preview_window.setHasShadow_(False)
        preview_window.setIgnoresMouseEvents_(True)
        preview_window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

        content = preview_window.contentView()
        content.setWantsLayer_(True)

        card = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, card_h))
        card.setWantsLayer_(True)
        card.layer().setCornerRadius_(16)
        card.layer().setBorderWidth_(1.0)
        card.layer().setBorderColor_(
            NSColor.whiteColor().colorWithAlphaComponent_(0.18).CGColor()
        )
        card.layer().setBackgroundColor_(
            NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.92).CGColor()
        )
        card.layer().setShadowColor_(NSColor.blackColor().CGColor())
        card.layer().setShadowOpacity_(0.28)
        card.layer().setShadowRadius_(14)
        card.layer().setShadowOffset_(NSMakeSize(0, -4))

        image_view = NSImageView.alloc().initWithFrame_(NSMakeRect(6, 6, preview_w, preview_h))
        image_view.setImage_(get_file_thumbnail(item_view._file_path, max(preview_w, preview_h)))
        image_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        image_view.setWantsLayer_(True)
        image_view.layer().setCornerRadius_(12)
        image_view.layer().setMasksToBounds_(True)
        card.addSubview_(image_view)

        content.addSubview_(card)
        preview_window.setAlphaValue_(0.0)
        preview_window.orderFront_(None)
        self._hover_preview_window = preview_window
        self._hover_preview_owner = item_view
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.18)
        preview_window.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()
        try:
            CASpringAnimation = objc.lookUpClass("CASpringAnimation")
            spring = CASpringAnimation.animationWithKeyPath_("transform.scale")
            spring.setFromValue_(0.95)
            spring.setToValue_(1.0)
            spring.setDamping_(12)
            spring.setInitialVelocity_(0)
            spring.setDuration_(0.18)
            content.layer().addAnimation_forKey_(spring, "previewReveal")
        except Exception:
            try:
                CABasicAnimation = objc.lookUpClass("CABasicAnimation")
                anim = CABasicAnimation.animationWithKeyPath_("transform.scale")
                anim.setFromValue_(0.95)
                anim.setToValue_(1.0)
                anim.setDuration_(0.18)
                content.layer().addAnimation_forKey_(anim, "previewReveal")
            except Exception:
                pass

    def hide_hover_preview(self, owner=None):
        if owner is not None and self._hover_preview_owner is not owner:
            return
        if self._hover_preview_window is not None:
            window = self._hover_preview_window
            self._hover_preview_window = None
            self._hover_preview_owner = None
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.1)
            window.animator().setAlphaValue_(0.0)
            NSAnimationContext.endGrouping()
            self._hide_preview_proxy = ActionProxy.alloc().initWithCallback_(
                lambda w=window: w.orderOut_(None)
            )
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.12, self._hide_preview_proxy, b"invoke:", None, False
            )
        else:
            self._hover_preview_owner = None

    def _refresh(self):
        self._window.disableScreenUpdatesUntilFlush()
        self.hide_hover_preview()

        self._selected_indices.clear()
        self._last_selected_index = None

        for view in self._content_views:
            view.removeFromSuperview()
        self._item_views.clear()
        self._content_views.clear()

        n = len(self._files)
        self._update_count_label()

        rows = self._build_render_rows()
        if n == 0:
            ch = 160
            # Instant resize when going empty — the clear-all animation
            # already provided the transition, and an animated resize
            # here would leave stale scroll/geometry state.
            self._apply_window_height(ch, animated=False)
            self._scroll_view.contentView().scrollToPoint_(NSMakePoint(0, 0))
            self._scroll_view.reflectScrolledClipView_(self._scroll_view.contentView())
        else:
            ch = SHELF_HEADER_HEIGHT + min(
                self._content_height_for_rows(rows), self._max_list_height()
            )
            self._apply_window_height(ch, animated=True)

        dh = ch - SHELF_HEADER_HEIGHT

        to_animate = []
        content_h = max(dh, self._content_height_for_rows(rows))
        self._drop_view.setFrame_(NSMakeRect(0, 0, SHELF_WIDTH, content_h))
        y = SHELF_PADDING
        for row in rows:
            if row["kind"] == "section":
                header = SectionHeaderView.make_header(
                    row["title"],
                    row["color"],
                    row.get("collapsed", False),
                    lambda section_key=row["key"]: self._toggleSection(section_key),
                    self,
                )
                header.setFrame_(
                    NSMakeRect(
                        SHELF_PADDING,
                        y,
                        SHELF_WIDTH - SHELF_PADDING * 2,
                        SECTION_HEADER_HEIGHT,
                    )
                )
                self._drop_view.addSubview_(header)
                self._content_views.append(header)
                y += SECTION_HEADER_HEIGHT + SECTION_GAP
                continue

            real_idx = row["index"]
            fp = self._files[real_idx]
            iv = ShelfItemView.make_item(fp, real_idx, self.remove_file, self)
            final_frame = NSMakeRect(
                SHELF_PADDING,
                y,
                SHELF_WIDTH - SHELF_PADDING * 2,
                SHELF_ITEM_HEIGHT,
            )
            iv.setWantsLayer_(True)

            if fp in self._new_files:
                iv.setFrame_(
                    NSMakeRect(
                        SHELF_PADDING,
                        y + 12,
                        SHELF_WIDTH - SHELF_PADDING * 2,
                        SHELF_ITEM_HEIGHT,
                    )
                )
                iv.setAlphaValue_(0.0)
                to_animate.append((iv, final_frame))
            else:
                iv.setFrame_(final_frame)

            self._drop_view.addSubview_(iv)
            self._item_views.append(iv)
            self._content_views.append(iv)
            y += SHELF_ITEM_HEIGHT + ITEM_GAP

        if to_animate:
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(0.25)
            for iv, target in to_animate:
                iv.animator().setFrame_(target)
                iv.animator().setAlphaValue_(1.0)
            NSAnimationContext.endGrouping()

        self._drop_view.setNeedsDisplay_(True)

    def _flashDropHighlight(self):
        self._drop_highlight = True
        self._drop_view.setNeedsDisplay_(True)
        self._highlight_proxy = ActionProxy.alloc().initWithCallback_(self._clearDropHighlight)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self._highlight_proxy, b"invoke:", None, False
        )

    def _clearDropHighlight(self):
        self._drop_highlight = False
        self._drop_view.setNeedsDisplay_(True)

    def _showSortMenu(self):
        menu = NSMenu.alloc().init()
        self._sort_proxies = []
        for label, key in [
            ("Manual", "manual"),
            ("Name", "name"),
            ("File Size", "size"),
            ("Date Added", "date-added"),
        ]:
            px = ActionProxy.alloc().initWithCallback_(lambda k=key: self._setSortOrder(k))
            self._sort_proxies.append(px)
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, b"invoke:", "")
            mi.setTarget_(px)
            if key == self._sort_order:
                mi.setState_(NSOnState)
            menu.addItem_(mi)
        menu.addItem_(NSMenuItem.separatorItem())
        px = ActionProxy.alloc().initWithCallback_(self._toggleAutoOrganize)
        self._sort_proxies.append(px)
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Auto-organize", b"invoke:", "")
        mi.setTarget_(px)
        mi.setState_(NSOnState if self._auto_organize else NSOffState)
        menu.addItem_(mi)
        loc = self._sort_btn.convertPoint_toView_(NSMakePoint(0, 0), None)
        menu.popUpMenuPositioningItem_atLocation_inView_(None, loc, self._header)

    def _setSortOrder(self, order):
        self._sort_order = order
        self.cancel_reorder()
        self._refresh()

    def _toggleAutoOrganize(self):
        self._auto_organize = not self._auto_organize
        self._settings["auto_organize"] = self._auto_organize
        save_settings(self._settings)
        self._refresh()

    def _toggleSection(self, section_key):
        if section_key in self._collapsed_sections:
            self._collapsed_sections.discard(section_key)
        else:
            self._collapsed_sections.add(section_key)
        self._refresh()

    def _sorted_indices(self, indices):
        indices = list(indices)
        if self._sort_order == "manual":
            return indices
        if self._sort_order == "name":
            indices.sort(key=lambda i: os.path.basename(self._files[i]).lower())
        elif self._sort_order == "size":

            def safe_size(i):
                return get_file_size_bytes(self._files[i])

            indices.sort(key=safe_size, reverse=True)
        else:
            indices.sort(reverse=True)
        return indices

    def _build_render_rows(self):
        indices = list(range(len(self._files)))
        pinned = self._sorted_indices([i for i in indices if i in self._pinned_indices])
        unpinned = self._sorted_indices([i for i in indices if i not in self._pinned_indices])

        rows = []
        if self._auto_organize:
            if pinned:
                is_collapsed = "Pinned" in self._collapsed_sections
                rows.append(
                    {
                        "kind": "section",
                        "key": "Pinned",
                        "title": "Pinned",
                        "color": SECTION_COLORS["Pinned"],
                        "collapsed": is_collapsed,
                    }
                )
                if not is_collapsed:
                    rows.extend({"kind": "item", "index": i} for i in pinned)

            grouped = {key: [] for _, key in TYPE_SECTIONS}
            for idx in unpinned:
                grouped[classify_file_type(self._files[idx])].append(idx)

            for title, key in TYPE_SECTIONS:
                if grouped[key]:
                    is_collapsed = title in self._collapsed_sections
                    rows.append(
                        {
                            "kind": "section",
                            "key": title,
                            "title": title,
                            "color": SECTION_COLORS[title],
                            "collapsed": is_collapsed,
                        }
                    )
                    if not is_collapsed:
                        rows.extend({"kind": "item", "index": i} for i in grouped[key])
            return rows

        ordered = pinned + unpinned
        for idx in ordered:
            rows.append({"kind": "item", "index": idx})
        return rows

    def _content_height_for_rows(self, rows):
        if not rows:
            return 0
        height = SHELF_PADDING * 2
        for row in rows:
            if row["kind"] == "section":
                height += SECTION_HEADER_HEIGHT + SECTION_GAP
            elif row["kind"] == "placeholder":
                height += SHELF_ITEM_HEIGHT + ITEM_GAP
            else:
                height += SHELF_ITEM_HEIGHT + ITEM_GAP
        return height

    def _visible_selection_range(self, start_index, end_index):
        visible = self._flat_visible_indices()
        positions = {idx: pos for pos, idx in enumerate(visible)}
        if start_index not in positions or end_index not in positions:
            return None
        lo = min(positions[start_index], positions[end_index])
        hi = max(positions[start_index], positions[end_index])
        return visible[lo : hi + 1]

    def toggle_selection(self, index, shift_held):
        if shift_held and self._last_selected_index is not None:
            range_indices = self._visible_selection_range(self._last_selected_index, index)
            if range_indices is None:
                lo = min(self._last_selected_index, index)
                hi = max(self._last_selected_index, index)
                range_indices = range(lo, hi + 1)
            for i in range_indices:
                self._selected_indices.add(i)
        else:
            if index in self._selected_indices:
                self._selected_indices.discard(index)
            else:
                self._selected_indices.add(index)
        self._last_selected_index = index
        self._update_selection_visuals()

    def _update_selection_visuals(self):
        for iv in self._item_views:
            iv._selected = iv._index in self._selected_indices
            iv.setNeedsDisplay_(True)
        self._update_count_label()

    def _update_count_label(self):
        n = len(self._files)
        sel = len(self._selected_indices)
        if sel > 0:
            sel_bytes = 0
            for i in self._selected_indices:
                if 0 <= i < n:
                    try:
                        sel_bytes += os.path.getsize(self._files[i])
                    except OSError:
                        pass
            text = f"{sel} selected · {human_readable_size(sel_bytes)}"
        else:
            total_bytes = 0
            for fp in self._files:
                try:
                    total_bytes += os.path.getsize(fp)
                except OSError:
                    pass
            text = f"{n} item{'s' if n != 1 else ''}"
            if total_bytes > 0:
                text += f" · {human_readable_size(total_bytes)}"
        self._count_label.setStringValue_(text)
