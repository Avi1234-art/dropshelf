#!/usr/bin/env python3
"""
Generate a crisp 1024x1024 macOS app icon for DropShelf.
"""

import os
import sys

from AppKit import (
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSPNGFileType,
    NSShadow,
)


CANVAS = 1024


def rgb(hex_code, alpha=1.0):
    hex_code = hex_code.lstrip("#")
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(
        int(hex_code[0:2], 16) / 255.0,
        int(hex_code[2:4], 16) / 255.0,
        int(hex_code[4:6], 16) / 255.0,
        alpha,
    )


def rounded_rect(x, y, width, height, radius):
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, width, height),
        radius,
        radius,
    )


def fill_with_shadow(path, fill_color, shadow_color, blur, offset_y):
    NSGraphicsContext.saveGraphicsState()
    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(shadow_color)
    shadow.setShadowBlurRadius_(blur)
    shadow.setShadowOffset_(NSMakeSize(0, offset_y))
    shadow.set()
    fill_color.setFill()
    path.fill()
    NSGraphicsContext.restoreGraphicsState()


def stroke_path(path, stroke_color, line_width):
    stroke_color.setStroke()
    path.setLineWidth_(line_width)
    path.stroke()


def draw_paper(x, y, width, height, angle, fill_hex, fold_hex, outline_hex):
    NSGraphicsContext.saveGraphicsState()
    transform = NSAffineTransform.transform()
    transform.translateXBy_yBy_(x + width / 2.0, y + height / 2.0)
    transform.rotateByDegrees_(angle)
    transform.translateXBy_yBy_(-(x + width / 2.0), -(y + height / 2.0))
    transform.concat()

    page = rounded_rect(x, y, width, height, 34)
    fill_with_shadow(
        page,
        rgb(fill_hex),
        rgb("0F172A", 0.16),
        18,
        -12,
    )
    stroke_path(page, rgb(outline_hex, 0.95), 14)

    fold_size = min(width, height) * 0.2
    fold = NSBezierPath.bezierPath()
    fold.moveToPoint_(NSMakePoint(x + width - fold_size, y + height))
    fold.lineToPoint_(NSMakePoint(x + width, y + height))
    fold.lineToPoint_(NSMakePoint(x + width, y + height - fold_size))
    fold.closePath()
    rgb(fold_hex).setFill()
    fold.fill()

    fold_line = NSBezierPath.bezierPath()
    fold_line.moveToPoint_(NSMakePoint(x + width - fold_size, y + height))
    fold_line.lineToPoint_(NSMakePoint(x + width - fold_size, y + height - fold_size))
    fold_line.lineToPoint_(NSMakePoint(x + width, y + height - fold_size))
    stroke_path(fold_line, rgb(outline_hex, 0.55), 9)

    margin = 44
    line_y = y + height - 120
    for _ in range(4):
        line = NSBezierPath.bezierPath()
        line.moveToPoint_(NSMakePoint(x + margin, line_y))
        line.lineToPoint_(NSMakePoint(x + width - margin - 16, line_y))
        stroke_path(line, rgb(outline_hex, 0.16), 10)
        line_y -= 56

    NSGraphicsContext.restoreGraphicsState()


def draw_icon():
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
        None,
        CANVAS,
        CANVAS,
        8,
        4,
        True,
        False,
        NSDeviceRGBColorSpace,
        0,
        0,
        0,
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    background = rounded_rect(72, 72, 880, 880, 196)
    fill_with_shadow(
        background,
        rgb("E7F0FF"),
        rgb("0F172A", 0.2),
        34,
        -18,
    )
    gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
        rgb("F7FBFF"),
        rgb("D6E7FF"),
    )
    gradient.drawInBezierPath_angle_(background, 90)
    stroke_path(background, rgb("FFFFFF", 0.72), 8)

    top_glow = rounded_rect(116, 520, 792, 250, 124)
    rgb("FFFFFF", 0.18).setFill()
    top_glow.fill()

    draw_paper(196, 320, 224, 420, -11, "D8ECFF", "B5DAFF", "143251")
    draw_paper(396, 250, 252, 478, 0, "FFFFFF", "E7EEF8", "10253F")
    draw_paper(620, 320, 214, 412, 10, "DDF6EA", "BCE8D2", "123A32")

    tray = rounded_rect(152, 152, 720, 182, 86)
    fill_with_shadow(
        tray,
        rgb("17324D"),
        rgb("0F172A", 0.28),
        28,
        -16,
    )
    tray_gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
        rgb("234F74"),
        rgb("122B45"),
    )
    tray_gradient.drawInBezierPath_angle_(tray, 90)
    stroke_path(tray, rgb("0A1B2D", 0.52), 12)

    tray_lip = rounded_rect(192, 190, 640, 92, 44)
    rgb("FFFFFF", 0.1).setFill()
    tray_lip.fill()
    stroke_path(tray_lip, rgb("DCEBFF", 0.25), 6)

    base_shadow = rounded_rect(224, 104, 576, 42, 21)
    rgb("0F172A", 0.12).setFill()
    base_shadow.fill()

    NSGraphicsContext.restoreGraphicsState()
    return rep


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "DropShelfAppIcon.png"
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    rep = draw_icon()
    png_data = rep.representationUsingType_properties_(NSPNGFileType, {})
    if png_data is None or not png_data.writeToFile_atomically_(output_path, True):
        raise SystemExit(f"Could not write icon to {output_path}")


if __name__ == "__main__":
    main()
