import base64
import io
import zlib

import cv2
import numpy as np
import pytest

from app.utils import image_utils
from app.utils.image_utils import ImageTooLarge, decode_base64_image, decode_image_bytes, image_size


def encoded(extension, width=64, height=48, params=None):
    picture = np.zeros((height, width, 3), np.uint8)
    picture[:, : width // 2] = (40, 160, 220)
    flags = [int(value) for pair in (params or {}).items() for value in pair]
    return cv2.imencode(extension, picture, flags)[1].tobytes()


def png_header(width, height, crc_ok=True):
    # A PNG signature and IHDR chunk alone, with no pixel data after it.
    data = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    crc = zlib.crc32(b"IHDR" + data) ^ (0 if crc_ok else 1)
    return image_utils.PNG_SIGNATURE + (13).to_bytes(4, "big") + b"IHDR" + data + crc.to_bytes(4, "big")


def pillow_file(format, frames=1):
    from PIL import Image

    pictures = [Image.new("RGB", (64, 48), (40 * n, 160, 220)) for n in range(frames)]
    out = io.BytesIO()
    pictures[0].save(out, format=format, save_all=frames > 1, append_images=pictures[1:])
    return out.getvalue()


# ---- what is accepted ---------------------------------------------------------------------------

@pytest.mark.parametrize("extension, params", [
    (".jpg", {}),
    (".jpg", {cv2.IMWRITE_JPEG_PROGRESSIVE: 1}),
    (".jpg", {cv2.IMWRITE_JPEG_QUALITY: 30}),
    (".png", {}),
    (".png", {cv2.IMWRITE_PNG_COMPRESSION: 9}),
])
def test_jpeg_and_png_frames_are_read_at_their_size(extension, params):
    raw = encoded(extension, 64, 48, params)

    image = decode_image_bytes(raw, 4096 * 4096)

    assert image_size(raw) == (64, 48) and image.shape == (48, 64, 3)


def test_a_frame_sent_as_base64_with_a_data_url_prefix_is_read():
    text = "data:image/png;base64," + base64.b64encode(encoded(".png", 32, 20)).decode()

    assert decode_base64_image(text, 4096 * 4096).shape == (20, 32, 3)


def test_pillow_is_never_given_the_uploaded_bytes(monkeypatch):
    # The app no longer opens frames with Pillow at all, so its parsers never see untrusted bytes.
    from PIL import Image

    def refuse(*_args, **_kwargs):
        raise AssertionError("Pillow was asked to open an upload")

    monkeypatch.setattr(Image, "open", refuse)
    source = open(image_utils.__file__, encoding="utf-8").read()

    assert decode_image_bytes(encoded(".jpg"), 4096 * 4096).shape == (48, 64, 3)
    assert decode_image_bytes(encoded(".png"), 4096 * 4096).shape == (48, 64, 3)
    assert "PIL" not in source and "Image.open" not in source


# ---- what is refused -----------------------------------------------------------------------------

def test_an_mpo_file_is_refused_even_though_it_starts_like_a_jpeg():
    mpo = pillow_file("MPO", frames=2)
    assert mpo.startswith(b"\xff\xd8") and b"MPF\x00" in mpo

    assert image_size(mpo) is None and decode_image_bytes(mpo, 4096 * 4096) is None


def test_a_jpeg_given_an_mpo_segment_by_hand_is_refused():
    jpeg = encoded(".jpg")
    segment = b"MPF\x00" + b"\x00" * 8
    mpo = jpeg[:2] + b"\xff\xe2" + (len(segment) + 2).to_bytes(2, "big") + segment + jpeg[2:]

    assert decode_jpeg_still_works(jpeg) and decode_image_bytes(mpo, 4096 * 4096) is None


def decode_jpeg_still_works(raw):
    return decode_image_bytes(raw, 4096 * 4096) is not None


@pytest.mark.parametrize("make", [
    lambda: encoded(".bmp"),
    lambda: encoded(".tiff"),
    lambda: encoded(".webp"),
    lambda: pillow_file("GIF"),
    lambda: pillow_file("TIFF"),
    lambda: pillow_file("ICO"),
    lambda: pillow_file("PCX"),
    lambda: b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 64 48\n",
    lambda: b"DDS |\x00\x00\x00" + b"\x00" * 120,
    lambda: b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
    lambda: b"GIF89a" + b"\x00" * 20,
    lambda: b"<svg xmlns='http://www.w3.org/2000/svg'/>",
], ids=["bmp", "tiff", "webp", "gif", "tiff-pillow", "ico", "pcx", "eps", "dds", "pdf", "gif-header", "svg"])
def test_every_other_format_is_refused_before_any_decoder_sees_it(make):
    raw = make()

    assert image_size(raw) is None and decode_image_bytes(raw, 4096 * 4096) is None


@pytest.mark.parametrize("raw", [
    b"\xff\xd8",                                    # a JPEG start and nothing else
    b"\xff\xd8\xff\xd9",                            # start, then end, no frame header
    b"\xff\xd8\xff\xda\x00\x08" + b"\x00" * 6,      # a scan before any frame header
    b"\xff\xd8\xff\xe0\xff\xff" + b"\x00" * 10,     # a segment longer than the file
    b"\xff\xd8\xff\xe0\x00\x01",                    # a segment length below its minimum
    b"\xff\xd8\x00\x00\x00\x00",                    # no marker where one must be
    b"\xff\xd8\xff\xc0\x00\x05\x08\x00",            # a frame header cut short
    b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x00\x00\x40" + b"\x00" * 10,  # a height of 0
    image_utils.PNG_SIGNATURE,                      # a PNG signature and nothing else
    png_header(64, 48, crc_ok=False),               # IHDR with a wrong checksum
    png_header(0, 48),                              # a width of 0
    image_utils.PNG_SIGNATURE + (12).to_bytes(4, "big") + b"IHDR" + b"\x00" * 17,  # IHDR of the wrong length
    image_utils.PNG_SIGNATURE + (13).to_bytes(4, "big") + b"IDAT" + b"\x00" * 17,  # first chunk not IHDR
], ids=["jpeg-start-only", "jpeg-no-frame", "jpeg-scan-first", "jpeg-long-segment", "jpeg-short-length", "jpeg-no-marker",
        "jpeg-cut-frame-header", "jpeg-zero-height", "png-signature-only", "png-bad-crc", "png-zero-width", "png-wrong-ihdr-length", "png-no-ihdr"])
def test_malformed_headers_are_refused(raw):
    assert image_size(raw) is None and decode_image_bytes(raw, 4096 * 4096) is None


def test_a_valid_header_with_no_pixels_after_it_is_refused():
    # The header passes, but there is nothing to decode: OpenCV gives nothing back, and neither do we.
    assert image_size(png_header(64, 48)) == (64, 48)
    assert decode_image_bytes(png_header(64, 48), 4096 * 4096) is None


def test_pixels_of_another_size_than_the_header_says_are_refused():
    real = encoded(".png", 64, 48)
    data = (65).to_bytes(4, "big") + (48).to_bytes(4, "big") + real[24:29]
    lying = real[:16] + data + zlib.crc32(b"IHDR" + data).to_bytes(4, "big") + real[33:]

    assert image_size(lying) == (65, 48) and decode_image_bytes(lying, 4096 * 4096) is None


def test_empty_and_missing_bytes_are_refused():
    assert decode_image_bytes(b"", 100) is None and decode_image_bytes(None, 100) is None
    assert decode_base64_image("%%%not base64%%%", 100) is None and decode_base64_image("", 100) is None


# ---- size limits, read from the header before anything is unpacked --------------------------------

@pytest.mark.parametrize("extension", [".jpg", ".png"])
def test_more_pixels_than_allowed_is_too_large(extension):
    raw = encoded(extension, 300, 200)

    with pytest.raises(ImageTooLarge) as refused:
        decode_image_bytes(raw, 300 * 200 - 1)
    assert "300 x 200" in str(refused.value)
    assert decode_image_bytes(raw, 300 * 200).shape == (200, 300, 3)


def test_a_side_beyond_any_frame_is_too_large_even_without_a_pixel_limit(monkeypatch):
    # No pixels are ever unpacked for it: the header alone decides.
    monkeypatch.setattr(image_utils.cv2, "imdecode", lambda *_: pytest.fail("pixels were unpacked"))

    with pytest.raises(ImageTooLarge):
        decode_image_bytes(png_header(70000, 10))
    with pytest.raises(ImageTooLarge):
        decode_image_bytes(png_header(100_000, 100_000), 4096 * 4096)


# ---- the routes: the bytes decide, not the name or type the client gave -----------------------------

def test_a_bmp_sent_as_frame_jpg_with_type_image_jpeg_is_invalid(client):
    answer = client.post("/face/recognize", files={"image": ("frame.jpg", encoded(".bmp"), "image/jpeg")})

    assert answer.status_code == 200 and answer.json()["message"] == "Invalid image"


def test_an_mpo_upload_is_invalid_on_both_face_routes(client):
    from app.models.person import Person

    with client.db() as db:
        person = Person(person_code="STF-1", full_name="Staff One", person_type="admin")
        db.add(person)
        db.commit()
        person_id = person.id
    assert client.post(f"/face/enrollment/start/{person_id}?consent=true").status_code == 200
    mpo = pillow_file("MPO", frames=2)

    recognize = client.post("/face/recognize", files={"image": ("frame.jpg", mpo, "image/jpeg")})
    enroll = client.post("/face/enrollment/frame", files={"image": ("frame.jpg", mpo, "image/jpeg")}, data={"person_id": str(person_id), "current_step": "front"})

    assert recognize.json()["message"] == "Invalid image"
    assert enroll.json()["accepted"] is False and enroll.json()["message"] == "Invalid image", enroll.text


def test_a_real_jpeg_named_as_a_gif_is_still_read(client):
    from app.routes import face_routes

    face_routes.detect_faces, real = (lambda image: []), face_routes.detect_faces
    try:
        answer = client.post("/face/recognize", files={"image": ("frame.gif", encoded(".jpg", 320, 240), "image/gif")})
    finally:
        face_routes.detect_faces = real

    assert answer.json()["status"] == "no_face" and answer.json()["frame"] == {"width": 320, "height": 240}
