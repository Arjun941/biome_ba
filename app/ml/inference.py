"""
app/ml/inference.py — ONNX model inference singleton.

The ConvNeXt-Large-MLP (iNat2021) model is loaded ONCE at module import time
(or lazily on first call if ML_LAZY_LOAD=true). A threading.Lock protects
concurrent inference calls.

Inference pipeline mirrors test.py exactly:
  TRANSFORM → numpy array → ONNX session.run() → softmax → argsort → top-k
"""

import io
import json
import logging
import os
import threading
from typing import List, Dict, Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ── Preprocessing constants (loaded from config.json) ──────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_cfg_path = os.environ.get("ML_CONFIG_PATH", "config.json")
if not os.path.isabs(_cfg_path):
    _cfg_path = os.path.join(_BASE_DIR, _cfg_path)

_model_path = os.environ.get("ML_MODEL_PATH", "model_fp16.onnx")
if not os.path.isabs(_model_path):
    _model_path = os.path.join(_BASE_DIR, _model_path)

# Load config at module level so LABEL_NAMES is always available
with open(_cfg_path, encoding="utf-8") as _f:
    _cfg = json.load(_f)

LABEL_NAMES: List[str] = _cfg["label_names"]
LABEL_MAP: Dict[str, str] = _cfg.get("label_map", {})
NUM_CLASSES: int = _cfg["num_classes"]
ARCH: str = _cfg["architecture"]

_pc = _cfg["pretrained_cfg"]
_H = _W = _pc["input_size"][1]
_MEAN: List[float] = _pc["mean"]
_STD: List[float] = _pc["std"]
_RESIZE_TO: int = int(_H / _pc["crop_pct"])

# ── Internal state ────────────────────────────────────────────────────────────
_lock = threading.Lock()
_session = None          # onnxruntime.InferenceSession


def _normalize(arr: np.ndarray, mean: List[float], std: List[float]) -> np.ndarray:
    """Channel-wise normalization matching torchvision.transforms.Normalize."""
    arr = arr.astype(np.float32) / 255.0
    mean_arr = np.array(mean, dtype=np.float32).reshape(3, 1, 1)
    std_arr = np.array(std, dtype=np.float32).reshape(3, 1, 1)
    return (arr - mean_arr) / std_arr


def _preprocess(pil_img: Image.Image) -> np.ndarray:
    """
    Apply the same preprocessing pipeline as test.py TRANSFORM:
      1. Resize shortest edge to _RESIZE_TO (bicubic)
      2. Centre-crop to (_H, _W)
      3. Convert to (C, H, W) float32 tensor
      4. Normalize with pretrained mean/std
    Returns shape (1, 3, H, W) float32 numpy array.
    """
    # Step 1 – Resize shortest edge while maintaining aspect ratio
    w, h = pil_img.size
    scale = _RESIZE_TO / min(w, h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    pil_img = pil_img.resize((new_w, new_h), Image.BICUBIC)

    # Step 2 – Centre crop
    left = (new_w - _W) // 2
    top = (new_h - _H) // 2
    pil_img = pil_img.crop((left, top, left + _W, top + _H))

    # Step 3 – HWC → CHW
    arr = np.array(pil_img, dtype=np.float32).transpose(2, 0, 1)  # (3, H, W)

    # Step 4 – Normalize
    arr = _normalize(arr, _MEAN, _STD)

    return arr[np.newaxis, :]  # (1, 3, H, W)


def load_model() -> None:
    """
    Load the ONNX inference session. Called at app startup (or lazily).
    Thread-safe — subsequent calls while already loaded are no-ops.
    """
    global _session
    if _session is not None:
        return

    if not os.path.exists(_model_path):
        logger.warning(
            "ML model not found at %s — /identify will return empty results.", _model_path
        )
        return

    import onnxruntime as ort  # lazy import so tests can run without onnxruntime

    logger.info("Loading ONNX model from %s …", _model_path)
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.intra_op_num_threads = 4

    # Prefer CUDA if available, fall back to CPU
    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if "CUDAExecutionProvider" in ort.get_available_providers()
        else ["CPUExecutionProvider"]
    )

    _session = ort.InferenceSession(_model_path, sess_options=so, providers=providers)
    logger.info("Model loaded. Input name: %s", _session.get_inputs()[0].name)


def predict(pil_img: Image.Image, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Run inference on a PIL Image and return the top-k predictions.

    Args:
        pil_img:  RGB PIL Image (any size — preprocessing handles resizing).
        top_k:    Number of top predictions to return (clamped to NUM_CLASSES).

    Returns:
        List of dicts: [{"rank", "species", "common_name", "confidence", "class_index"}]
        Returns [] if the model is not loaded.
    """
    global _session

    top_k = max(1, min(top_k, NUM_CLASSES))

    if _session is None:
        load_model()  # attempt lazy load

    if _session is None:
        return []  # model still not available

    x = _preprocess(pil_img.convert("RGB"))

    with _lock:
        # The ONNX FP16 model accepts float32 input (ORT handles casting internally)
        input_name = _session.get_inputs()[0].name
        logits = _session.run(["logits"], {input_name: x})[0][0]  # shape (NUM_CLASSES,)

    # Softmax (numerically stable)
    logits = logits.astype(np.float64)
    e = np.exp(logits - logits.max())
    probs = e / e.sum()

    # Top-k indices sorted by confidence descending
    top_indices = np.argsort(probs)[::-1][:top_k].tolist()

    return [
        {
            "rank": rank + 1,
            "species": LABEL_NAMES[idx],
            "common_name": LABEL_MAP.get(LABEL_NAMES[idx], ""),
            "confidence": round(float(probs[idx]), 6),
            "class_index": idx,
        }
        for rank, idx in enumerate(top_indices)
    ]


def predict_from_b64(b64_string: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Convenience wrapper: decode a base64 image string and run inference.

    Args:
        b64_string: Raw base64 string (no data-URL prefix required, but handled).
        top_k:      Number of predictions.

    Returns:
        Same as predict().

    Raises:
        ValueError: If the base64 string cannot be decoded as an image.
    """
    import base64

    # Strip data URL prefix if present (e.g., "data:image/jpeg;base64,...")
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(b64_string)
        pil_img = Image.open(io.BytesIO(img_bytes))
    except Exception as exc:
        raise ValueError(f"Cannot decode image: {exc}") from exc

    return predict(pil_img, top_k=top_k)
