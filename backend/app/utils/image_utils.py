import base64
import binascii
import re
import zlib

import cv2
import numpy as np


class ImageTooLarge(ValueError):
    """An image whose pixels would not fit in memory safely, however small its file is."""


# Camera frames are JPEG (the browser's canvas.toBlob) and, from older clients and tests, PNG. Nothing
# else is ever needed, so nothing else is read: every other format, MPO and TIFF and GIF included, is
# refused from its first bytes, before any decoder sees it. The format is read from the bytes
# themselves, never from a file name or a content type the client chose.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_START = b"\xff\xd8"
# JPEG frame headers (SOF0-3, 5-7, 9-11, 13-15) carry the size. C4 (DHT), C8 (JPG) and CC (DAC) do not.
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
# Markers that are only two bytes long, without a length after them.
JPEG_STANDALONE_MARKERS = {0x01, *range(0xD0, 0xD8)}
# The largest side a JPEG can describe. A PNG may claim more; no frame is ever that wide.
MAX_SIDE = 65535


def decode_base64_image(image_base64: str, max_pixels: int | None = None):
    # None when the text is not base64 or not an image: the caller answers "Invalid image".
    cleaned = re.sub(r"^data:image/.+;base64,", "", image_base64 or "")
    try:
        raw = base64.b64decode(cleaned)
    except (binascii.Error, ValueError):
        return None
    return decode_image_bytes(raw, max_pixels)


def decode_image_bytes(raw: bytes, max_pixels: int | None = None):
    # None when the bytes are not a JPEG or PNG image. A compressed file a few kilobytes long can unpack
    # into gigabytes, so the size is read from the file's header first and the pixels are only unpacked
    # when there are at most max_pixels of them.
    if not raw:
        return None
    size = image_size(raw)
    if size is None:
        return None
    width, height = size
    if width > MAX_SIDE or height > MAX_SIDE or (max_pixels and width * height > max_pixels):
        limit = f"at most {max_pixels:,} pixels" if max_pixels else f"at most {MAX_SIDE:,} pixels a side"
        raise ImageTooLarge(f"The image is {width} x {height} pixels; {limit} are accepted.")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    # The pixels must be the size the header said; a file that says one thing and holds another is not
    # a camera frame. A photo turned by its EXIF orientation comes out with the two sides swapped.
    if image is None or image.shape[:2] not in ((height, width), (width, height)):
        return None
    return image


def image_size(raw: bytes):
    """(width, height) of a JPEG or PNG image, read from its header alone. None for anything else."""
    if raw.startswith(PNG_SIGNATURE):
        size = _png_size(raw)
    elif raw.startswith(JPEG_START):
        size = _jpeg_size(raw)
    else:
        return None
    if size is None or size[0] < 1 or size[1] < 1:
        return None
    return size


def _png_size(raw: bytes):
    # The first chunk must be IHDR, 13 bytes long, with a checksum that matches it.
    if len(raw) < 33:
        return None
    length, kind, data, crc = int.from_bytes(raw[8:12], "big"), raw[12:16], raw[16:29], raw[29:33]
    if length != 13 or kind != b"IHDR" or zlib.crc32(kind + data) != int.from_bytes(crc, "big"):
        return None
    return int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big")


def _jpeg_size(raw: bytes):
    # Walks the segments before the first scan until a frame header names the size. A scan or the end
    # of the image before that, a segment longer than the file, or an MPO segment means: not accepted.
    position, end = 2, len(raw)
    while position < end:
        if raw[position] != 0xFF:
            return None
        while position < end and raw[position] == 0xFF:
            position += 1
        if position >= end:
            return None
        marker = raw[position]
        position += 1
        if marker in JPEG_STANDALONE_MARKERS:
            continue
        if marker in (0x00, 0xD8, 0xD9, 0xDA):
            return None
        if position + 2 > end:
            return None
        length = int.from_bytes(raw[position:position + 2], "big")
        if length < 2 or position + length > end:
            return None
        segment = raw[position + 2:position + length]
        # An MPO file (several pictures in one, from some cameras) is a JPEG with this APP2 segment.
        if marker == 0xE2 and segment.startswith(b"MPF\x00"):
            return None
        if marker in JPEG_FRAME_MARKERS:
            if len(segment) < 5:
                return None
            return int.from_bytes(segment[3:5], "big"), int.from_bytes(segment[1:3], "big")
        position += length
    return None
