import os
import subprocess
import sys
import time

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSEvent,
    NSFilenamesPboardType,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSOffState,
    NSOnState,
    NSPasteboard,
    NSPasteboardNameDrag,
    NSPasteboardTypeFileURL,
    NSStatusBar,
)
from Foundation import NSBundle, NSObject, NSTimer

from .constants import SHAKE_POLL_INTERVAL, SENSITIVITY_PRESETS
from .file_utils import make_status_item_image
from .settings import load_settings, save_settings
from .shelf_window import ShelfWindow
from .ui_components import ActionProxy


def _log(msg):
    """Append a timestamped line to ~/.dropshelf/shake_debug.log."""
    try:
        path = os.path.expanduser("~/.dropshelf/shake_debug.log")
        with open(path, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


class ShakeDetector(NSObject):
    """Detect horizontal cursor‑shake gestures to summon the shelf.

    Detection rules:
    ── No mouse buttons held ──
        Normal shake detection runs.  Accumulate horizontal reversals;
        trigger when enough occur within the time window.

    ── Mouse button held, first 150 ms ──
        Too early to tell whether this is a file‑drag or a regular
        click/selection.  Reset and skip.

    ── Mouse button held, after 150 ms ──
        Only allow detection if the drag pasteboard carries file URLs
        whose changeCount differs from the last idle snapshot.  This
        means a NEW file‑drag session is in progress.

    ── Vertical guard ──
        True shakes are primarily horizontal.  If cumulative vertical
        drift exceeds a threshold, the gesture is rejected as normal
        cursor movement.
    """

    def initWithCallback_(self, callback):
        self = objc.super(ShakeDetector, self).init()
        if self is None:
            return None
        self._callback = callback
        self._prev_x = None
        self._direction = 0
        self._segment_distance = 0.0
        self._reversals = []
        self._cooldown_until = 0.0
        self._direction_changes = 3
        self._time_window = 0.6
        self._min_segment = 14
        # Button‑hold debounce
        self._button_press_start = 0.0
        # Drag pasteboard changeCount baseline (updated while idle)
        self._idle_drag_change_count = -1
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            SHAKE_POLL_INTERVAL, self, b"tick:", None, True
        )
        _log("ShakeDetector initialised")
        return self

    def _applySensitivity_(self, name):
        preset = SENSITIVITY_PRESETS.get(name, SENSITIVITY_PRESETS["medium"])
        self._direction_changes, self._time_window, self._min_segment = preset
        self._reset()

    def _cooldown_(self, seconds):
        self._cooldown_until = time.monotonic() + seconds
        self._reset()

    def _reset(self):
        self._reversals.clear()
        self._prev_x = None
        self._direction = 0
        self._segment_distance = 0.0

    # ── File‑drag detection ────────────────────────────────────────

    def _file_drag_active(self):
        """Return True only during a *new* file‑drag session.

        Compares the drag pasteboard's changeCount against the last
        idle snapshot so that stale pasteboard data from a previous
        drag is ignored.
        """
        try:
            drag_pb = NSPasteboard.pasteboardWithName_(NSPasteboardNameDrag)
        except Exception:
            return False
        if drag_pb is None:
            return False
        current_count = drag_pb.changeCount()
        # If the count hasn't changed since the last idle snapshot,
        # the pasteboard is stale — no new drag session.
        if current_count == self._idle_drag_change_count:
            return False
        drag_type = drag_pb.availableTypeFromArray_(
            [NSPasteboardTypeFileURL, NSFilenamesPboardType]
        )
        return bool(drag_type)

    def _update_idle_drag_count(self):
        """Snapshot the drag pasteboard changeCount while no buttons are held."""
        try:
            drag_pb = NSPasteboard.pasteboardWithName_(NSPasteboardNameDrag)
            if drag_pb is not None:
                self._idle_drag_change_count = drag_pb.changeCount()
        except Exception:
            pass

    # ── Main tick ──────────────────────────────────────────────────

    @objc.typedSelector(b"v@:@")
    def tick_(self, timer):
        buttons = NSEvent.pressedMouseButtons()
        now = time.monotonic()

        if buttons == 0:
            # ── No buttons held ──
            # Shake detection is ONLY active during a file drag, so when
            # no buttons are held we just maintain bookkeeping and skip.
            # The user can show/hide the shelf via the menu-bar icon.
            self._button_press_start = 0.0
            self._update_idle_drag_count()
            self._reset()
            return

        # ── A mouse button is held ──
        if self._button_press_start == 0.0:
            # Just pressed — record the time, reset, skip.
            self._button_press_start = now
            self._reset()
            return

        hold_ms = (now - self._button_press_start) * 1000
        if hold_ms < 150:
            # Too early to distinguish click from drag.  Block.
            self._reset()
            return

        # Held 150 ms+ — only allow if it's a real file drag.
        if not self._file_drag_active():
            self._reset()
            return
        # File drag confirmed — fall through to shake detection.

        if now < self._cooldown_until:
            return

        x = NSEvent.mouseLocation().x

        if self._prev_x is None:
            self._prev_x = x
            return

        dx = x - self._prev_x
        self._prev_x = x

        if abs(dx) < 0.5:
            return

        new_dir = 1 if dx > 0 else -1
        if new_dir == self._direction:
            self._segment_distance += abs(dx)
        else:
            if self._direction != 0 and self._segment_distance >= self._min_segment:
                self._reversals.append(now)
                cutoff = now - self._time_window
                self._reversals = [t for t in self._reversals if t > cutoff]
                if len(self._reversals) >= self._direction_changes:
                    _log(
                        f"SHAKE TRIGGERED  reversals={len(self._reversals)} "
                        f"buttons={buttons}"
                    )
                    self._reversals.clear()
                    self._cooldown_until = now + 1.5
                    self._callback()
            self._direction = new_dir
            self._segment_distance = abs(dx)


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self._settings = load_settings()
        self._proxies = []

        self._shelf = ShelfWindow(self._settings)
        self._shake = ShakeDetector.alloc().initWithCallback_(self._on_shake)
        self._shake._applySensitivity_(self._settings["sensitivity"])
        self._shelf._shake_detector = self._shake

        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        btn = self._status_item.button()

        img = make_status_item_image()
        if img:
            btn.setImage_(img)
            btn.setTitle_("")
        if not btn.image():
            btn.setTitle_("\U0001F4C2 ")
            btn.setFont_(NSFont.systemFontOfSize_(14))

        menu = NSMenu.alloc().init()

        si = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show / Hide Shelf", self.toggleShelf_, "")
        si.setTarget_(self)
        menu.addItem_(si)
        menu.addItem_(NSMenuItem.separatorItem())

        pm = NSMenu.alloc().init()
        self._pos_items = {}
        for label, key in [
            ("Top Right", "top-right"),
            ("Top Left", "top-left"),
            ("Bottom Right", "bottom-right"),
            ("Bottom Left", "bottom-left"),
            ("Near Cursor", "near-cursor"),
        ]:
            px = ActionProxy.alloc().initWithCallback_(lambda k=key: self._set_position(k))
            self._proxies.append(px)
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, px.invoke_, "")
            mi.setTarget_(px)
            mi.setAction_(b"invoke:")
            if key == self._settings["position"]:
                mi.setState_(NSOnState)
            pm.addItem_(mi)
            self._pos_items[key] = mi
        pp = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Position", None, "")
        pp.setSubmenu_(pm)
        menu.addItem_(pp)

        sm = NSMenu.alloc().init()
        self._sens_items = {}
        for label, key in [("Low", "low"), ("Medium", "medium"), ("High", "high")]:
            px = ActionProxy.alloc().initWithCallback_(lambda k=key: self._set_sensitivity(k))
            self._proxies.append(px)
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, px.invoke_, "")
            mi.setTarget_(px)
            mi.setAction_(b"invoke:")
            if key == self._settings["sensitivity"]:
                mi.setState_(NSOnState)
            sm.addItem_(mi)
            self._sens_items[key] = mi
        sp = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Shake Sensitivity", None, "")
        sp.setSubmenu_(sm)
        menu.addItem_(sp)

        menu.addItem_(NSMenuItem.separatorItem())
        ai = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("About DropShelf", self.showAbout_, "")
        ai.setTarget_(self)
        menu.addItem_(ai)
        ri = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Refresh", self.refreshApp_, "r")
        ri.setTarget_(self)
        menu.addItem_(ri)
        menu.addItem_(NSMenuItem.separatorItem())
        qi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", self.quitApp_, "q")
        qi.setTarget_(self)
        menu.addItem_(qi)

        self._status_item.setMenu_(menu)
        _log("DropShelf launched")
        print("DropShelf running. Shake your cursor to open the shelf.")

    def _set_position(self, key):
        self._settings["position"] = key
        save_settings(self._settings)
        self._shelf._settings = self._settings
        for k, mi in self._pos_items.items():
            mi.setState_(NSOnState if k == key else NSOffState)

    def _set_sensitivity(self, key):
        self._settings["sensitivity"] = key
        save_settings(self._settings)
        self._shake._applySensitivity_(key)
        for k, mi in self._sens_items.items():
            mi.setState_(NSOnState if k == key else NSOffState)

    def _on_shake(self):
        # Double‑check at callback time — block if a non‑drag button
        # is somehow still held.
        if NSEvent.pressedMouseButtons() != 0 and not self._shake._file_drag_active():
            _log("_on_shake BLOCKED (button held, no file drag)")
            return
        if not self._shelf.recently_toggled() and not self._shelf._window.isVisible():
            _log("_on_shake → showing shelf")
            self._shelf.show()
        else:
            _log("_on_shake SKIPPED (recently toggled or already visible)")

    @objc.typedSelector(b"v@:@")
    def toggleShelf_(self, sender):
        self._shelf.toggle_in_place()
        self._shake._cooldown_(1.5)

    @objc.typedSelector(b"v@:@")
    def showAbout_(self, sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("DropShelf v2.0")
        alert.setInformativeText_(
            "A free Dropover alternative for macOS.\n\n"
            "Shake your cursor to summon the shelf.\n"
            "Drag files in and out freely.\n\n"
            "Configure position and sensitivity\nfrom the menu bar icon."
        )
        alert.setAlertStyle_(1)
        alert.runModal()

    @objc.typedSelector(b"v@:@")
    def refreshApp_(self, sender):
        bundle_path = NSBundle.mainBundle().bundlePath()
        if bundle_path and bundle_path.endswith(".app"):
            # Relaunch via the app bundle after a brief delay so the
            # current instance has time to terminate.
            subprocess.Popen(
                ["bash", "-c", 'sleep 0.5 && open "$1"', "bash", bundle_path],
                start_new_session=True,
            )
            NSApp.terminate_(None)
        else:
            # Fallback: direct Python re-exec (running outside .app bundle).
            script = os.path.abspath(sys.argv[0]) if sys.argv else None
            if not script:
                pkg = os.path.dirname(os.path.abspath(__file__))
                script = os.path.join(os.path.dirname(pkg), "dropshelf.py")
            try:
                subprocess.Popen(
                    [sys.executable, "-u", script],
                    cwd=os.getcwd(),
                    start_new_session=True,
                )
                NSApp.terminate_(None)
            except OSError as exc:
                alert = NSAlert.alloc().init()
                alert.setMessageText_("Could not refresh DropShelf")
                alert.setInformativeText_(str(exc))
                alert.setAlertStyle_(2)
                alert.runModal()

    @objc.typedSelector(b"v@:@")
    def quitApp_(self, sender):
        NSApp.terminate_(None)
