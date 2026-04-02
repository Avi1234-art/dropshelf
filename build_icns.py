#!/usr/bin/env python3
"""
Build a standard .icns file from a source PNG.
"""

import os
import struct
import sys

from AppKit import (
    NSBitmapImageRep,
    NSCompositingOperationCopy,
    NSDeviceRGBColorSpace,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSPNGFileType,
)


ICON_TYPES = [
    ("icp4", 16),
    ("icp5", 32),
    ("icp6", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
]


def png_bytes_for_size(image, size):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
        None,
        size,
        size,
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
    image.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(0, 0, size, size),
        NSMakeRect(0, 0, image.size().width, image.size().height),
        NSCompositingOperationCopy,
        1.0,
    )
    NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(NSPNGFileType, {})
    return bytes(data)


def build_icns(source_png, output_path):
    image = NSImage.alloc().initWithContentsOfFile_(source_png)
    if not image or not image.isValid():
        raise SystemExit(f"Could not read icon source: {source_png}")

    chunks = []
    total_size = 8
    for icon_type, size in ICON_TYPES:
        payload = png_bytes_for_size(image, size)
        chunk = icon_type.encode("ascii") + struct.pack(">I", len(payload) + 8) + payload
        chunks.append(chunk)
        total_size += len(chunk)

    with open(output_path, "wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", total_size))
        for chunk in chunks:
            f.write(chunk)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_icns.py SOURCE_PNG OUTPUT_ICNS")

    source_png = os.path.abspath(sys.argv[1])
    output_path = os.path.abspath(sys.argv[2])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    build_icns(source_png, output_path)


if __name__ == "__main__":
    main()
