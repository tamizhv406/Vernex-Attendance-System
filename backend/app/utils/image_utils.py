import base64
import re
import cv2
import numpy as np


def decode_base64_image(image_base64: str):
    cleaned = re.sub(r"^data:image/.+;base64,", "", image_base64 or "")
    raw = base64.b64decode(cleaned)
    return decode_image_bytes(raw)


def decode_image_bytes(raw: bytes):
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
