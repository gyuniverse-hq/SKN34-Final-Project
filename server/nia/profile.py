"""Experimental one-photo features. Geometric ROIs are not NIA annotations."""

import time

import cv2

from .imaging import decode

ROI_METHOD = "opencv_haar_facebox_proportions_v1"
# Image-left/right refer to the displayed image, not the subject's anatomy.
REGIONS = {
    0: ("full_image", None),
    1: ("forehead", (.22, -.08, .78, .22)),
    2: ("glabella", (.42, .23, .58, .39)),
    3: ("eye_image_left", (.02, .28, .28, .47)),
    4: ("eye_image_right", (.72, .28, .98, .47)),
    5: ("cheek_image_left", (.08, .48, .36, .73)),
    6: ("cheek_image_right", (.64, .48, .92, .73)),
    7: ("lips", (.27, .73, .73, .88)),
    8: ("chin", (.25, .84, .75, 1.04)),
}
# Explicit schema: preserve separate areas, scales and class/regression heads.
FEATURES = {
    "dryness": ("class/dryness", {"dryness": [7]}),
    "moisture": ("regression/moisture", {"forehead_moisture": [1], "cheek_moisture": [5, 6], "chin_moisture": [8]}),
    "pore_grade": ("class/pore", {"pore": [5, 6]}),
    "pore_value": ("regression/pore", {"cheek_pore": [5, 6]}),
    "pigmentation_grade": ("class/pigmentation", {"forehead_pigmentation": [1], "cheek_pigmentation": [5, 6]}),
    "pigmentation_value": ("regression/pigmentation", {"pigmentation": [0]}),
    "wrinkle_grade": ("class/wrinkle", {"forehead_wrinkle": [1], "glabellus_wrinkle": [2], "perocular_wrinkle": [3, 4]}),
    "wrinkle_roughness": ("regression/wrinkle_Ra", {"perocular_wrinkle_Ra": [3, 4]}),
    "sagging": ("class/sagging", {"sagging": [8]}),
    "elasticity": ("regression/elasticity_R2", {"forehead_elasticity_R2": [1], "cheek_elasticity_R2": [5, 6], "chin_elasticity_R2": [8]}),
}
UNSUPPORTED = ("acne", "oiliness", "skin_type")


def locate_regions(raw):
    image = decode(raw)
    height, width = image.shape[:2]
    scale = min(1, 900 / max(height, width))
    small = cv2.resize(image, (round(width * scale), round(height * scale)))
    gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        raise ValueError("Face detector is unavailable")
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80))
    if len(faces) == 0:
        raise ValueError("No frontal face detected. Use a clear, upright photo with one face.")
    if len(faces) != 1:
        raise ValueError("Multiple faces detected. Use a photo containing only one face.")
    x, y, w, h = [float(v) / scale for v in faces[0]]
    boxes = {0: [0, 0, width, height]}
    for part, (_, proportions) in REGIONS.items():
        if proportions is None:
            continue
        left, top, right, bottom = proportions
        box = [max(0, round(x + left * w)), max(0, round(y + top * h)),
               min(width, round(x + right * w)), min(height, round(y + bottom * h))]
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            raise ValueError("Face is too close to the image boundary. Use a photo of the complete face.")
        boxes[part] = box
    return dict(original_size=[width, height], face_bbox=[round(x), round(y), round(x+w), round(y+h)],
                method=ROI_METHOD, training_annotation_match=False, boxes=boxes)


def run_profile(raw, engines, job, acne_engine=None, *, features=None,
                unsupported=UNSUPPORTED, include_previews=True):
    start = time.perf_counter()
    features = FEATURES if features is None else features
    roi = locate_regions(raw)
    groups, flat, statuses, provenance = {}, {}, {}, {}
    for feature, (task, areas) in features.items():
        candidates = [e for e in engines.values() if e.config["task"] == task]
        engine = candidates[0] if len(candidates) == 1 else None
        load_error = None
        if engine is not None:
            try:
                engine.load()
            except Exception as error:
                load_error = str(error)
        rows = []
        for area, parts in areas.items():
            for part in parts:
                region = REGIONS[part][0]
                key = f"{feature}_{region}"
                row = dict(key=key, area=area, region=region, facepart=part, status="unavailable", value=None)
                flat[key] = None
                if engine is None:
                    row["error"] = "No unique checkpoint configured for this task"
                elif load_error:
                    row.update(status="failed", error=load_error)
                elif part not in engine.config["areas"].get(area, []):
                    row["error"] = "ROI not configured for this checkpoint"
                else:
                    try:
                        # Each side is prepared independently. Never feed a combined cheek box.
                        options = {} if include_previews else {"preview": False}
                        result = engine.predict(raw, area, roi["boxes"][part], repeats=1, **options)
                        value = result["prediction"].get("grade", result["prediction"].get("value"))
                        row.update(status="predicted", value=value, result=result)
                        flat[key] = value
                        provenance[key] = dict(task=task, model_id=engine.config["id"],
                                               checkpoint_sha256=result["model"]["sha256"],
                                               region=region, crop=result["preprocessing"]["crop"],
                                               unit="grade" if result["mode"] == "class" else result["prediction"]["unit"],
                                               grade_range=[0, result["model"]["outputs"] - 1] if result["mode"] == "class" else None,
                                               original_unit_multiplier=result["prediction"].get("multiplier"))
                    except Exception as error:
                        row.update(status="failed", error=str(error))
                statuses[key] = row["status"]
                rows.append(row)
                job["completed"] += 1
        groups[feature] = dict(task=task, rows=rows)
    acne = None
    unsupported = [key for key in unsupported if key != "acne" or acne_engine is None]
    if acne_engine is not None:
        flat["acne"] = None
        try:
            acne = acne_engine.predict(raw)
            flat["acne"] = acne["label"]
            statuses["acne"] = "predicted"
            provenance["acne"] = dict(
                task="acne/binary", model_id="acne-research-v1",
                checkpoint_sha256=acne["model_sha256"], region="full_image",
                crop=roi["boxes"][0], unit="binary_label", grade_range=None,
                original_unit_multiplier=None)
        except Exception as error:
            acne = dict(status="failed", label=None, score=None, error=str(error))
            statuses["acne"] = "failed"
        job["completed"] += 1
    for key in unsupported:
        flat[key] = None
        statuses[key] = "unsupported"
    predicted = sum(value == "predicted" for value in statuses.values())
    expected = sum(len(parts) for _, areas in features.values() for parts in areas.values()) + int(acne_engine is not None)
    result = dict(status="complete" if predicted == expected else "partial" if predicted else "no_results",
                predicted=predicted, expected=expected, roi=roi, groups=groups,
                server_ms=(time.perf_counter() - start) * 1000,
                ml_input=dict(schema_version="nia-photo-features-v2" if acne_engine is not None else "nia-photo-features-v1", features=flat, feature_status=statuses,
                              provenance=provenance, roi_method=ROI_METHOD,
                              validation_status="experimental_unvalidated",
                              training_roi_match=False, softmax_calibrated=False,
                              unsupported=unsupported))
    if acne is not None:
        result["acne"] = acne
        result["ml_input"]["acne"] = acne
    return result
