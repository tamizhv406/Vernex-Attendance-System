import json
import threading

import cv2
import numpy as np

from app.config import settings

DeepFace = None
DeepFaceImportError = None
liveness_models = None


def get_deepface():
    global DeepFace, DeepFaceImportError
    if DeepFace is not None:
        return DeepFace
    if DeepFaceImportError is not None:
        raise RuntimeError(f"DeepFace failed to import: {DeepFaceImportError}")
    try:
        from deepface import DeepFace as ImportedDeepFace
    except Exception as exc:
        DeepFaceImportError = exc
        raise RuntimeError(f"DeepFace failed to import: {exc}") from exc
    DeepFace = ImportedDeepFace
    try:
        compile_recognition_model()
    except Exception as exc:
        print("recognition model runs uncompiled (slower):", exc)
    return DeepFace


def compile_recognition_model():
    # DeepFace calls the Keras model eagerly, layer by layer. Running it as one compiled graph
    # returns the same vectors several times faster, which is what keeps live video smooth.
    import tensorflow as tf
    from deepface.modules import modeling

    client = modeling.build_model(task="facial_recognition", model_name=settings.face_model)
    if not hasattr(client.model, "predict_on_batch"):
        return
    height, width = client.input_shape
    graph = tf.function(
        lambda batch: client.model(batch, training=False),
        input_signature=[tf.TensorSpec([None, height, width, 3], tf.float32)],
    )

    def forward(img):
        if img.ndim == 3:
            img = np.expand_dims(img, axis=0)
        embeddings = graph(tf.constant(img, dtype=tf.float32)).numpy()
        return embeddings[0].tolist() if embeddings.shape[0] == 1 else embeddings.tolist()

    client.forward = forward


def get_liveness_models():
    global liveness_models
    if liveness_models is None:
        import tensorflow as tf
        from deepface.modules import modeling

        get_deepface()
        fasnet = modeling.build_model(task="spoofing", model_name="Fasnet")
        signature = [tf.TensorSpec([None, 80, 80, 3], tf.float32)]
        liveness_models = [
            (tf.function(lambda batch, model=model: model(batch, training=False), input_signature=signature), scale)
            for model, scale in ((fasnet.first_model, 2.7), (fasnet.second_model, 4))
        ]
    return liveness_models


def judge_liveness(image, boxes):
    # One (verdict, score) per box. The verdict is "live", "spoof" or "uncertain".
    # "uncertain" is its own answer on purpose: a face the model is not sure about is not treated
    # as a photo (nothing is wiped, nobody is paused) and is not treated as real either (it never
    # counts towards attendance and is never stored as an enrollment face).
    # With the check switched off every face is "live" and the score is None.
    scores = liveness_scores(image, boxes)
    if scores is None:
        return [("live", None)] * len(boxes)
    return [(liveness_verdict(score), score) for score in scores]


def liveness_verdict(score):
    if score != score or score < settings.face_liveness_threshold:
        return "spoof"
    return "live" if score >= settings.face_liveness_confident else "uncertain"


def check_liveness(image, boxes):
    # True only for a face judged live with confidence.
    return [verdict == "live" for verdict, _ in judge_liveness(image, boxes)]


def liveness_scores(image, boxes):
    # MiniFASNet looks at each face together with its surroundings: a printed photo or a phone
    # screen shows edges, glare and flat texture that a real face in a room does not.
    # Returns the "real face" probability per box (the two models' votes averaged), or None when
    # the check is switched off. Checked against DeepFace's own Fasnet.analyze on 300 faces: same
    # class every time, scores equal to 0.000002.
    if not settings.face_liveness:
        return None
    if not boxes:
        return []
    try:
        import tensorflow as tf
        from deepface.models.spoofing.FasNetUtils import crop

        votes = np.zeros((len(boxes), 3))
        for model, scale in get_liveness_models():
            crops = np.stack([crop(image, tuple(box), scale, 80, 80) for box in boxes]).astype(np.float32)
            logits = model(tf.constant(crops)).numpy()
            exps = np.exp(logits - logits.max(axis=1, keepdims=True))
            votes += exps / exps.sum(axis=1, keepdims=True)
    except Exception as exc:
        raise RuntimeError(f"Liveness check failed: {exc}") from exc
    # Column 1 is the "real face" class; the two models' votes are averaged.
    return [float(score) for score in votes[:, 1] / 2]


ENROLLMENT_STEPS = ["front", "left", "right", "close", "far", "with_specs"]


# The detector's box is widened by this share before it is scaled to the model input. Facenet was
# trained on faces with some forehead, chin and cheek around them, not on a tight box.
FACE_CROP_MARGIN = 0.20


def model_label():
    # Stored with every embedding. Vectors from different models, or from differently prepared
    # face crops, are not comparable, so each preparation has its own label.
    if settings.face_pipeline == "legacy":
        return f"DeepFace-{settings.face_model}-{settings.face_normalization}"
    return f"Vernex2-{settings.face_model}-{settings.face_normalization}"


def face_crop(image, box, left_eye, right_eye, size):
    # One warp from the frame straight to the model input: eyes level, the widened box filling the
    # whole input. No black bars, and a face at the frame edge is continued instead of cut to black.
    x, y, w, h = box
    center = (x + w / 2, y + h / 2)
    angle = 0.0
    if left_eye is not None and right_eye is not None:
        angle = float(np.degrees(np.arctan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0])))
    crop_w, crop_h = w * (1 + FACE_CROP_MARGIN), h * (1 + FACE_CROP_MARGIN)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    matrix[0, 2] += crop_w / 2 - center[0]
    matrix[1, 2] += crop_h / 2 - center[1]
    matrix[0] *= size[1] / crop_w
    matrix[1] *= size[0] / crop_h
    return cv2.warpAffine(image, matrix, (size[1], size[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def embed_crops(crops):
    # crops: BGR uint8 at the model's input size. The model was trained on RGB.
    from deepface.modules import modeling, preprocessing

    client = modeling.build_model(task="facial_recognition", model_name=settings.face_model)
    batch = np.ascontiguousarray(np.stack(crops)[..., ::-1], dtype=np.float32) / 255.0
    batch = preprocessing.normalize_input(batch, normalization=settings.face_normalization)
    return np.asarray(client.forward(batch), dtype=float).reshape(len(crops), -1).tolist()


def detect_faces(image):
    # YOLO finds every face in the frame, then the embedding model encodes each one.
    # Both are pretrained. We do not train any model here.
    # Enrollment and the scanner both come through here (enrollment in its two halves, below),
    # so a face is prepared the same way in both.
    return embed_faces(image, locate_faces(image))


def locate_faces(image):
    # The detector half: where the faces are, how sure the detector is and how the head is turned.
    # No vectors yet. Enrollment looks at a frame with this first and only pays for the embedding
    # model on frames that are good enough to keep.
    if settings.face_pipeline == "legacy":
        return detect_faces_legacy(image)
    get_deepface()
    try:
        from deepface.modules import modeling

        detector = modeling.build_model(task="face_detector", model_name=settings.face_detector)
        found = [area for area in detector.detect_faces(image) if float(area.confidence or 0) >= settings.face_detection_confidence]
    except Exception as exc:
        raise RuntimeError(f"Face detection failed: {exc}") from exc
    return [{
        "box": [int(area.x), int(area.y), int(area.w), int(area.h)],
        "detection_confidence": float(area.confidence),
        "turn": head_turn({"x": area.x, "w": area.w, "left_eye": area.left_eye, "right_eye": area.right_eye}),
        "area": area,
    } for area in found]


def embed_faces(image, faces):
    # The embedding half: adds "embedding" to each located face, all of them in one batch.
    # The crop is the same one for every caller: detector box, widened, eyes levelled, model input size.
    todo = [face for face in faces if "embedding" not in face]
    if not todo:
        return faces
    try:
        from deepface.modules import modeling

        size = modeling.build_model(task="facial_recognition", model_name=settings.face_model).input_shape
        areas = [face.pop("area") for face in todo]
        crops = [face_crop(image, (area.x, area.y, area.w, area.h), area.left_eye, area.right_eye, size) for area in areas]
        for face, embedding in zip(todo, embed_crops(crops)):
            face["embedding"] = embedding
    except Exception as exc:
        raise RuntimeError(f"Face detection failed: {exc}") from exc
    return faces


def detect_faces_legacy(image):
    # The original preparation (DeepFace.represent: tight box, black bars, BGR). Kept so vectors
    # enrolled before FACE_PIPELINE existed can still be matched with FACE_PIPELINE=legacy.
    deepface = get_deepface()
    try:
        reps = deepface.represent(
            image,
            model_name=settings.face_model,
            detector_backend=settings.face_detector,
            enforce_detection=False,
            align=True,
            normalization=settings.face_normalization,
        )
    except Exception as exc:
        raise RuntimeError(f"Face detection failed: {exc}") from exc

    faces = []
    for rep in reps:
        # With enforce_detection=False a frame without faces comes back as one
        # zero-confidence "face" covering the whole image, so drop weak detections.
        confidence = float(rep.get("face_confidence") or 0)
        if confidence < settings.face_detection_confidence:
            continue
        area = rep["facial_area"]
        faces.append({
            "box": [int(area["x"]), int(area["y"]), int(area["w"]), int(area["h"])],
            "embedding": rep["embedding"],
            "detection_confidence": confidence,
            "turn": head_turn(area),
        })
    return faces


def head_turn(area):
    # When the head turns, the eyes slide sideways inside the face box. The value is that shift as a
    # share of the box width: about 0 looking straight, positive when turned to the person's own left.
    left_eye, right_eye = area.get("left_eye"), area.get("right_eye")
    if not left_eye or not right_eye or not area["w"]:
        return None
    eyes_x = (left_eye[0] + right_eye[0]) / 2
    return float((eyes_x - (area["x"] + area["w"] / 2)) / area["w"])


def warm_up():
    # Loading the models takes around half a minute, so do it at startup instead of on the first scan.
    try:
        blank = np.zeros((160, 160, 3), dtype=np.uint8)
        detect_faces(blank)
        check_liveness(blank, [(40, 40, 80, 80)])
        print("face models ready")
    except Exception as exc:
        print("face models failed to load:", exc)


def usable_vector(vector, size=None):
    # A vector that can be compared at all: numbers only, none of them NaN or infinite, not all zero,
    # and of the expected length when one is given.
    try:
        vector = np.asarray(vector, dtype=float)
    except (TypeError, ValueError):
        return False
    if vector.ndim != 1 or vector.size == 0 or (size is not None and vector.size != size):
        return False
    return bool(np.isfinite(vector).all()) and float(np.linalg.norm(vector)) > 0


def build_gallery(embeddings, mode=None):
    # Parse stored vectors once per frame so every detected face reuses them.
    # mode: "centroid" or "individual"; the FACE_GALLERY setting when not given.
    # A stored vector that is damaged or of another length is left out: it must never be matched,
    # and one bad row must not stop everyone else in the batch from being recognized.
    embeddings = list(embeddings)
    parsed = []
    for item in embeddings:
        try:
            vector = json.loads(item.embedding_vector)
        except (TypeError, ValueError):
            continue
        if usable_vector(vector):
            parsed.append((item, vector))
    # Vectors of one model all have one length; the odd ones out are the damaged ones.
    lengths = [len(vector) for _, vector in parsed]
    usual = max(set(lengths), key=lengths.count) if lengths else None
    parsed = [entry for entry in parsed if len(entry[1]) == usual]
    if len(parsed) != len(embeddings):
        print("gallery: skipped", len(embeddings) - len(parsed), "unusable stored vectors")
    embeddings = [item for item, _ in parsed]
    if not embeddings:
        return embeddings, None
    matrix = unit_rows(np.array([vector for _, vector in parsed], dtype=float))
    if (mode or settings.face_gallery) == "individual":
        return embeddings, matrix
    # One vector per person: the average of their enrollment vectors, each scaled to unit length
    # first so no single capture dominates. Measured against comparing with every stored vector
    # separately, this recognizes more enrolled faces at the same false-accept rate.
    people = {}
    for index, item in enumerate(embeddings):
        people.setdefault(item.person_id, []).append(index)
    items = [embeddings[indexes[0]] for indexes in people.values()]
    return items, unit_rows(np.array([matrix[indexes].mean(axis=0) for indexes in people.values()]))


def unit_rows(matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def identify(live_embedding, gallery):
    # Who a face is, or why it cannot be named. Always answers with a status:
    #   "matched"   - one person clears the threshold and leads everyone else by the margin
    #   "ambiguous" - clears the threshold but a second person is nearly as close; never guessed
    #   "unknown"   - nobody in this gallery is close enough (or the vector is unusable)
    # The closest person and the runner-up are reported in every case, for the diagnostic log.
    items, matrix = gallery
    answer = {"status": "unknown", "embedding": None, "confidence": 0.0, "runner_up_id": None, "runner_up_score": None}
    if matrix is None or not usable_vector(live_embedding, matrix.shape[1]):
        return answer
    live = np.array(live_embedding, dtype=float)
    scores = matrix @ (live / np.linalg.norm(live))
    index = int(np.argmax(scores))
    person_id = items[index].person_id
    answer.update(embedding=items[index], confidence=float(scores[index]))
    others = [(float(score), item.person_id) for item, score in zip(items, scores) if item.person_id != person_id]
    if others:
        answer["runner_up_score"], answer["runner_up_id"] = max(others, key=lambda entry: entry[0])
    if scores[index] < settings.face_match_threshold:
        return answer
    # A face that looks almost as much like a second person is ambiguous, so it is never named.
    if others and scores[index] - answer["runner_up_score"] < settings.face_match_margin:
        answer["status"] = "ambiguous"
        return answer
    answer["status"] = "matched"
    return answer


def best_match(live_embedding, gallery):
    # The matched person, or None when the face is unknown or ambiguous.
    answer = identify(live_embedding, gallery)
    if answer["status"] != "matched":
        return None
    return {"embedding": answer["embedding"], "confidence": answer["confidence"]}


# The models are shared by every scanner and every enrollment. They run one frame at a time: two
# frames in the models at once are not faster on one machine, only slower and hungrier for memory.
model_lock = threading.Lock()


def run_models(function, *args):
    with model_lock:
        return function(*args)
