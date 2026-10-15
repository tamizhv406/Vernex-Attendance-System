import base64
import binascii
import io
import re

import cv2
import numpy as np
from PIL import Image


class ImageTooLarge(ValueError):
    """An image whose pixels would not fit in memory safely, however small its file is."""


def decode_base64_image(image_base64: str, max_pixels: int | None = None):
    # None when the text is not base64 or not an image: the caller answers "Invalid image".
    cleaned = re.sub(r"^data:image/.+;base64,", "", image_base64 or "")
    try:
        raw = base64.b64decode(cleaned)
    except (binascii.Error, ValueError):
        return None
    return decode_image_bytes(raw, max_pixels)


def decode_image_bytes(raw: bytes, max_pixels: int | None = None):
    # None when the bytes are not an image. A compressed file a few kilobytes long can unpack into
    # gigabytes, so the size is read from the file's header first and the pixels are only unpacked
    # when there are at most max_pixels of them.
    if not raw:
        return None
    if max_pixels:
        try:
            width, height = Image.open(io.BytesIO(raw)).size
        except Exception:
            return None
        if width * height > max_pixels:
            raise ImageTooLarge(f"The image is {width} x {height} pixels; at most {max_pixels:,} pixels are accepted.")
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
