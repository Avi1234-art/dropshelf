import math
import os
import subprocess
import threading

import objc
from AppKit import (
    NSAttributedString,
    NSBezierPath,
    NSButton,
    NSColor,
    NSCursor,
    NSDragOperationCopy,
    NSDragOperationDelete,
    NSDragOperationMove,
    NSDragOperationNone,
    NSDraggingItem,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPasteboardTypeFileURL,
    NSScrollView,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingEnabledDuringMouseDrag,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSTextField,
    NSView,
    NSWorkspace,
    NSAnimationContext,
)
from Foundation import NSMakePoint, NSMakeSize, NSMutableDictionary, NSObject, NSTimer, NSURL

from .constants import (
    DRAG_THRESHOLD,
    ITEM_GAP,
    MARQUEE_EDGE_PAUSE,
    MARQUEE_POINTS_PER_SECOND,
    MARQUEE_RETURN_DURATION,
    MARQUEE_START_DELAY,
    PREVIEW_SIZE,
    REORDER_DRAG_THRESHOLD,
    REORDER_VERTICAL_BIAS,
    SECTION_HEADER_HEIGHT,
    SHELF_ITEM_HEIGHT,
    SHELF_PADDING,
    SHELF_WIDTH,
    TOAST_BODY_HEIGHT,
    TOAST_MIN_WIDTH,
    TOAST_SHELF_OVERLAP,
    TOAST_TEXT_PADDING,
    TOAST_TEXT_VERTICAL_OFFSET,
    TOAST_WINDOW_TOP_INSET,
)
from .file_utils import (
    describe_file_location,
    get_file_icon,
    get_file_size_bytes,
    get_file_thumbnail,
    human_readable_size,
    size_badge_style,
)


class ActionProxy(NSObject):
    def initWithCallback_(self, callback):
        self = objc.super(ActionProxy, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    @objc.typedSelector(b"v@:@")
    def invoke_(self, sender):
        self._callback()


class SectionHeaderView(NSView):
    @classmethod
    def make_header(cls, title, color, collapsed, toggle_callback, shelf_window):
        view = cls.alloc().initWithFrame_(
            NSMakeRect(0, 0, SHELF_WIDTH - SHELF_PADDING * 2, SECTION_HEADER_HEIGHT)
        )
        view._title = title
        view._color = color
        view._collapsed = collapsed
        view._hovered = False
        view._toggle_callback = toggle_callback
        view._shelf_window = shelf_window
        view._setup_ui()
        return view

    def isFlipped(self):
        return True

    def mouseDownCanMoveWindow(self):
        return False

    def _setup_ui(self):
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(11, 0.45)
        attrs[NSForegroundColorAttributeName] = self._color
        display_title = self._display_title()
        title = NSAttributedString.alloc().initWithString_attributes_(display_title, attrs)
        size = title.size()
        self._label_width = size.width

        label = NSTextField.labelWithString_(display_title)
        label.setFrame_(NSMakeRect((self.bounds().size.width - size.width) / 2, 4, size.width, 16))
        label.setFont_(NSFont.systemFontOfSize_weight_(11, 0.45))
        label.setTextColor_(self._color)
        label.setAlignment_(2)
        label.setDrawsBackground_(False)
        label.setBezeled_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        self.addSubview_(label)
        self._label = label

    def _display_title(self):
        return f"{self._title.upper()} {'▸' if self._collapsed else '▾'}"

    def drawRect_(self, rect):
        color = self._color.colorWithAlphaComponent_(0.7 if self._hovered else 0.45)
        color.set()
        y = self.bounds().size.height / 2 + 1
        gap = 10
        left_end = (self.bounds().size.width - self._label_width) / 2 - gap
        right_start = (self.bounds().size.width + self._label_width) / 2 + gap

        left = NSBezierPath.bezierPath()
        left.moveToPoint_(NSMakePoint(0, y))
        left.lineToPoint_(NSMakePoint(max(left_end, 0), y))
        left.setLineWidth_(1.5)
        left.stroke()

        right = NSBezierPath.bezierPath()
        right.moveToPoint_(NSMakePoint(min(right_start, self.bounds().size.width), y))
        right.lineToPoint_(NSMakePoint(self.bounds().size.width, y))
        right.setLineWidth_(1.5)
        right.stroke()

    def mouseEntered_(self, event):
        if getattr(self._shelf_window, "_clear_in_progress", False):
            return
        self._hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        if getattr(self._shelf_window, "_clear_in_progress", False):
            return
        self._hovered = False
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if getattr(self._shelf_window, "_clear_in_progress", False):
            return
        self._toggle_callback()

    def updateTrackingAreas(self):
        if hasattr(self, "_tracking_area"):
            self.removeTrackingArea_(self._tracking_area)
        self._tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking_area)
        objc.super(SectionHeaderView, self).updateTrackingAreas()


class DropPlaceholderView(NSView):
    @classmethod
    def make_placeholder(cls):
        return cls.alloc().initWithFrame_(
            NSMakeRect(0, 0, SHELF_WIDTH - SHELF_PADDING * 2, SHELF_ITEM_HEIGHT)
        )

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        bounds = self.bounds()
        card_rect = NSMakeRect(
            1,
            1,
            max(0, bounds.size.width - 2),
            max(0, bounds.size.height - 2),
        )
        fill = NSColor.systemBlueColor().colorWithAlphaComponent_(0.07)
        fill.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(card_rect, 14, 14).fill()

        stroke = NSColor.systemBlueColor().colorWithAlphaComponent_(0.8)
        stroke.set()
        guide = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(card_rect, 14, 14)
        guide.setLineWidth_(2.0)
        guide.setLineDash_count_phase_([7.0, 5.0], 2, 0.0)
        guide.stroke()

        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(14, 0.3)
        attrs[NSForegroundColorAttributeName] = NSColor.systemBlueColor().colorWithAlphaComponent_(0.95)
        text = NSAttributedString.alloc().initWithString_attributes_("Drop files here", attrs)
        size = text.size()
        text.drawAtPoint_(
            NSMakePoint(
                (bounds.size.width - size.width) / 2,
                (bounds.size.height - size.height) / 2,
            )
        )


class ToastBannerView(NSView):
    @classmethod
    def make_toast(cls):
        total_height = TOAST_WINDOW_TOP_INSET + TOAST_BODY_HEIGHT
        view = cls.alloc().initWithFrame_(NSMakeRect(0, 0, 220, total_height))
        view.setWantsLayer_(True)
        view._style = "celebrate"
        view._attachment = "below"
        view._style_colors = {}
        view._message = ""
        view._font = NSFont.systemFontOfSize_weight_(12, 0.48)
        view._text_size = NSMakeSize(0, 0)
        view._apply_style("celebrate")
        return view

    def isFlipped(self):
        return True

    def hitTest_(self, point):
        return None

    def setAttachment_(self, attachment):
        attachment = attachment if attachment in {"above", "below"} else "below"
        if self._attachment == attachment:
            return
        self._attachment = attachment
        self.setNeedsDisplay_(True)

    def _body_rect(self):
        return NSMakeRect(
            1,
            TOAST_WINDOW_TOP_INSET,
            max(0, self.bounds().size.width - 2),
            max(0, TOAST_BODY_HEIGHT - 1),
        )

    def _body_fill_path(self, body_rect, radius):
        left = body_rect.origin.x
        top = body_rect.origin.y
        right = body_rect.origin.x + body_rect.size.width
        bottom = body_rect.origin.y + body_rect.size.height
        radius = max(0, min(radius, body_rect.size.width / 2, body_rect.size.height))

        path = NSBezierPath.bezierPath()
        if self._attachment == "above":
            # Rounded top corners (away from shelf), flat bottom
            path.moveToPoint_(NSMakePoint(left, bottom))
            path.lineToPoint_(NSMakePoint(right, bottom))
            path.lineToPoint_(NSMakePoint(right, top + radius))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(right, top),
                NSMakePoint(right - radius, top),
                radius,
            )
            path.lineToPoint_(NSMakePoint(left + radius, top))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(left, top),
                NSMakePoint(left, top + radius),
                radius,
            )
            path.lineToPoint_(NSMakePoint(left, bottom))
        else:
            # Rounded bottom corners (away from shelf), flat top
            path.moveToPoint_(NSMakePoint(left, top))
            path.lineToPoint_(NSMakePoint(right, top))
            path.lineToPoint_(NSMakePoint(right, bottom - radius))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(right, bottom),
                NSMakePoint(right - radius, bottom),
                radius,
            )
            path.lineToPoint_(NSMakePoint(left + radius, bottom))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(left, bottom),
                NSMakePoint(left, bottom - radius),
                radius,
            )
            path.lineToPoint_(NSMakePoint(left, top))
        path.closePath()
        return path

    def _body_outline_path(self, body_rect, radius):
        left = body_rect.origin.x
        top = body_rect.origin.y
        right = body_rect.origin.x + body_rect.size.width
        bottom = body_rect.origin.y + body_rect.size.height
        radius = max(0, min(radius, body_rect.size.width / 2, body_rect.size.height))

        path = NSBezierPath.bezierPath()
        if self._attachment == "above":
            # U-shape opening at the bottom (toward shelf)
            path.moveToPoint_(NSMakePoint(left, bottom))
            path.lineToPoint_(NSMakePoint(left, top + radius))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(left, top),
                NSMakePoint(left + radius, top),
                radius,
            )
            path.lineToPoint_(NSMakePoint(right - radius, top))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(right, top),
                NSMakePoint(right, top + radius),
                radius,
            )
            path.lineToPoint_(NSMakePoint(right, bottom))
        else:
            # U-shape opening at the top (toward shelf)
            path.moveToPoint_(NSMakePoint(left, top))
            path.lineToPoint_(NSMakePoint(left, bottom - radius))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(left, bottom),
                NSMakePoint(left + radius, bottom),
                radius,
            )
            path.lineToPoint_(NSMakePoint(right - radius, bottom))
            path.appendBezierPathWithArcFromPoint_toPoint_radius_(
                NSMakePoint(right, bottom),
                NSMakePoint(right, bottom - radius),
                radius,
            )
            path.lineToPoint_(NSMakePoint(right, top))
        return path

    def _apply_style(self, style):
        self._style = style
        palette = {
            "duplicate": {
                "text": NSColor.colorWithRed_green_blue_alpha_(1.0, 0.73, 0.38, 0.98),
                "shadow": NSColor.colorWithRed_green_blue_alpha_(0.78, 0.28, 0.17, 0.55),
                "fill": NSColor.colorWithRed_green_blue_alpha_(0.14, 0.11, 0.10, 0.95),
                "stroke": NSColor.colorWithRed_green_blue_alpha_(1.0, 0.73, 0.38, 0.28),
                "highlight": NSColor.colorWithRed_green_blue_alpha_(1.0, 0.83, 0.64, 0.12),
            },
            "celebrate": {
                "text": NSColor.colorWithRed_green_blue_alpha_(0.42, 0.93, 0.78, 0.98),
                "shadow": NSColor.colorWithRed_green_blue_alpha_(0.12, 0.46, 0.88, 0.5),
                "fill": NSColor.colorWithRed_green_blue_alpha_(0.09, 0.13, 0.13, 0.95),
                "stroke": NSColor.colorWithRed_green_blue_alpha_(0.42, 0.93, 0.78, 0.24),
                "highlight": NSColor.colorWithRed_green_blue_alpha_(0.70, 0.98, 0.88, 0.12),
            },
        }.get(
            style,
            {
                "text": NSColor.colorWithRed_green_blue_alpha_(0.67, 0.85, 1.0, 0.98),
                "shadow": NSColor.colorWithRed_green_blue_alpha_(0.19, 0.42, 0.93, 0.45),
                "fill": NSColor.colorWithRed_green_blue_alpha_(0.10, 0.12, 0.15, 0.95),
                "stroke": NSColor.colorWithRed_green_blue_alpha_(0.67, 0.85, 1.0, 0.24),
                "highlight": NSColor.colorWithRed_green_blue_alpha_(0.80, 0.90, 1.0, 0.12),
            },
        )
        self._style_colors = palette
        self.setNeedsDisplay_(True)

    def setMessage_style_(self, message, style):
        self._apply_style(style)
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = self._font
        sized = NSAttributedString.alloc().initWithString_attributes_(message, attrs)
        text_size = sized.size()
        width = min(
            SHELF_WIDTH - 54,
            max(TOAST_MIN_WIDTH, math.ceil(text_size.width) + TOAST_TEXT_PADDING * 2),
        )
        height = TOAST_WINDOW_TOP_INSET + TOAST_BODY_HEIGHT
        self.setFrameSize_(NSMakeSize(width, height))
        self._message = message
        self._text_size = NSMakeSize(math.ceil(text_size.width), math.ceil(text_size.height))
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        palette = self._style_colors
        if not palette:
            return

        body_rect = self._body_rect()
        visible_rect = NSMakeRect(
            body_rect.origin.x,
            body_rect.origin.y + TOAST_SHELF_OVERLAP,
            body_rect.size.width,
            max(0, body_rect.size.height - TOAST_SHELF_OVERLAP),
        )
        radius = 12

        palette["fill"].set()
        body_path = self._body_fill_path(body_rect, radius)
        body_path.fill()

        palette["stroke"].set()
        body_outline = self._body_outline_path(body_rect, radius)
        body_outline.setLineWidth_(1.0)
        body_outline.stroke()

        if not self._message:
            return

        text_x = round(visible_rect.origin.x + (visible_rect.size.width - self._text_size.width) / 2)
        text_y = round(
            visible_rect.origin.y
            + max(0, (visible_rect.size.height - self._text_size.height) / 2)
            + TOAST_TEXT_VERTICAL_OFFSET
        )

        shadow_attrs = NSMutableDictionary.alloc().init()
        shadow_attrs[NSFontAttributeName] = self._font
        shadow_attrs[NSForegroundColorAttributeName] = palette["shadow"].colorWithAlphaComponent_(0.72)
        shadow_text = NSAttributedString.alloc().initWithString_attributes_(
            self._message, shadow_attrs
        )
        shadow_text.drawAtPoint_(NSMakePoint(text_x, text_y + 1))

        text_attrs = NSMutableDictionary.alloc().init()
        text_attrs[NSFontAttributeName] = self._font
        text_attrs[NSForegroundColorAttributeName] = palette["text"]
        text = NSAttributedString.alloc().initWithString_attributes_(self._message, text_attrs)
        text.drawAtPoint_(NSMakePoint(text_x, text_y))

    def play_pop_animation(self):
        try:
            layer = self.layer()
            if layer is None:
                return
            CAKeyframeAnimation = objc.lookUpClass("CAKeyframeAnimation")
            scale_anim = CAKeyframeAnimation.animationWithKeyPath_("transform.scale")
            scale_anim.setValues_([0.92, 1.05, 1.0])
            scale_anim.setDuration_(0.24)
            layer.removeAnimationForKey_("toastPop")
            layer.addAnimation_forKey_(scale_anim, "toastPop")
        except Exception:
            pass


class MarqueeLabelView(NSView):
    @classmethod
    def make_label(cls, text, frame, font, color):
        view = cls.alloc().initWithFrame_(frame)
        view._text = text or ""
        view._font = font
        view._text_color = color
        view._hovered = False
        view._marquee_generation = 0
        view._marquee_proxies = []
        view._setup_ui()
        return view

    def isFlipped(self):
        return True

    def hitTest_(self, point):
        return None

    def _setup_ui(self):
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(True)

        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = self._font
        sized = NSAttributedString.alloc().initWithString_attributes_(self._text, attrs)
        text_size = sized.size()
        self._text_width = math.ceil(text_size.width)
        label_h = max(14, math.ceil(text_size.height))
        label_y = max(0, (self.bounds().size.height - label_h) / 2)

        label = NSTextField.labelWithString_(self._text)
        label.setFrame_(NSMakeRect(0, label_y, max(self.bounds().size.width, self._text_width), label_h))
        label.setFont_(self._font)
        label.setTextColor_(self._text_color)
        label.setDrawsBackground_(False)
        label.setBezeled_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setWantsLayer_(True)
        self.addSubview_(label)
        self._label = label

    def has_overflow(self):
        return self._text_width > self.bounds().size.width + 2

    def setHovered_(self, hovered):
        if self._hovered == hovered:
            return
        self._hovered = hovered
        if hovered and self.has_overflow():
            self._start_marquee()
        else:
            self._stop_marquee()

    def _start_marquee(self):
        self._marquee_generation += 1
        generation = self._marquee_generation
        self._reset_label_position()
        self._schedule_callback(
            MARQUEE_START_DELAY,
            lambda current_generation=generation: self._animate_marquee_left(current_generation),
        )

    def _stop_marquee(self):
        self._marquee_generation += 1
        self._reset_label_position()

    def _schedule_callback(self, delay, callback):
        holder = {}

        def wrapped():
            proxy = holder.get("proxy")
            if proxy in self._marquee_proxies:
                self._marquee_proxies.remove(proxy)
            callback()

        proxy = ActionProxy.alloc().initWithCallback_(wrapped)
        holder["proxy"] = proxy
        self._marquee_proxies.append(proxy)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay, proxy, b"invoke:", None, False
        )

    def _animate_marquee_left(self, generation):
        if generation != self._marquee_generation or not self._hovered or not self.has_overflow():
            return
        overflow = self._overflow_distance()
        if overflow <= 0:
            return
        duration = max(1.35, overflow / MARQUEE_POINTS_PER_SECOND)
        self._animate_label_to_x(-overflow, duration)
        self._schedule_callback(
            duration + MARQUEE_EDGE_PAUSE,
            lambda current_generation=generation: self._animate_marquee_right(current_generation),
        )

    def _animate_marquee_right(self, generation):
        if generation != self._marquee_generation or not self._hovered or not self.has_overflow():
            return
        self._animate_label_to_x(0, MARQUEE_RETURN_DURATION, ease_out=True)
        self._schedule_callback(
            MARQUEE_RETURN_DURATION + MARQUEE_EDGE_PAUSE,
            lambda current_generation=generation: self._animate_marquee_left(current_generation),
        )

    def _overflow_distance(self):
        return max(0, self._text_width - self.bounds().size.width + 12)

    def _animate_label_to_x(self, target_x, duration, ease_out=False):
        if hasattr(self, "_marquee_target_x") and self._marquee_target_x is not None:
            if abs(self._marquee_target_x - target_x) < 0.5:
                return
        self._marquee_target_x = target_x
        if self._label.layer() is not None:
            self._label.layer().removeAllAnimations()
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(duration)
        try:
            CAMediaTimingFunction = objc.lookUpClass("CAMediaTimingFunction")
            if ease_out:
                ctx.setTimingFunction_(CAMediaTimingFunction.functionWithName_("easeOut"))
            else:
                ctx.setTimingFunction_(CAMediaTimingFunction.functionWithName_("linear"))
        except Exception:
            pass
        self._label.animator().setFrameOrigin_(NSMakePoint(target_x, self._label.frame().origin.y))
        NSAnimationContext.endGrouping()

    def _reset_label_position(self):
        self._marquee_target_x = None
        if self._label.layer() is not None:
            self._label.layer().removeAllAnimations()
        self._label.setFrameOrigin_(NSMakePoint(0, self._label.frame().origin.y))


class ShelfItemView(NSView):
    """Single shelf item. Shows preview thumbnail with filename below.
    Click to open, drag out to any target."""

    @classmethod
    def make_item(cls, path, index, remove_callback, shelf_window):
        width = SHELF_WIDTH - SHELF_PADDING * 2
        view = cls.alloc().initWithFrame_(NSMakeRect(0, 0, width, SHELF_ITEM_HEIGHT))
        view._file_path = path
        view._index = index
        view._remove_callback = remove_callback
        view._shelf_window = shelf_window
        view._hovered = False
        view._thumb_hovered = False
        view._selected = False
        view._mouse_down_event = None
        view._dragging = False
        view._reordering = False
        view._drag_handle_active = False
        view._drag_handle_hovered = False
        view._drag_gesture_moved = False
        view._drag_lift_base_frame = None
        view._reorder_blocked_feedback_shown = False
        view._drag_session_indices = []
        view._setup_ui(width)
        view._setup_tracking()
        return view

    def _setup_tracking(self):
        self._row_tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect,
            self,
            None,
        )
        self._thumb_tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self._thumb_frame,
            NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways,
            self,
            None,
        )
        self._drag_handle_tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self._drag_handle_frame,
            NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingEnabledDuringMouseDrag,
            self,
            None,
        )
        self.addTrackingArea_(self._row_tracking_area)
        self.addTrackingArea_(self._thumb_tracking_area)
        self.addTrackingArea_(self._drag_handle_tracking_area)

    def _setup_ui(self, width):
        path = self._file_path
        filename = os.path.basename(path)

        icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
        icon.setSize_(NSMakeSize(PREVIEW_SIZE, PREVIEW_SIZE))
        self._thumb_frame = NSMakeRect(
            10,
            (SHELF_ITEM_HEIGHT - PREVIEW_SIZE) // 2,
            PREVIEW_SIZE,
            PREVIEW_SIZE,
        )
        iv = NSImageView.alloc().initWithFrame_(self._thumb_frame)
        iv.setImage_(icon)
        iv.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        iv.setWantsLayer_(True)
        iv.layer().setCornerRadius_(6)
        iv.layer().setMasksToBounds_(True)
        self._thumb_view = iv
        self.addSubview_(iv)
        self._load_thumbnail_async(path)

        if len(filename) > 22:
            base, ext = os.path.splitext(filename)
            keep = 19 - len(ext)
            name_display = base[: max(keep, 5)] + "…" + ext
        else:
            name_display = filename
        name_lbl = NSTextField.labelWithString_(name_display)
        name_lbl.setFrame_(NSMakeRect(PREVIEW_SIZE + 20, 36, width - PREVIEW_SIZE - 60, 18))
        name_lbl.setFont_(NSFont.systemFontOfSize_weight_(13, 0.3))
        name_lbl.setTextColor_(NSColor.labelColor())
        name_lbl.setDrawsBackground_(False)
        name_lbl.setBezeled_(False)
        name_lbl.setEditable_(False)
        name_lbl.setSelectable_(False)
        self.addSubview_(name_lbl)

        size_bytes = get_file_size_bytes(path)
        size_str = human_readable_size(size_bytes) if size_bytes > 0 else ""
        badge_color, badge_fill = size_badge_style(size_bytes)
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSFontAttributeName] = NSFont.systemFontOfSize_(11)
        size_attr = NSAttributedString.alloc().initWithString_attributes_(size_str, attrs)
        text_size = size_attr.size()
        badge_w = max(64, math.ceil(text_size.width) + 22)
        badge = NSView.alloc().initWithFrame_(NSMakeRect(PREVIEW_SIZE + 20, 17, badge_w, 20))
        badge.setWantsLayer_(True)
        badge.layer().setCornerRadius_(10)
        badge.layer().setBorderWidth_(1.0)
        badge.layer().setBorderColor_(badge_color.CGColor())
        badge.layer().setBackgroundColor_(badge_fill.CGColor())
        self.addSubview_(badge)
        self._size_badge = badge

        size_lbl = NSTextField.labelWithString_(size_str)
        size_lbl.setFrame_(NSMakeRect(9, 3, badge_w - 18, 14))
        size_lbl.setFont_(NSFont.systemFontOfSize_(11))
        size_lbl.setTextColor_(badge_color)
        size_lbl.setDrawsBackground_(False)
        size_lbl.setBezeled_(False)
        size_lbl.setEditable_(False)
        size_lbl.setSelectable_(False)
        size_lbl.setAlignment_(2)
        badge.addSubview_(size_lbl)

        location_str = describe_file_location(path)
        location_frame = NSMakeRect(
            PREVIEW_SIZE + 20 + badge_w + 8,
            20,
            width - (PREVIEW_SIZE + 20 + badge_w + 78),
            14,
        )
        self._location_view = MarqueeLabelView.make_label(
            location_str,
            location_frame,
            NSFont.systemFontOfSize_(11),
            NSColor.secondaryLabelColor(),
        )
        self.addSubview_(self._location_view)

        self._remove_proxy = ActionProxy.alloc().initWithCallback_(lambda: self._remove_callback(self._index))
        self._remove_btn = NSButton.alloc().initWithFrame_(NSMakeRect(width - 28, SHELF_ITEM_HEIGHT - 26, 22, 22))
        self._remove_btn.setBordered_(False)
        self._remove_btn.setWantsLayer_(True)
        attrs = NSMutableDictionary.alloc().init()
        attrs[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
        attrs[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(14, 0.2)
        self._remove_btn.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_("×", attrs))
        self._remove_btn.setTarget_(self._remove_proxy)
        self._remove_btn.setAction_(b"invoke:")
        self.addSubview_(self._remove_btn)

        self._drag_handle_frame = NSMakeRect(width - 46, 16, 12, 20)

    def _load_thumbnail_async(self, path):
        def _worker():
            thumb = get_file_thumbnail(path, PREVIEW_SIZE)
            if thumb:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    b"_applyThumbnail:", thumb, False
                )

        threading.Thread(target=_worker, daemon=True).start()

    @objc.typedSelector(b"v@:@")
    def _applyThumbnail_(self, image):
        if self.superview() is not None and hasattr(self, "_thumb_view"):
            self._thumb_view.setImage_(image)

    def drawRect_(self, rect):
        card_rect = NSMakeRect(
            2,
            4,
            max(0, self.bounds().size.width - 4),
            max(0, self.bounds().size.height - 8),
        )
        if self._selected:
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.18).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(card_rect, 8, 8).fill()
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.7).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(
                    card_rect.origin.x + 1,
                    card_rect.origin.y + 6,
                    3,
                    max(0, card_rect.size.height - 12),
                ),
                1.5,
                1.5,
            ).fill()
        elif self._hovered:
            NSColor.colorWithWhite_alpha_(0.5, 0.08).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(card_rect, 8, 8).fill()

        if self._index in self._shelf_window._pinned_indices:
            attrs = NSMutableDictionary.alloc().init()
            attrs[NSFontAttributeName] = NSFont.systemFontOfSize_(9)
            attrs[NSForegroundColorAttributeName] = NSColor.systemOrangeColor()
            pin = NSAttributedString.alloc().initWithString_attributes_("📌", attrs)
            pin.drawAtPoint_(NSMakePoint(1, self.bounds().size.height - 14))

        handle_color = NSColor.whiteColor().colorWithAlphaComponent_(
            0.54
            if (self._drag_handle_active or self._drag_handle_hovered)
            else 0.48
            if (self._selected or self._hovered)
            else 0.26
        )
        handle_color.set()
        dot = 2.2
        start_x = self._drag_handle_frame.origin.x + 1
        start_y = self._drag_handle_frame.origin.y + 3
        gap_x = 4.2
        gap_y = 4.6
        for col in range(2):
            for row in range(3):
                dot_rect = NSMakeRect(start_x + col * gap_x, start_y + row * gap_y, dot, dot)
                NSBezierPath.bezierPathWithOvalInRect_(dot_rect).fill()

    def mouseEntered_(self, event):
        if self._shelf_window._clear_in_progress:
            return
        if event.trackingArea() == getattr(self, "_drag_handle_tracking_area", None):
            self._drag_handle_hovered = True
            self._sync_drag_handle_cursor()
            self.setNeedsDisplay_(True)
            return
        if event.trackingArea() == getattr(self, "_thumb_tracking_area", None):
            self._thumb_hovered = True
            self._setThumbnailExpanded_(True)
            return
        self._hovered = True
        if hasattr(self, "_location_view"):
            self._location_view.setHovered_(True)
        self.setNeedsDisplay_(True)
        self._shakeRemoveButton()

    def mouseExited_(self, event):
        if self._shelf_window._clear_in_progress:
            return
        if event.trackingArea() == getattr(self, "_drag_handle_tracking_area", None):
            self._drag_handle_hovered = False
            self._sync_drag_handle_cursor()
            self.setNeedsDisplay_(True)
            return
        if event.trackingArea() == getattr(self, "_thumb_tracking_area", None):
            self._thumb_hovered = False
            self._setThumbnailExpanded_(False)
            return
        # Verify mouse is actually outside bounds to avoid spurious exits
        # from NSTrackingInVisibleRect during scrolling or sub-area transitions
        window = self.window()
        if window is not None:
            local = self.convertPoint_fromView_(window.mouseLocationOutsideOfEventStream(), None)
            bounds = self.bounds()
            if 0 <= local.x <= bounds.size.width and 0 <= local.y <= bounds.size.height:
                return
        self._hovered = False
        if hasattr(self, "_location_view"):
            self._location_view.setHovered_(False)
        self.setNeedsDisplay_(True)
        if hasattr(self, "_remove_btn") and self._remove_btn.layer():
            self._remove_btn.layer().removeAnimationForKey_("shake")

    def _setThumbnailExpanded_(self, expanded):
        if not hasattr(self, "_thumb_view"):
            return
        if expanded:
            self._thumb_view.layer().setBorderWidth_(1.2)
            self._thumb_view.layer().setBorderColor_(
                NSColor.systemBlueColor().colorWithAlphaComponent_(0.7).CGColor()
            )
            self._shelf_window.show_hover_preview(self)
        else:
            self._thumb_view.layer().setBorderWidth_(0.0)
            self._thumb_view.layer().setBorderColor_(None)
            self._shelf_window.hide_hover_preview(self)

    def _shakeRemoveButton(self):
        try:
            CAKeyframeAnimation = objc.lookUpClass("CAKeyframeAnimation")
            anim = CAKeyframeAnimation.animationWithKeyPath_("transform.translation.x")
            anim.setValues_([-1.5, 1.5, -1.0, 1.0, 0])
            anim.setDuration_(0.3)
            self._remove_btn.layer().addAnimation_forKey_(anim, "shake")
        except Exception:
            pass

    def menuForEvent_(self, event):
        if self._shelf_window._clear_in_progress:
            return None
        menu = NSMenu.alloc().init()
        self._ctx_proxies = []

        px = ActionProxy.alloc().initWithCallback_(
            lambda: subprocess.Popen(
                ["qlmanage", "-p", self._file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        self._ctx_proxies.append(px)
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quick Look", b"invoke:", "")
        mi.setTarget_(px)
        menu.addItem_(mi)

        px2 = ActionProxy.alloc().initWithCallback_(
            lambda: NSWorkspace.sharedWorkspace().openFile_(self._file_path)
        )
        self._ctx_proxies.append(px2)
        mi2 = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open", b"invoke:", "")
        mi2.setTarget_(px2)
        menu.addItem_(mi2)

        px3 = ActionProxy.alloc().initWithCallback_(
            lambda: NSWorkspace.sharedWorkspace().selectFile_inFileViewerRootedAtPath_(
                self._file_path, ""
            )
        )
        self._ctx_proxies.append(px3)
        mi3 = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show in Finder", b"invoke:", "")
        mi3.setTarget_(px3)
        menu.addItem_(mi3)

        menu.addItem_(NSMenuItem.separatorItem())

        px4 = ActionProxy.alloc().initWithCallback_(self._copyFilePath)
        self._ctx_proxies.append(px4)
        mi4 = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Copy File Path", b"invoke:", "")
        mi4.setTarget_(px4)
        menu.addItem_(mi4)

        menu.addItem_(NSMenuItem.separatorItem())

        is_pinned = self._index in self._shelf_window._pinned_indices
        pin_label = "Unpin" if is_pinned else "Pin to Top"
        px5 = ActionProxy.alloc().initWithCallback_(self._togglePin)
        self._ctx_proxies.append(px5)
        mi5 = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(pin_label, b"invoke:", "")
        mi5.setTarget_(px5)
        menu.addItem_(mi5)

        return menu

    def _togglePin(self):
        shelf_window = self._shelf_window
        if shelf_window._clear_in_progress:
            return
        if self._index in shelf_window._pinned_indices:
            shelf_window._pinned_indices.discard(self._index)
        else:
            shelf_window._pinned_indices.add(self._index)
        shelf_window._refresh()

    def _copyFilePath(self):
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(self._file_path, NSPasteboardTypeString)

    def mouseDown_(self, event):
        if self._shelf_window._clear_in_progress:
            return
        local = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._drag_handle_active = self._point_in_drag_handle(local)
        self._drag_gesture_moved = False
        self._reorder_blocked_feedback_shown = False
        self._sync_drag_handle_cursor()
        self.setNeedsDisplay_(True)
        self._mouse_down_event = event
        self._dragging = False

    def mouseDragged_(self, event):
        if self._shelf_window._clear_in_progress:
            return
        if self._dragging or self._mouse_down_event is None:
            return
        start = self._mouse_down_event.locationInWindow()
        current = event.locationInWindow()
        shelf_window = self._shelf_window
        dx = current.x - start.x
        dy = current.y - start.y
        abs_dx = abs(dx)
        abs_dy = abs(dy)
        distance = math.sqrt(dx**2 + dy**2)
        if distance < DRAG_THRESHOLD:
            return
        self._drag_gesture_moved = True

        if self._drag_handle_active:
            self._sync_drag_handle_cursor(refresh_pointer=True)
            if shelf_window.can_reorder_items():
                if (
                    not self._reordering
                    and shelf_window.point_is_inside_reorder_area(current)
                    and abs_dy >= REORDER_DRAG_THRESHOLD
                    and abs_dy >= abs_dx * REORDER_VERTICAL_BIAS
                ):
                    self._reordering = True
                    shelf_window.begin_reorder(self._index, current)
                if self._reordering:
                    if shelf_window.point_is_inside_reorder_area(current):
                        shelf_window.update_reorder(current)
                        return
                    shelf_window.cancel_reorder()
                    self._reordering = False
                    self._sync_drag_handle_cursor(refresh_pointer=True)
            elif not self._reorder_blocked_feedback_shown:
                if shelf_window._auto_organize:
                    shelf_window.show_toast("Turn off Auto-organize to reorder", "duplicate")
                else:
                    shelf_window.show_toast("Reordering is unavailable right now", "duplicate")
                self._reorder_blocked_feedback_shown = True
            return

        if not shelf_window.point_is_inside_reorder_area(current):
            self._startExternalDrag()

    def _startExternalDrag(self):
        shelf_window = self._shelf_window
        if shelf_window._clear_in_progress:
            return
        self._dragging = True
        self._drag_lift_base_frame = self.frame()
        if self._index in shelf_window._selected_indices:
            visible_order = shelf_window._flat_visible_indices()
            drag_indices = [idx for idx in visible_order if idx in shelf_window._selected_indices]
        else:
            drag_indices = [self._index]
        self._drag_session_indices = drag_indices
        self.setWantsLayer_(True)
        if self.layer():
            self.layer().setZPosition_(10)
            self.layer().setShadowColor_(NSColor.blackColor().CGColor())
            self.layer().setShadowOpacity_(0.3)
            self.layer().setShadowRadius_(12)
            self.layer().setShadowOffset_(NSMakeSize(0, -4))
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.15)
        self.animator().setAlphaValue_(0.7)
        frame = self.frame()
        self.animator().setFrame_(
            NSMakeRect(
                frame.origin.x - 2,
                frame.origin.y - 2,
                frame.size.width + 4,
                frame.size.height + 4,
            )
        )
        NSAnimationContext.endGrouping()
        items = []
        for idx in drag_indices:
            if 0 <= idx < len(shelf_window._files):
                file_path = shelf_window._files[idx]
                url = NSURL.fileURLWithPath_(file_path)
                dragging_item = NSDraggingItem.alloc().initWithPasteboardWriter_(url)
                icon = get_file_icon(file_path)
                dragging_item.setDraggingFrame_contents_(NSMakeRect(0, 0, 48, 48), icon)
                items.append(dragging_item)
        if items:
            self.beginDraggingSessionWithItems_event_source_(items, self._mouse_down_event, self)

    def mouseUp_(self, event):
        if self._shelf_window._clear_in_progress:
            self._mouse_down_event = None
            self._dragging = False
            self._reordering = False
            self._drag_handle_active = False
            self._drag_gesture_moved = False
            self._reorder_blocked_feedback_shown = False
            self._sync_drag_handle_cursor(refresh_pointer=True)
            self.setNeedsDisplay_(True)
            return
        if self._reordering:
            self._shelf_window.finish_reorder()
            self._mouse_down_event = None
            self._dragging = False
            self._reordering = False
            self._drag_handle_active = False
            self._drag_gesture_moved = False
            self._reorder_blocked_feedback_shown = False
            self._sync_drag_handle_cursor(refresh_pointer=True)
            self.setNeedsDisplay_(True)
            return
        if self._drag_handle_active:
            self._mouse_down_event = None
            self._dragging = False
            self._drag_handle_active = False
            self._drag_gesture_moved = False
            self._reorder_blocked_feedback_shown = False
            self._sync_drag_handle_cursor(refresh_pointer=True)
            self.setNeedsDisplay_(True)
            return
        if not self._dragging and not self._drag_gesture_moved and self._mouse_down_event is not None:
            if event.clickCount() == 2:
                NSWorkspace.sharedWorkspace().openFile_(self._file_path)
            else:
                shift = bool(event.modifierFlags() & (1 << 17))
                self._shelf_window.toggle_selection(self._index, shift)
        self._mouse_down_event = None
        self._dragging = False
        self._drag_handle_active = False
        self._drag_gesture_moved = False
        self._reorder_blocked_feedback_shown = False
        self._sync_drag_handle_cursor(refresh_pointer=True)
        self.setNeedsDisplay_(True)

    def mouseDownCanMoveWindow(self):
        return False

    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        return NSDragOperationCopy | NSDragOperationMove | NSDragOperationDelete

    def draggingSession_endedAtPoint_operation_(self, session, point, operation):
        if self.layer():
            self.layer().setZPosition_(0)
            self.layer().setShadowOpacity_(0.0)
            self.layer().setShadowRadius_(0.0)
            self.layer().setShadowOffset_(NSMakeSize(0, 0))
        self.setAlphaValue_(1.0)
        if self._drag_lift_base_frame is not None:
            self.setFrame_(self._drag_lift_base_frame)
            self._drag_lift_base_frame = None
        self._drag_handle_active = False
        self._drag_gesture_moved = False
        self._reorder_blocked_feedback_shown = False
        self._sync_drag_handle_cursor(refresh_pointer=True)
        self.setNeedsDisplay_(True)
        if self._shelf_window._clear_in_progress:
            self._reordering = False
            self._drag_session_indices = []
            return
        if operation & (NSDragOperationMove | NSDragOperationDelete):
            shelf_window = self._shelf_window
            shelf_window._remove_file_indices(self._drag_session_indices)
            shelf_window._selected_indices.clear()
            shelf_window._last_selected_index = None
            shelf_window._refresh()
            if not shelf_window._files:
                shelf_window.show_toast("You made that look easy!", "celebrate")
        elif operation == NSDragOperationNone:
            shelf_window = self._shelf_window
            for idx in self._drag_session_indices:
                shelf_window._selected_indices.discard(idx)
            shelf_window._last_selected_index = None
            shelf_window._update_selection_visuals()
        self._drag_session_indices = []
        self._reordering = False

    def _refresh_drag_handle_hover_state(self):
        window = self.window()
        if window is None:
            self._drag_handle_hovered = False
            return
        local = self.convertPoint_fromView_(window.mouseLocationOutsideOfEventStream(), None)
        self._drag_handle_hovered = (
            0 <= local.x <= self.bounds().size.width
            and 0 <= local.y <= self.bounds().size.height
            and self._point_in_drag_handle(local)
        )

    def _sync_drag_handle_cursor(self, refresh_pointer=False):
        if refresh_pointer:
            self._refresh_drag_handle_hover_state()
        if self._drag_handle_active and self._drag_handle_hovered:
            NSCursor.closedHandCursor().set()
        elif self._drag_handle_hovered:
            NSCursor.openHandCursor().set()
        else:
            NSCursor.arrowCursor().set()

    def pulse_attention(self):
        try:
            self.setWantsLayer_(True)
            layer = self.layer()
            if layer is None:
                return
            layer.setShadowColor_(NSColor.systemBlueColor().colorWithAlphaComponent_(0.8).CGColor())
            layer.setShadowOffset_(NSMakeSize(0, 0))
            layer.setShadowOpacity_(0.0)
            layer.setShadowRadius_(0.0)
            CAKeyframeAnimation = objc.lookUpClass("CAKeyframeAnimation")

            scale_anim = CAKeyframeAnimation.animationWithKeyPath_("transform.scale")
            scale_anim.setValues_([1.0, 1.018, 0.995, 1.0])
            scale_anim.setDuration_(0.42)

            shadow_anim = CAKeyframeAnimation.animationWithKeyPath_("shadowOpacity")
            shadow_anim.setValues_([0.0, 0.32, 0.0])
            shadow_anim.setDuration_(0.42)

            radius_anim = CAKeyframeAnimation.animationWithKeyPath_("shadowRadius")
            radius_anim.setValues_([0.0, 14.0, 0.0])
            radius_anim.setDuration_(0.42)

            layer.removeAnimationForKey_("attentionScale")
            layer.removeAnimationForKey_("attentionShadow")
            layer.removeAnimationForKey_("attentionRadius")
            layer.addAnimation_forKey_(scale_anim, "attentionScale")
            layer.addAnimation_forKey_(shadow_anim, "attentionShadow")
            layer.addAnimation_forKey_(radius_anim, "attentionRadius")
        except Exception:
            pass

    def _point_in_drag_handle(self, point):
        frame = self._drag_handle_frame
        return (
            frame.origin.x <= point.x <= frame.origin.x + frame.size.width
            and frame.origin.y <= point.y <= frame.origin.y + frame.size.height
        )


class DropTargetView(NSView):
    @classmethod
    def make_view(cls, frame, shelf_window):
        view = cls.alloc().initWithFrame_(frame)
        view._shelf_window = shelf_window
        view.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        return view

    def isFlipped(self):
        return True

    def mouseDownCanMoveWindow(self):
        return False

    def _is_self_drag_from_shelf(self, sender):
        try:
            source = sender.draggingSource()
        except Exception:
            return False
        return isinstance(source, ShelfItemView) and getattr(source, "_shelf_window", None) is self._shelf_window

    def draggingEntered_(self, sender):
        if self._shelf_window._clear_in_progress:
            return NSDragOperationNone
        if self._is_self_drag_from_shelf(sender):
            return NSDragOperationNone
        self._shelf_window._beginDropAnimation(sender.draggingLocation())
        return NSDragOperationCopy

    def draggingUpdated_(self, sender):
        if self._shelf_window._clear_in_progress:
            return NSDragOperationNone
        if self._is_self_drag_from_shelf(sender):
            return NSDragOperationNone
        self._shelf_window._updateDropAnimation(sender.draggingLocation())
        return NSDragOperationCopy

    def draggingExited_(self, sender):
        if self._shelf_window._clear_in_progress:
            return
        self._shelf_window._endDropAnimation()

    def performDragOperation_(self, sender):
        if self._shelf_window._clear_in_progress:
            self._shelf_window._endDropAnimation()
            return False
        if self._is_self_drag_from_shelf(sender):
            self._shelf_window._endDropAnimation()
            return False
        pasteboard = sender.draggingPasteboard()
        urls = pasteboard.readObjectsForClasses_options_(
            [objc.lookUpClass("NSURL")],
            {"NSPasteboardURLReadingFileURLsOnlyKey": True},
        )
        if urls:
            shelf_window = self._shelf_window
            gap_idx = shelf_window._drop_gap_index
            shelf_window._endDropAnimation()
            paths = [str(url.path()) for url in urls if url.path()]
            result = shelf_window.add_files(paths, gap_idx)
            if result["added_count"] > 0:
                shelf_window._flashDropHighlight()
        else:
            self._shelf_window._endDropAnimation()
        return True

    def drawRect_(self, rect):
        visible = self.visibleRect()

        if getattr(self._shelf_window, "_drop_highlight", False):
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.35).set()
            border_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(
                    visible.origin.x + 2,
                    visible.origin.y + 2,
                    visible.size.width - 4,
                    visible.size.height - 4,
                ),
                10,
                10,
            )
            border_path.setLineWidth_(2.5)
            border_path.stroke()

        if getattr(self._shelf_window, "_reorder_indicator_y", None) is not None:
            y = self._shelf_window._reorder_indicator_y
            NSColor.systemBlueColor().colorWithAlphaComponent_(0.85).set()
            line = NSBezierPath.bezierPath()
            line.moveToPoint_(NSMakePoint(SHELF_PADDING + 4, y))
            line.lineToPoint_(NSMakePoint(rect.size.width - SHELF_PADDING - 4, y))
            line.setLineWidth_(3.0)
            line.stroke()

        if self._shelf_window.should_draw_empty_hint():
            hint = "Drop files here"
            attrs = NSMutableDictionary.alloc().init()
            attrs[NSFontAttributeName] = NSFont.systemFontOfSize_weight_(14, 0.2)
            attrs[NSForegroundColorAttributeName] = NSColor.secondaryLabelColor()
            hint_string = NSAttributedString.alloc().initWithString_attributes_(hint, attrs)
            size = hint_string.size()
            hint_string.drawAtPoint_(
                NSMakePoint(
                    visible.origin.x + (visible.size.width - size.width) / 2,
                    visible.origin.y + (visible.size.height - size.height) / 2,
                )
            )
