from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

from .app_delegate import AppDelegate


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()
