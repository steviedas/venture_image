#!/usr/bin/env python3
"""
Multi-photo scan splitter with deskew, border trim, debug overlays, and fallbacks.

- Recursively processes images under PATH_TO_PROCESS.
- Detects individual photos in a scan using LAB-L Otsu segmentation + morphology + watershed;
  attempts projection-based splitting if two neighbors are still merged.
- Falls back to edge-based detection if mask route finds nothing.
- Deskews each photo via perspective transform; trims white borders.
- Saves results under:
    OUTPUT_ROOT/<relative_dir>/<scan_stem>_split/photo_XX.jpg
  plus debug overlays/steps under _debug/.

Tune CLOSE_KERNEL/OPEN_KERNEL and MIN_AREA_RATIO if needed; use overlays to guide tuning.
"""

from pathlib import Path
from typing import List, Tuple, Dict, Optional
import numpy as np
import cv2
from PIL import Image

# ---------- CONFIG ----------
PATH_TO_PROCESS = r"C:\Users\stevi\Desktop\scan_split_test"           # <— change me
OUTPUT_ROOT     = r"C:\Users\stevi\Desktop\scan_split_test\output"    # <— change me (can be inside root)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic", ".heif")

# Detection tuning (good starting values for your sample)
MIN_AREA_RATIO = 0.03   # ignore blobs smaller than 3% of the page area
MAX_AREA_RATIO = 0.98   # ignore blobs larger than 98% (likely full page)
CLOSE_KERNEL   = (7, 7) # close small gaps around photo edges (reduce if neighbors merge)
OPEN_KERNEL    = (3, 3) # remove tiny noise (increase slightly if you see speckles)
KEEP_TOP_N     = 20     # cap number of candidate blobs for speed

# Save options
JPEG_QUALITY   = 95

# Debug & diagnostics
DEBUG_OVERLAY    = True   # save 01_overlay.jpg with numbered boxes
DEBUG_SAVE_STEPS = True   # save intermediate masks/labels
VERBOSE          = True   # print detector diagnostics
# ---------------------------

# Optional HEIC/HEIF support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass


# ===================== Helpers =====================
def load_image_any(path: Path) -> np.ndarray:
    """Load an image as BGR np.array. Uses Pillow (with pillow-heif) as fallback."""
    ext = path.suffix.lower()
    try:
        # Fast path for common formats
        if ext not in (".heic", ".heif"):
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is not None:
                return img
        # Pillow fallback (also covers HEIC/HEIF when pillow-heif is installed)
        im = Image.open(path).convert("RGB")
        return np.array(im)[:, :, ::-1]  # RGB -> BGR
    except Exception as e:
        raise RuntimeError(f"Failed to load {path}: {e}")


def order_box_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as TL, TR, BR, BL."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]    # tl
    rect[2] = pts[np.argmax(s)]    # br
    rect[1] = pts[np.argmin(d)]    # tr
    rect[3] = pts[np.argmax(d)]    # bl
    return rect


def warp_perspective_from_box(image: np.ndarray, box: np.ndarray) -> Optional[np.ndarray]:
    """Deskew/rectify region defined by a 4-pt box."""
    rect = order_box_points(box.astype("float32"))
    (tl, tr, br, bl) = rect
    wA = np.hypot(br[0]-bl[0], br[1]-bl[1])
    wB = np.hypot(tr[0]-tl[0], tr[1]-tl[1])
    hA = np.hypot(tr[0]-br[0], tr[1]-br[1])
    hB = np.hypot(tl[0]-bl[0], tl[1]-bl[1])
    maxW, maxH = int(max(wA, wB)), int(max(hA, hB))
    if maxW < 20 or maxH < 20:
        return None
    dst = np.array([[0,0],[maxW-1,0],[maxW-1,maxH-1],[0,maxH-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (maxW, maxH), flags=cv2.INTER_CUBIC)


def auto_crop_border(img_bgr: np.ndarray, pad: int = 10) -> np.ndarray:
    """Trim white-ish border from a deskewed photo."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3,3)), 1)
    coords = cv2.findNonZero(th)
    if coords is None:
        return img_bgr
    x, y, w, h = cv2.boundingRect(coords)
    x = max(0, x - pad); y = max(0, y - pad)
    w = min(img_bgr.shape[1] - x, w + 2*pad)
    h = min(img_bgr.shape[0] - y, h + 2*pad)
    return img_bgr[y:y+h, x:x+w]


def quad_to_mask(box: np.ndarray, shape: Tuple[int,int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [box.astype(np.int32)], 255)
    return mask


def iou_quads(a: np.ndarray, b: np.ndarray, img_shape: Tuple[int,int]) -> float:
    """IoU between two quads by rasterizing to fixed grid for scale invariance."""
    H, W = img_shape
    S = 2048
    sx, sy = S / W, S / H
    a2, b2 = a.copy(), b.copy()
    a2[:,0] *= sx; a2[:,1] *= sy
    b2[:,0] *= sx; b2[:,1] *= sy
    ma = quad_to_mask(a2, (S, S))
    mb = quad_to_mask(b2, (S, S))
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    return 0.0 if union == 0 else inter / union


def nms_quads(boxes: List[np.ndarray], iou_thresh: float = 0.25) -> List[np.ndarray]:
    if not boxes:
        return []
    areas = [cv2.contourArea(b.astype(np.int32)) for b in boxes]
    order = np.argsort(areas)[::-1]
    kept: List[int] = []
    for i in order:
        keep = True
        for j in kept:
            if iou_quads(boxes[i], boxes[j], (1000, 1000)) > iou_thresh:
                keep = False; break
        if keep:
            kept.append(i)
    return [boxes[i] for i in kept]


# ============ Detection (mask + watershed + projection split) ============
def detect_boxes_mask(page_bgr: np.ndarray, return_steps: bool = False) -> Tuple[List[np.ndarray], Dict[str, np.ndarray], Dict[str, float]]:
    """
    Segment 'non-white' (photos) via Otsu on LAB-L → open/close → watershed.
    If a blob still merges multiple photos, try a simple projection split.
    Returns (boxes, steps, diag).
    """
    H, W = page_bgr.shape[:2]
    area = H * W
    steps: Dict[str, np.ndarray] = {}
    diag: Dict[str, float] = {}

    lab = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2LAB)
    L = cv2.GaussianBlur(lab[:, :, 0], (5, 5), 0)
    _, mask = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_RECT, OPEN_KERNEL), 1)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, CLOSE_KERNEL), 1)

    # Diagnostics
    fg_ratio = float((closed > 0).sum()) / float(area)
    diag["fg_ratio_after_close"] = round(fg_ratio, 4)

    # Watershed to separate touchers
    dist = cv2.distanceTransform(closed, cv2.DIST_L2, 5)
    _, sure_fg = cv2.threshold(dist, 0.30 * dist.max(), 255, 0)
    sure_fg = np.uint8(sure_fg)
    sure_bg = cv2.dilate(closed, None, iterations=1)
    unknown = cv2.subtract(sure_bg, sure_fg)
    n, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0
    ws = cv2.watershed(cv2.cvtColor(page_bgr, cv2.COLOR_BGR2RGB), markers)

    boxes: List[np.ndarray] = []
    for label in np.unique(ws):
        if label <= 1:   # 0/1 are background/unknown/borders
            continue
        comp = np.uint8(ws == label) * 255
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        a = cv2.contourArea(c)
        if a < MIN_AREA_RATIO * area or a > MAX_AREA_RATIO * area:
            continue

        rect = cv2.minAreaRect(c)
        (w, h) = rect[1]
        if w < 20 or h < 20:
            continue

        rect_area = max(1.0, w * h)
        rectangularity = float(a) / rect_area

        if rectangularity < 0.60:
            boxes.extend(_split_component_by_projection(comp))
            continue

        boxes.append(cv2.boxPoints(rect).astype("float32"))

    boxes = nms_quads(boxes, iou_thresh=0.25)
    diag["boxes_mask"] = len(boxes)

    if return_steps:
        # Normalize dist for visualization
        dist_vis = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        steps.update({
            "L_channel": L,
            "mask_otsu_inv": mask,
            "mask_opened": opened,
            "mask_closed": closed,
            "dist": dist_vis,
        })
        # Colored label map for inspection
        lab_vis = np.zeros((H, W, 3), dtype=np.uint8)
        rng = np.random.default_rng(42)
        for label in np.unique(ws):
            if label <= 1:  # skip bg/unknown
                continue
            color = tuple(int(x) for x in rng.integers(80, 255, size=3))
            lab_vis[ws == label] = color
        steps["watershed_labels"] = lab_vis

    return boxes, steps, diag


def _split_component_by_projection(comp_mask: np.ndarray) -> List[np.ndarray]:
    """
    Split a merged blob along the strongest internal white valley (vertical or horizontal).
    Returns list of minAreaRect boxes in original comp coords.
    """
    boxes: List[np.ndarray] = []

    # Vertical split attempt
    col_sum = (255 - comp_mask).sum(axis=0)  # white seam -> larger value
    v_idx = int(np.argmin(col_sum))
    if col_sum.max() > 0 and col_sum[v_idx] < 0.20 * col_sum.max():
        left = comp_mask[:, :v_idx]
        right = comp_mask[:, v_idx:]
        for m, xshift in ((left, 0), (right, v_idx)):
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) < 5000:
                continue
            rect = cv2.minAreaRect(c)
            box = cv2.boxPoints(rect).astype("float32")
            box[:, 0] += xshift
            boxes.append(box)

    # Horizontal split attempt (if still one piece)
    if len(boxes) <= 1:
        row_sum = (255 - comp_mask).sum(axis=1)
        h_idx = int(np.argmin(row_sum))
        if row_sum.max() > 0 and row_sum[h_idx] < 0.20 * row_sum.max():
            top = comp_mask[:h_idx, :]
            bot = comp_mask[h_idx:, :]
            for m, yshift in ((top, 0), (bot, h_idx)):
                cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not cnts:
                    continue
                c = max(cnts, key=cv2.contourArea)
                if cv2.contourArea(c) < 5000:
                    continue
                rect = cv2.minAreaRect(c)
                box = cv2.boxPoints(rect).astype("float32")
                box[:, 1] += yshift
                boxes.append(box)

    return boxes


# ===================== Edge fallback =====================
def detect_boxes_edges(page_bgr: np.ndarray, return_steps: bool = False):
    """
    Fallback detector: Canny edges -> close -> contours -> minAreaRect.
    Less robust to lighting, but helpful if mask path fails.
    """
    H, W = page_bgr.shape[:2]
    area = H * W
    steps: Dict[str, np.ndarray] = {}
    diag: Dict[str, float] = {}

    gray = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)), 1)
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: List[np.ndarray] = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < MIN_AREA_RATIO * area or a > MAX_AREA_RATIO * area:
            continue
        rect = cv2.minAreaRect(c)
        w, h = rect[1]
        if w < 20 or h < 20:
            continue
        ar = max(w, h) / max(1.0, min(w, h))
        if ar > 4.5:
            continue
        boxes.append(cv2.boxPoints(rect).astype("float32"))

    boxes = nms_quads(boxes, iou_thresh=0.25)
    diag["boxes_edges"] = len(boxes)

    if return_steps:
        steps.update({"gray": gray, "edges": edges, "edges_closed": closed})
    return boxes, steps, diag


# ===================== Pipeline =====================
def try_all_orientations(page_bgr: np.ndarray, return_steps: bool = False):
    """
    Try 0/90/180/270 with mask detector; if none found, try edge fallback.
    Returns: oriented_img, boxes, angle, steps(dict), diag(dict)
    """
    rotations = [
        (page_bgr, 0),
        (cv2.rotate(page_bgr, cv2.ROTATE_90_CLOCKWISE), 90),
        (cv2.rotate(page_bgr, cv2.ROTATE_180), 180),
        (cv2.rotate(page_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE), 270),
    ]
    best = ([], None, page_bgr, 0, {}, {})
    # Primary: mask-based
    for img, angle in rotations:
        boxes, steps, info = detect_boxes_mask(img, return_steps=return_steps)
        if VERBOSE:
            print(f"[diag] angle {angle}: mask boxes={info.get('boxes_mask',0)}, fg_ratio={info.get('fg_ratio_after_close')}")
        if len(boxes) > len(best[0]):
            best = (boxes, steps, img, angle, steps, info)

    # Fallback: edges if nothing found
    if len(best[0]) == 0:
        for img, angle in rotations:
            boxes, steps, info2 = detect_boxes_edges(img, return_steps=return_steps)
            if VERBOSE:
                print(f"[diag] angle {angle}: EDGE boxes={info2.get('boxes_edges',0)}")
            if len(boxes) > len(best[0]):
                best = (boxes, steps, img, angle, steps, info2)

    return best[2], best[0], best[3], best[4], best[5]


def extract_photos_from_scan(page_bgr: np.ndarray, want_debug: bool = False):
    oriented, boxes, angle, steps, diag = try_all_orientations(page_bgr, return_steps=want_debug)

    # Stable save order: row-major by centroid
    order = []
    if boxes:
        centers = [(float(np.mean(b[:,1])), float(np.mean(b[:,0]))) for b in boxes]  # (y, x)
        order = list(np.argsort([y*1e5 + x for (y, x) in centers]))

    photos: List[np.ndarray] = []
    for idx in (order if order else range(len(boxes))):
        warped = warp_perspective_from_box(oriented, boxes[idx])
        if warped is None:
            continue
        photos.append(auto_crop_border(warped, pad=10))

    debug = {}
    if want_debug:
        debug = {"oriented": oriented, "boxes": boxes, "order": order, "angle": angle, "steps": steps, "diag": diag}
    return photos, debug


def draw_debug_overlay(img_bgr: np.ndarray, boxes: List[np.ndarray], order: List[int], angle: int) -> np.ndarray:
    overlay = img_bgr.copy()
    H, W = overlay.shape[:2]
    th = max(2, int(0.003 * max(H, W)))
    fs = max(0.6, 0.0012 * max(H, W))
    font = cv2.FONT_HERSHEY_SIMPLEX
    if not order:
        order = list(range(len(boxes)))
    index_map = {idx: i+1 for i, idx in enumerate(order)}

    for i, box in enumerate(boxes):
        pts = box.reshape(-1,1,2).astype(np.int32)
        cv2.polylines(overlay, [pts], True, (0,255,255), th)
        tl = order_box_points(box)[0].astype(int)
        label = str(index_map.get(i, i+1))
        cv2.putText(overlay, label, (int(tl[0])+5, int(tl[1])+25), font, fs, (0,0,0), th+2, cv2.LINE_AA)
        cv2.putText(overlay, label, (int(tl[0])+5, int(tl[1])+25), font, fs, (0,255,0), th,   cv2.LINE_AA)

    header = f"Detected: {len(boxes)} | Angle: {angle}°"
    cv2.putText(overlay, header, (10, 30), font, fs, (0,0,0), th+2, cv2.LINE_AA)
    cv2.putText(overlay, header, (10, 30), font, fs, (255,255,255), th,   cv2.LINE_AA)
    return overlay


def save_jpg(path: Path, img_bgr: np.ndarray, quality: int = JPEG_QUALITY):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])


def process_one_file(in_path: Path, out_root: Path, root_dir: Path):
    try:
        page = load_image_any(in_path)
    except Exception as e:
        print(f"[SKIP] {in_path}: {e}")
        return

    want_debug = DEBUG_OVERLAY or DEBUG_SAVE_STEPS
    photos, dbg = extract_photos_from_scan(page, want_debug=want_debug)

    rel_dir   = in_path.parent.relative_to(root_dir)
    split_dir = out_root / rel_dir / (in_path.stem + "_split")
    debug_dir = split_dir / "_debug"

    if not photos:
        print(f"[WARN] No photos detected in {in_path}")
        if want_debug and "oriented" in dbg:
            save_jpg(debug_dir / "00_page_oriented.jpg", dbg["oriented"])
            if DEBUG_OVERLAY:
                # Overlay even when no boxes (will just show header)
                save_jpg(debug_dir / "01_overlay.jpg", dbg["oriented"])
            if DEBUG_SAVE_STEPS:
                for name, im in dbg.get("steps", {}).items():
                    im3 = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) if im.ndim == 2 else im
                    save_jpg(debug_dir / f"step_{name}.jpg", im3)
        return

    # Save crops
    for i, p in enumerate(photos, 1):
        save_jpg(split_dir / f"photo_{i:02d}.jpg", p)

    # Debug
    if want_debug:
        save_jpg(debug_dir / "00_page_oriented.jpg", dbg["oriented"])
        if DEBUG_OVERLAY:
            overlay = draw_debug_overlay(dbg["oriented"], dbg["boxes"], dbg["order"], dbg["angle"])
            save_jpg(debug_dir / "01_overlay.jpg", overlay)
        if DEBUG_SAVE_STEPS:
            for name, im in dbg.get("steps", {}).items():
                im3 = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) if im.ndim == 2 else im
                save_jpg(debug_dir / f"step_{name}.jpg", im3)

    print(f"[OK] {in_path} -> {len(photos)} photo(s)")


def walk_and_process(root_dir: Path, out_root: Path):
    """Walk root_dir, skipping anything inside out_root, and process images."""
    out_root = out_root.resolve()
    count = 0
    for p in root_dir.rglob("*"):
        if not p.is_file():
            continue
        # Skip anything inside output root to avoid reprocessing debug/crops
        try:
            if Path(p).resolve().is_relative_to(out_root):
                continue
        except AttributeError:
            # Python < 3.9 fallback (you’re on 3.12, so this won’t run)
            if str(Path(p).resolve()).startswith(str(out_root)):
                continue
        if p.suffix.lower() in IMAGE_EXTENSIONS:
            process_one_file(p, out_root, root_dir)
            count += 1
    if count == 0:
        print(f"[INFO] No images found under {root_dir}")


# ===================== Run =====================
if __name__ == "__main__":
    ROOT = Path(PATH_TO_PROCESS).expanduser().resolve()
    OUT  = Path(OUTPUT_ROOT if OUTPUT_ROOT else ROOT / "_extracted").expanduser().resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"Root:   {ROOT}")
    print(f"Output: {OUT}")
    walk_and_process(ROOT, OUT)
    print("Done.")
