# SPDX-License-Identifier: MIT
"""Deep-learning face frontend: detect, align, embed.

The pipeline is the standard InsightFace recipe, implemented directly on
onnxruntime, numpy and opencv so that the only Python dependencies are wheels
that install on Apple Silicon without a compiler.

  1. SCRFD predicts a bounding box and five landmarks (eye centres, nose tip,
     mouth corners) for every face in the image.
  2. A similarity transform maps those five points onto the canonical ArcFace
     template, producing a 112x112 crop in which the eyes and mouth sit at fixed
     pixel positions for every subject.
  3. The recognition network maps the crop to a 512-dimensional embedding, which
     is scaled to unit L2 norm so that an inner product is the cosine similarity.

Step 3 is what the encrypted circuit consumes: after normalisation the score the
server computes is an inner product, which is the one operation RNS-CKKS
evaluates at multiplicative depth one.
"""

import os

import cv2
import numpy as np
import onnxruntime as ort

# Canonical five-point template for a 112x112 ArcFace crop, in pixels.
ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],  # left eye centre
        [73.5318, 51.5014],  # right eye centre
        [56.0252, 71.7366],  # nose tip
        [41.5493, 92.3655],  # left mouth corner
        [70.7299, 92.2041],  # right mouth corner
    ],
    dtype=np.float32,
)


def make_session(path, threads):
    """Builds a CPU inference session with a fixed thread count."""
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3  # errors only
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])


def similarity_transform(src, dst):
    """Least-squares similarity transform (rotation, uniform scale, translation).

    This is the Umeyama estimator: it returns the 2x3 matrix M minimising
    the sum of squared distances between M applied to `src` and `dst`, which is
    the transform ArcFace alignment is defined in terms of.
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n = src.shape[0]
    mu_src, mu_dst = src.mean(axis=0), dst.mean(axis=0)
    src_c, dst_c = src - mu_src, dst - mu_dst

    sigma = dst_c.T @ src_c / n
    u, singular, vt = np.linalg.svd(sigma)
    # Reflections are not similarities, so the smaller singular direction is
    # flipped when the estimated rotation would have negative determinant.
    signs = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        signs[-1] = -1.0
    rotation = u @ np.diag(signs) @ vt
    variance = (src_c ** 2).sum() / n
    scale = float((singular * signs).sum() / variance) if variance > 0 else 1.0

    matrix = np.zeros((2, 3), dtype=np.float64)
    matrix[:, :2] = scale * rotation
    matrix[:, 2] = mu_dst - scale * (rotation @ mu_src)
    return matrix.astype(np.float32)


def align(image, landmarks, size=112):
    """Warps the face onto the canonical template."""
    matrix = similarity_transform(landmarks, ARCFACE_TEMPLATE * (size / 112.0))
    return cv2.warpAffine(image, matrix, (size, size), borderValue=0.0)


class Detector:
    """SCRFD face detector.

    The exported graph emits nine tensors: classification scores, box offsets and
    landmark offsets for each of the three feature strides 8, 16 and 32. Each
    location carries two anchors, and every offset is expressed in units of its
    stride, so decoding multiplies by the stride and adds the anchor centre.
    """

    STRIDES = (8, 16, 32)
    ANCHORS = 2

    def __init__(self, path, size=320, score_threshold=0.4, nms_threshold=0.4, threads=4):
        self.session = make_session(path, threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.size = size
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self._centres = {}

    def _anchor_centres(self, stride):
        key = (self.size, stride)
        if key not in self._centres:
            rows = cols = self.size // stride
            ys, xs = np.mgrid[:rows, :cols]
            grid = np.stack([xs, ys], axis=-1).astype(np.float32).reshape(-1, 2) * stride
            self._centres[key] = np.repeat(grid, self.ANCHORS, axis=0)
        return self._centres[key]

    def detect(self, image):
        """Returns (box, landmarks, score) for the primary face, or None."""
        height, width = image.shape[:2]
        ratio = min(self.size / width, self.size / height)
        new_w, new_h = int(round(width * ratio)), int(round(height * ratio))
        canvas = np.zeros((self.size, self.size, 3), dtype=np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(image, (new_w, new_h))

        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 128, (self.size, self.size), (127.5, 127.5, 127.5), swapRB=True
        )
        outputs = self.session.run(self.output_names, {self.input_name: blob})

        scores, boxes, points = [], [], []
        for i, stride in enumerate(self.STRIDES):
            score = outputs[i].reshape(-1)
            keep = score >= self.score_threshold
            if not keep.any():
                continue
            centre = self._anchor_centres(stride)[keep]
            box = outputs[i + 3].reshape(-1, 4)[keep] * stride
            kps = outputs[i + 6].reshape(-1, 10)[keep] * stride
            scores.append(score[keep])
            # Box offsets are distances from the anchor to each of the four edges.
            boxes.append(
                np.stack(
                    [
                        centre[:, 0] - box[:, 0],
                        centre[:, 1] - box[:, 1],
                        centre[:, 0] + box[:, 2],
                        centre[:, 1] + box[:, 3],
                    ],
                    axis=-1,
                )
            )
            points.append(centre[:, None, :] + kps.reshape(-1, 5, 2))
        if not scores:
            return None

        scores = np.concatenate(scores)
        boxes = np.concatenate(boxes) / ratio
        points = np.concatenate(points) / ratio

        widths = boxes[:, 2] - boxes[:, 0]
        heights = boxes[:, 3] - boxes[:, 1]
        keep = cv2.dnn.NMSBoxes(
            np.stack([boxes[:, 0], boxes[:, 1], widths, heights], axis=-1).tolist(),
            scores.tolist(),
            self.score_threshold,
            self.nms_threshold,
        )
        keep = np.asarray(keep).reshape(-1)
        if keep.size == 0:
            return None
        boxes, points, scores = boxes[keep], points[keep], scores[keep]

        # LFW images are centred on the subject, so the largest face nearest the
        # image centre is the one the pair refers to.
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        dx = (boxes[:, 0] + boxes[:, 2]) / 2 - width / 2
        dy = (boxes[:, 1] + boxes[:, 3]) / 2 - height / 2
        best = int(np.argmax(areas / (width * height) - 2.0 * (dx ** 2 + dy ** 2) / (width * height)))
        return boxes[best], points[best], float(scores[best])


class Recognizer:
    """Face recognition network mapping a 112x112 crop to a unit-norm embedding."""

    def __init__(self, path, threads=4):
        self.session = make_session(path, threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        shape = self.session.get_outputs()[0].shape
        self.dim = int(shape[-1]) if isinstance(shape[-1], int) else 512

    def embed(self, crops):
        """Embeds a list of aligned crops. Returns an (n, dim) float64 array."""
        blob = cv2.dnn.blobFromImages(
            crops, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True
        )
        out = self.session.run([self.output_name], {self.input_name: blob})[0]
        out = np.asarray(out, dtype=np.float64)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return out / norms


class Frontend:
    """Detector and recogniser bound together with a fallback crop.

    LFW deep-funnelled images are already registered to a common frame, so the
    rare image whose face the detector misses is handled by the fixed central
    crop that the funnelling procedure implies. Every such image is counted and
    reported, so the fallback never hides silently.
    """

    def __init__(self, detector_path, recognizer_path, size=320, threads=4):
        self.detector = Detector(detector_path, size=size, threads=threads)
        self.recognizer = Recognizer(recognizer_path, threads=threads)
        self.detected = 0
        self.fallback = 0

    def crop(self, image):
        found = self.detector.detect(image)
        if found is not None:
            self.detected += 1
            return align(image, found[1])
        self.fallback += 1
        height, width = image.shape[:2]
        half = int(0.36 * min(height, width))
        cy, cx = height // 2, width // 2
        patch = image[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
        return cv2.resize(patch, (112, 112))

    def embed_paths(self, paths, batch_size=16):
        """Embeds every image path in order, batching the network calls."""
        vectors = []
        for start in range(0, len(paths), batch_size):
            crops = []
            for path in paths[start:start + batch_size]:
                image = cv2.imread(path, cv2.IMREAD_COLOR)
                if image is None:
                    raise SystemExit(f"cannot read image {path}")
                crops.append(self.crop(image))
            vectors.append(self.recognizer.embed(crops))
        return np.concatenate(vectors, axis=0) if vectors else np.zeros((0, self.recognizer.dim))


def find_models(directory):
    """Locates the detector and recogniser inside an InsightFace model pack."""
    detector = recognizer = None
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".onnx"):
            continue
        path = os.path.join(directory, name)
        if name.startswith("det_"):
            detector = path
        elif name.startswith("w600k_"):
            recognizer = path
    if detector is None or recognizer is None:
        raise SystemExit(
            f"{directory} needs a det_*.onnx detector and a w600k_*.onnx recogniser; "
            "run python/fetch_assets.py to download a model pack"
        )
    return detector, recognizer
