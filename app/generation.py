from __future__ import annotations

import random
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from .config import (
    CLEANUP_OPTIONS,
    DEFAULT_BACKEND,
    DEFAULT_CLEANUP,
    DEFAULT_QUALITY,
    DETAIL_TARGET_OPTIONS,
    DETAIL_VIEW_OPTION,
    DESKTOP_DIR,
    MAX_SAMPLE_COUNT,
    MAX_DETAIL_REFERENCES,
    MAX_PRIMARY_REFERENCES,
    MAX_TRIANGLE_BUDGET,
    MIN_SAMPLE_COUNT,
    MIN_TRIANGLE_BUDGET,
    PREVIEW_CACHE_DIR,
    PREVIEW_CACHE_KEEP_LATEST,
    PREVIEW_CACHE_MAX_AGE_DAYS,
    QUALITY_PRESETS,
    QualityPreset,
    SHEET_CACHE_DIR,
    SHEET_CACHE_KEEP_LATEST,
    SHEET_CACHE_MAX_AGE_DAYS,
    SOURCE_MAX_SIDE,
    SOURCE_MIN_SIDE,
    VIEW_HINTS,
    VIEW_ORDER,
)
from .runtime import RUNTIME, ensure_runtime, get_bg_remover, get_cleanup_workers, get_pipeline


@dataclass
class SelectedImage:
    path: Path
    view_value: str = "Auto"
    detail_target: str = "Auto"


@dataclass(frozen=True)
class DetailReference:
    image: Image.Image
    target: str = "Auto"
    source_name: str = ""


@dataclass(frozen=True)
class OrthoSheetSplitResult:
    source_path: Path
    output_dir: Path
    images: tuple[SelectedImage, ...]
    note: str


@dataclass
class GenerationOptions:
    output_name: str
    backend_name: str = DEFAULT_BACKEND
    quality_name: str = DEFAULT_QUALITY
    cleanup_mode: str = DEFAULT_CLEANUP
    remove_background: bool = True
    keep_raw_copy: bool = False
    max_triangles: int | None = None
    sample_count: int = 1
    memory_guard: bool = True
    soft_ram_limit_percent: int = 82
    soft_vram_limit_percent: int = 84
    subject_type: str = "Auto"
    subject_name: str = ""
    subject_notes: str = ""


@dataclass
class GenerationResult:
    output_path: Path
    raw_output_path: Path | None
    preview_image_path: Path | None
    used_input_summary: str
    quality_name: str
    cleanup_mode: str
    target_triangles: int | None
    seed: int
    samples_ran: int
    face_count: int
    vertex_count: int
    selected_sample_index: int
    sample_review_note: str
    runtime_profile_note: str
    subject_profile_note: str
    note: str


@dataclass(frozen=True)
class SubjectProfile:
    label: str
    is_vehicle: bool = False
    is_hard_surface: bool = False
    is_transparent: bool = False
    is_organic: bool = False
    prefers_multiview: bool = False
    preserve_edges: bool = False
    has_extremity_detail: bool = False
    has_cloth_detail: bool = False
    has_fragile_detail: bool = False


@dataclass(frozen=True)
class ReferenceGeometryHints:
    width_to_height: float | None = None
    depth_to_height: float | None = None
    generic_width_to_height: float | None = None
    confidence: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class GeometryGuardReference:
    labeled_masks: tuple[tuple[str, np.ndarray], ...] = ()
    generic_masks: tuple[np.ndarray, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class GeometryGuardResult:
    score_adjustment: float = 0.0
    avg_iou: float = 0.0
    matched_views: int = 0
    best_vertical_axis: int | None = None
    best_yaw_deg: int | None = None
    symmetry_error: float | None = None
    needs_retry: bool = False
    note: str = "geometry guard unavailable"


def build_subject_profile(subject_type: str, subject_name: str, subject_notes: str) -> SubjectProfile:
    explicit = (subject_type or "Auto").strip().lower()
    text = " ".join(part for part in (subject_type, subject_name, subject_notes) if part).lower()

    vehicle_words = (
        "car", "vehicle", "truck", "van", "suv", "sedan", "coupe", "wagon",
        "porsche", "bmw", "audi", "mercedes", "ford", "wheel", "rim",
    )
    transparent_words = ("glass", "transparent", "translucent", "window", "bottle", "cup", "clear")
    organic_words = ("dog", "cat", "animal", "creature", "character", "head", "face", "human", "person")
    hard_surface_words = (
        "hard surface", "helmet", "machine", "robot", "vehicle", "car", "product",
        "prop", "weapon", "cup", "bottle", "container",
    )
    portrait_words = ("head", "face", "bust", "portrait", "closeup", "close-up")
    extremity_words = (
        "hand", "hands", "finger", "fingers", "glove", "gloves", "arm", "arms",
        "foot", "feet", "toe", "toes", "paw", "paws", "claw", "claws",
    )
    cloth_words = (
        "cape", "cloak", "cloth", "fabric", "robe", "dress", "skirt", "coat",
        "jacket", "sleeve", "ribbon", "strap", "banner", "scarf",
        "tear", "tears", "torn", "ragged", "tattered",
    )
    thin_detail_words = cloth_words + (
        "feather", "feathers", "fur", "hair", "wing", "wings",
        "horn", "horns", "spike", "spikes", "chain", "chains",
    )

    is_vehicle = explicit == "vehicle" or any(word in text for word in vehicle_words)
    is_transparent = explicit == "glass / transparent" or (
        (not is_vehicle) and any(word in text for word in transparent_words)
    )
    is_organic = explicit == "creature / character" or any(word in text for word in organic_words)
    is_hard_surface = explicit in {"hard surface object", "product / prop", "vehicle", "glass / transparent"} or any(
        word in text for word in hard_surface_words
    )

    if is_vehicle:
        label = "Vehicle / car-like hard surface"
    elif is_transparent:
        label = "Glass / transparent object"
    elif is_organic:
        label = "Organic / creature-like subject"
    elif is_hard_surface:
        label = "Hard surface object"
    else:
        label = subject_type.strip() if subject_type.strip() and subject_type.strip().lower() != "auto" else "General object"

    portrait_like = any(word in text for word in portrait_words)
    has_extremity_detail = any(word in text for word in extremity_words) or (is_organic and not portrait_like)
    has_cloth_detail = any(word in text for word in cloth_words)
    has_fragile_detail = has_extremity_detail or has_cloth_detail or any(word in text for word in thin_detail_words)

    return SubjectProfile(
        label=label,
        is_vehicle=is_vehicle,
        is_hard_surface=is_hard_surface,
        is_transparent=is_transparent,
        is_organic=is_organic,
        prefers_multiview=is_vehicle or is_hard_surface or is_transparent,
        preserve_edges=is_vehicle or is_hard_surface,
        has_extremity_detail=has_extremity_detail,
        has_cloth_detail=has_cloth_detail,
        has_fragile_detail=has_fragile_detail,
    )


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "3dvisual_mesh"


def guess_view_from_name(path: Path) -> str | None:
    stem = path.stem.lower()
    for view, hints in VIEW_HINTS.items():
        if any(hint in stem for hint in hints):
            return view
    return None


def is_detail_view_value(value: str | None) -> bool:
    lowered = (value or "").strip().lower()
    return lowered in {
        DETAIL_VIEW_OPTION.lower(),
        "detail",
        "detail crop",
        "closeup",
        "close-up",
    }


def normalize_detail_target(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Auto"
    lowered = raw.lower()
    alias_map = {
        "helmet": "Head / Helmet",
        "head": "Head / Helmet",
        "face": "Face",
        "torso": "Torso / Chest",
        "chest": "Torso / Chest",
        "body": "Torso / Chest",
        "shoulder": "Shoulder",
        "arm": "Arm",
        "arms": "Arm",
        "hand": "Hand",
        "hands": "Hand",
        "finger": "Hand",
        "fingers": "Hand",
        "waist": "Waist / Belt",
        "belt": "Waist / Belt",
        "hip": "Waist / Belt",
        "leg": "Leg",
        "legs": "Leg",
        "foot": "Foot / Shoe",
        "feet": "Foot / Shoe",
        "shoe": "Foot / Shoe",
        "shoes": "Foot / Shoe",
        "boot": "Foot / Shoe",
        "boots": "Foot / Shoe",
        "cape": "Cape / Cloth",
        "cloth": "Cape / Cloth",
        "cloak": "Cape / Cloth",
        "fabric": "Cape / Cloth",
        "robe": "Cape / Cloth",
        "back": "Back Detail",
        "weapon": "Weapon / Accessory",
        "sword": "Weapon / Accessory",
        "shield": "Weapon / Accessory",
        "accessory": "Weapon / Accessory",
        "other": "Other",
    }
    if lowered in alias_map:
        return alias_map[lowered]
    for option in DETAIL_TARGET_OPTIONS:
        if lowered == option.lower():
            return option
    return "Auto"


def detail_target_terms(value: str | None) -> tuple[str, ...]:
    normalized = normalize_detail_target(value)
    term_map = {
        "Head / Helmet": ("head", "helmet"),
        "Face": ("face",),
        "Torso / Chest": ("torso", "chest"),
        "Shoulder": ("shoulder",),
        "Arm": ("arm",),
        "Hand": ("hand", "finger"),
        "Waist / Belt": ("waist", "belt"),
        "Leg": ("leg",),
        "Foot / Shoe": ("foot", "shoe", "boot"),
        "Cape / Cloth": ("cape", "cloth", "fabric", "cloak"),
        "Back Detail": ("back",),
        "Weapon / Accessory": ("weapon", "accessory"),
        "Other": ("detail",),
    }
    return term_map.get(normalized, ())


def guess_detail_target_from_name(path: Path) -> str | None:
    stem = path.stem.lower()
    target_hints = (
        ("Hand", ("hand", "hands", "finger", "fingers", "glove", "palm")),
        ("Foot / Shoe", ("foot", "feet", "shoe", "shoes", "boot", "boots", "sole")),
        ("Cape / Cloth", ("cape", "cloth", "fabric", "cloak", "robe", "sleeve", "scarf", "tear", "torn")),
        ("Head / Helmet", ("head", "helmet", "helm", "hood")),
        ("Face", ("face", "eyes", "eye", "mouth", "nose")),
        ("Torso / Chest", ("torso", "chest", "body", "armor", "breastplate")),
        ("Shoulder", ("shoulder", "pauldron")),
        ("Arm", ("arm", "arms", "elbow", "forearm")),
        ("Waist / Belt", ("waist", "belt", "hip")),
        ("Leg", ("leg", "legs", "thigh", "knee", "shin")),
        ("Back Detail", ("back", "rear")),
        ("Weapon / Accessory", ("weapon", "sword", "shield", "bag", "pack", "accessory")),
    )
    for target, hints in target_hints:
        if any(hint in stem for hint in hints):
            return target
    return None


def guess_detail_crop_from_name(path: Path) -> bool:
    stem = path.stem.lower()
    detail_hints = (
        "detail",
        "closeup",
        "close-up",
        "crop",
        "hand",
        "hands",
        "finger",
        "fingers",
        "cloth",
        "cape",
        "cloak",
        "fabric",
        "shoe",
        "foot",
        "feet",
    )
    return any(hint in stem for hint in detail_hints)


def split_reference_images(selected_images: Iterable[SelectedImage]) -> tuple[list[SelectedImage], list[SelectedImage]]:
    primary_items: list[SelectedImage] = []
    detail_items: list[SelectedImage] = []
    for item in selected_images:
        value = (item.view_value or "Auto").strip()
        if not value or value.lower() == "ignore":
            continue
        if is_detail_view_value(value):
            detail_items.append(item)
        else:
            primary_items.append(item)
    return primary_items, detail_items


def build_detail_focus_terms(selected_images: Iterable[SelectedImage]) -> tuple[str, ...]:
    terms: list[str] = []
    for item in selected_images:
        if not is_detail_view_value(item.view_value):
            continue
        for term in detail_target_terms(item.detail_target):
            if term not in terms:
                terms.append(term)
    return tuple(terms)


def _iter_sorted_by_mtime(paths: Iterable[Path]) -> list[Path]:
    return sorted(
        (path for path in paths if path.exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _prune_cache_files(cache_dir: Path, *, keep_latest: int, max_age_days: int):
    if not cache_dir.exists():
        return

    now = time.time()
    max_age_seconds = max(1, int(max_age_days)) * 86400
    files = _iter_sorted_by_mtime(path for path in cache_dir.rglob("*") if path.is_file())
    keep_set = set(files[: max(0, int(keep_latest))])

    for path in files:
        try:
            too_old = (now - path.stat().st_mtime) > max_age_seconds
        except OSError:
            too_old = True
        if path in keep_set and not too_old:
            continue
        try:
            path.unlink()
        except OSError:
            continue


def _prune_cache_dirs(cache_dir: Path, *, keep_latest: int, max_age_days: int):
    if not cache_dir.exists():
        return

    now = time.time()
    max_age_seconds = max(1, int(max_age_days)) * 86400
    directories = _iter_sorted_by_mtime(path for path in cache_dir.iterdir() if path.is_dir())
    keep_set = set(directories[: max(0, int(keep_latest))])

    for path in directories:
        try:
            too_old = (now - path.stat().st_mtime) > max_age_seconds
        except OSError:
            too_old = True
        if path in keep_set and not too_old:
            continue
        try:
            shutil.rmtree(path)
        except OSError:
            continue


def cleanup_generated_caches():
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SHEET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _prune_cache_files(
        PREVIEW_CACHE_DIR,
        keep_latest=PREVIEW_CACHE_KEEP_LATEST,
        max_age_days=PREVIEW_CACHE_MAX_AGE_DAYS,
    )
    _prune_cache_dirs(
        SHEET_CACHE_DIR,
        keep_latest=SHEET_CACHE_KEEP_LATEST,
        max_age_days=SHEET_CACHE_MAX_AGE_DAYS,
    )


def _largest_component_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    if mask.ndim != 2 or not mask.any():
        return None

    height, width = mask.shape
    visited = np.zeros((height, width), dtype=bool)
    best_count = 0
    best_bbox: tuple[int, int, int, int] | None = None

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            stack = [(y, x)]
            visited[y, x] = True
            count = 0
            min_x = max_x = x
            min_y = max_y = y

            while stack:
                cy, cx = stack.pop()
                count += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy

                y0 = max(0, cy - 1)
                y1 = min(height, cy + 2)
                x0 = max(0, cx - 1)
                x1 = min(width, cx + 2)
                for ny in range(y0, y1):
                    for nx in range(x0, x1):
                        if visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        stack.append((ny, nx))

            if count > best_count:
                best_count = count
                best_bbox = (min_x, min_y, max_x + 1, max_y + 1)

    return best_bbox


def _component_bboxes(mask: np.ndarray) -> list[tuple[int, tuple[int, int, int, int]]]:
    if mask.ndim != 2 or not mask.any():
        return []

    height, width = mask.shape
    visited = np.zeros((height, width), dtype=bool)
    components: list[tuple[int, tuple[int, int, int, int]]] = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            stack = [(y, x)]
            visited[y, x] = True
            count = 0
            min_x = max_x = x
            min_y = max_y = y

            while stack:
                cy, cx = stack.pop()
                count += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy

                y0 = max(0, cy - 1)
                y1 = min(height, cy + 2)
                x0 = max(0, cx - 1)
                x1 = min(width, cx + 2)
                for ny in range(y0, y1):
                    for nx in range(x0, x1):
                        if visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        stack.append((ny, nx))

            components.append((count, (min_x, min_y, max_x + 1, max_y + 1)))

    return components


def _detect_sheet_subject_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    gray = image.convert("L")
    width, height = gray.size
    if width <= 0 or height <= 0:
        return None

    small_side = 196
    scale = min(1.0, small_side / max(width, height))
    small_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    small = gray.resize(small_size, Image.Resampling.BILINEAR)

    binary = small.point(lambda value: 255 if value < 236 else 0, mode="L")
    binary = binary.filter(ImageFilter.MaxFilter(5))
    binary = binary.filter(ImageFilter.MaxFilter(5))

    mask = np.asarray(binary) > 0
    bbox = _largest_component_bbox(mask)
    if bbox is None:
        return None

    sx0, sy0, sx1, sy1 = bbox
    inv_scale_x = width / max(1, small_size[0])
    inv_scale_y = height / max(1, small_size[1])

    padding_x = max(8, int(width * 0.03))
    padding_y = max(8, int(height * 0.03))

    x0 = max(0, int(np.floor(sx0 * inv_scale_x)) - padding_x)
    y0 = max(0, int(np.floor(sy0 * inv_scale_y)) - padding_y)
    x1 = min(width, int(np.ceil(sx1 * inv_scale_x)) + padding_x)
    y1 = min(height, int(np.ceil(sy1 * inv_scale_y)) + padding_y)
    return x0, y0, x1, y1


def _trim_bottom_label_band(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    width, height = gray.size
    row_dark = np.sum(np.asarray(gray) < 236, axis=1)
    if row_dark.size == 0:
        return image

    low_threshold = max(4, int(width * 0.01))
    gap_run = 0
    gap_top = None
    bottom_limit = int(height * 0.55)

    for row in range(height - 1, bottom_limit - 1, -1):
        if row_dark[row] <= low_threshold:
            gap_run += 1
            if gap_run >= 10:
                gap_top = row
        else:
            if gap_run >= 10 and gap_top is not None:
                break
            gap_run = 0
            gap_top = None

    if gap_top is None:
        working = image.convert("RGBA")
    else:
        footer_start = min(height, gap_top + 10)
        if footer_start >= int(height * 0.84):
            working = image.crop((0, 0, width, footer_start)).convert("RGBA")
        else:
            working = image.convert("RGBA")

    work_gray = working.convert("L")
    work_width, work_height = work_gray.size
    region_top = int(work_height * 0.72)
    region = np.asarray(work_gray.crop((0, region_top, work_width, work_height))) < 220
    components = _component_bboxes(region)

    if not components:
        return working

    cleaned = working.copy()
    draw = ImageDraw.Draw(cleaned)
    for count, (x0, y0, x1, y1) in components:
        component_h = y1 - y0
        component_w = x1 - x0
        absolute_top = region_top + y0
        if count < 32:
            continue
        if absolute_top < int(work_height * 0.78):
            continue
        if component_h > int(work_height * 0.12):
            continue
        if component_w > int(work_width * 0.68):
            continue

        pad_x = max(4, int(component_w * 0.16))
        pad_y = max(4, int(component_h * 0.25))
        draw.rectangle(
            (
                max(0, x0 - pad_x),
                max(0, region_top + y0 - pad_y),
                min(work_width, x1 + pad_x),
                min(work_height, region_top + y1 + pad_y),
            ),
            fill=(255, 255, 255, 255),
        )

    return cleaned


def _prepare_sheet_cell(image: Image.Image) -> Image.Image:
    image = trim_uniform_borders(image, tolerance=12, padding=6)
    image = _trim_bottom_label_band(image)
    bbox = _detect_sheet_subject_bbox(image)
    if bbox:
        image = image.crop(bbox)
    return image.convert("RGBA")


def _build_sheet_canvas(images_by_view: dict[str, Image.Image]) -> dict[str, Image.Image]:
    widths = [image.size[0] for image in images_by_view.values()]
    heights = [image.size[1] for image in images_by_view.values()]
    if not widths or not heights:
        return images_by_view

    base_width = max(widths)
    base_height = max(heights)
    side = max(
        768,
        base_width + max(60, int(base_width * 0.18)),
        base_height + max(90, int(base_height * 0.24)),
    )
    baseline = side - max(48, int(side * 0.10))

    output: dict[str, Image.Image] = {}
    for view, image in images_by_view.items():
        canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
        x = (side - image.size[0]) // 2
        y = baseline - image.size[1]
        y = max(24, y)
        canvas.alpha_composite(image, (x, y))
        output[view] = canvas
    return output


def split_ortho_reference_sheet(source_path: Path) -> OrthoSheetSplitResult:
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Sheet image not found: {source_path}")
    cleanup_generated_caches()

    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")

    width, height = image.size
    if width < 320 or height < 320:
        raise ValueError("The sheet image is too small for 2x2 split mode.")

    half_w = width // 2
    half_h = height // 2
    cells = {
        "Left": image.crop((0, 0, half_w, half_h)),
        "Right": image.crop((half_w, 0, width, half_h)),
        "Front": image.crop((0, half_h, half_w, height)),
        "Back": image.crop((half_w, half_h, width, height)),
    }

    prepared: dict[str, Image.Image] = {}
    for view, cell in cells.items():
        prepared[view] = _prepare_sheet_cell(cell)

    aligned = _build_sheet_canvas(prepared)

    safe_stem = sanitize_name(source_path.stem)
    output_dir = SHEET_CACHE_DIR / f"{safe_stem}_sheet"
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_images: list[SelectedImage] = []
    for view in ("Front", "Left", "Back", "Right"):
        output_path = output_dir / f"{safe_stem}_{view.lower()}.png"
        aligned[view].save(output_path)
        selected_images.append(SelectedImage(path=output_path, view_value=view))

    note = (
        "Split 2x2 ortho sheet into Front, Left, Back, Right. "
        "Text labels were trimmed and each view was centered on a shared square canvas."
    )
    return OrthoSheetSplitResult(
        source_path=source_path,
        output_dir=output_dir,
        images=tuple(selected_images),
        note=note,
    )


def trim_uniform_borders(image: Image.Image, tolerance: int = 18, padding: int = 8) -> Image.Image:
    rgb = image.convert("RGB")
    arr = np.asarray(rgb)
    h, w = arr.shape[:2]
    patch_h = max(4, min(24, h // 20))
    patch_w = max(4, min(24, w // 20))

    corners = np.concatenate(
        [
            arr[:patch_h, :patch_w].reshape(-1, 3),
            arr[:patch_h, -patch_w:].reshape(-1, 3),
            arr[-patch_h:, :patch_w].reshape(-1, 3),
            arr[-patch_h:, -patch_w:].reshape(-1, 3),
        ],
        axis=0,
    )
    border_color = np.median(corners, axis=0)
    diff = np.abs(arr.astype(np.int16) - border_color.astype(np.int16)).max(axis=2)
    mask = diff > tolerance

    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or len(ys) == 0:
        return image

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()

    crop_w = x1 - x0 + 1
    crop_h = y1 - y0 + 1

    if crop_w > w * 0.97 and crop_h > h * 0.97:
        return image

    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(w, x1 + padding + 1)
    y1 = min(h, y1 + padding + 1)
    return image.crop((x0, y0, x1, y1))


def alpha_bbox(image: Image.Image, threshold: int = 8) -> tuple[int, int, int, int] | None:
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.nonzero(alpha > threshold)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def alpha_coverage(image: Image.Image, threshold: int = 8) -> float:
    alpha = np.asarray(image.getchannel("A"))
    if alpha.size == 0:
        return 0.0
    return float((alpha > threshold).mean())


def content_bbox(image: Image.Image, threshold: int = 8) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    coverage = alpha_coverage(rgba, threshold=threshold)
    if 0.01 <= coverage <= 0.985:
        bbox = alpha_bbox(rgba, threshold=threshold)
        if bbox is not None:
            return bbox

    rgb = rgba.convert("RGB")
    arr = np.asarray(rgb)
    h, w = arr.shape[:2]
    if h <= 0 or w <= 0:
        return None

    patch_h = max(4, min(24, h // 20))
    patch_w = max(4, min(24, w // 20))
    corners = np.concatenate(
        [
            arr[:patch_h, :patch_w].reshape(-1, 3),
            arr[:patch_h, -patch_w:].reshape(-1, 3),
            arr[-patch_h:, :patch_w].reshape(-1, 3),
            arr[-patch_h:, -patch_w:].reshape(-1, 3),
        ],
        axis=0,
    )
    border_color = np.median(corners, axis=0)
    diff = np.abs(arr.astype(np.int16) - border_color.astype(np.int16)).max(axis=2)
    ys, xs = np.nonzero(diff > 12)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _subject_fill_ratio(image: Image.Image) -> float | None:
    bbox = content_bbox(image)
    if not bbox:
        return None
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    canvas_side = max(image.size)
    if canvas_side <= 0:
        return None
    return max(width, height) / canvas_side


def _rescale_subject_to_fill(image: Image.Image, target_fill: float) -> Image.Image:
    bbox = content_bbox(image)
    if not bbox:
        return image

    image = image.convert("RGBA")
    subject = image.crop(bbox)
    current_fill = _subject_fill_ratio(image)
    if not current_fill or current_fill <= 0:
        return image

    scale = target_fill / current_fill
    if abs(scale - 1.0) < 0.04:
        return image

    new_size = (
        max(1, int(round(subject.size[0] * scale))),
        max(1, int(round(subject.size[1] * scale))),
    )
    resized = subject.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    offset = (
        (image.size[0] - new_size[0]) // 2,
        (image.size[1] - new_size[1]) // 2,
    )
    canvas.alpha_composite(resized, offset)
    return canvas


def harmonize_multiview_subject_scale(images_by_view: dict[str, Image.Image]) -> dict[str, Image.Image]:
    if len(images_by_view) < 2:
        return images_by_view

    fills = [ratio for ratio in (_subject_fill_ratio(image) for image in images_by_view.values()) if ratio is not None]
    if len(fills) < 2:
        return images_by_view

    target_fill = float(np.median(np.asarray(fills, dtype=float)))
    target_fill = max(0.58, min(0.84, target_fill))

    output: dict[str, Image.Image] = {}
    for view, image in images_by_view.items():
        output[view] = _rescale_subject_to_fill(image, target_fill)
    return output


def _bbox_ratio(image: Image.Image | None) -> float | None:
    if image is None:
        return None
    bbox = content_bbox(image)
    if not bbox:
        return None
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    return width / max(height, 1)


def build_reference_geometry_hints(image_input, profile: SubjectProfile) -> ReferenceGeometryHints:
    if isinstance(image_input, dict):
        front_ratios = [
            ratio for ratio in (_bbox_ratio(image_input.get(view)) for view in ("front", "back")) if ratio is not None
        ]
        side_ratios = [
            ratio for ratio in (_bbox_ratio(image_input.get(view)) for view in ("left", "right")) if ratio is not None
        ]
        generic_ratios = [ratio for ratio in (_bbox_ratio(image) for image in image_input.values()) if ratio is not None]

        width_to_height = float(np.mean(front_ratios)) if front_ratios else None
        depth_to_height = float(np.mean(side_ratios)) if side_ratios else None
        generic_width_to_height = float(np.mean(generic_ratios)) if generic_ratios else None

        confidence = 0.0
        if width_to_height is not None:
            confidence += 0.36
        if depth_to_height is not None:
            confidence += 0.36
        if width_to_height is not None and depth_to_height is not None:
            confidence += 0.18
        if len(generic_ratios) >= 3:
            confidence += 0.08
        confidence = min(1.0, confidence)

        parts: list[str] = []
        if width_to_height is not None:
            parts.append(f"front width/height {width_to_height:.2f}")
        if depth_to_height is not None:
            parts.append(f"side depth/height {depth_to_height:.2f}")
        note = "Reference proportions: " + " | ".join(parts) if parts else "Reference proportions: not enough labeled data"

        return ReferenceGeometryHints(
            width_to_height=width_to_height,
            depth_to_height=depth_to_height,
            generic_width_to_height=generic_width_to_height,
            confidence=confidence,
            note=note,
        )

    generic_ratio = _bbox_ratio(image_input) if image_input is not None else None
    note = (
        f"Single-view silhouette ratio {generic_ratio:.2f}"
        if generic_ratio is not None
        else "Single-view silhouette ratio unavailable"
    )
    return ReferenceGeometryHints(
        generic_width_to_height=generic_ratio,
        confidence=0.12 if generic_ratio is not None else 0.0,
        note=note,
    )


def _image_to_guard_mask(image: Image.Image, size: int = 192) -> np.ndarray | None:
    rgba = image.convert("RGBA")
    bbox = content_bbox(rgba)
    if bbox is not None:
        rgba = rgba.crop(bbox)

    alpha = np.asarray(rgba.getchannel("A"))
    alpha_mask = alpha > 12
    alpha_fill = float(alpha_mask.mean()) if alpha_mask.size else 0.0

    if 0.015 <= alpha_fill <= 0.985:
        mask = alpha_mask
    else:
        rgb = np.asarray(rgba.convert("RGB"))
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return None

        patch_h = max(2, min(12, rgb.shape[0] // 8))
        patch_w = max(2, min(12, rgb.shape[1] // 8))
        corners = np.concatenate(
            [
                rgb[:patch_h, :patch_w].reshape(-1, 3),
                rgb[:patch_h, -patch_w:].reshape(-1, 3),
                rgb[-patch_h:, :patch_w].reshape(-1, 3),
                rgb[-patch_h:, -patch_w:].reshape(-1, 3),
            ],
            axis=0,
        )
        border_color = np.median(corners, axis=0)
        diff = np.abs(rgb.astype(np.int16) - border_color.astype(np.int16)).max(axis=2)
        mask = diff > 12

    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None

    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    cropped = mask[y0:y1, x0:x1]
    if cropped.size == 0:
        return None

    usable = max(48, int(round(size * 0.82)))
    crop_image = Image.fromarray((cropped.astype(np.uint8) * 255), mode="L")
    scale = min(usable / max(1, crop_image.size[0]), usable / max(1, crop_image.size[1]))
    resized = crop_image.resize(
        (
            max(1, int(round(crop_image.size[0] * scale))),
            max(1, int(round(crop_image.size[1] * scale))),
        ),
        Image.Resampling.BILINEAR,
    )

    canvas = Image.new("L", (size, size), 0)
    offset = ((size - resized.size[0]) // 2, (size - resized.size[1]) // 2)
    canvas.paste(resized, offset)
    canvas = canvas.filter(ImageFilter.MaxFilter(3))
    return np.asarray(canvas) > 28


def build_geometry_guard_reference(image_input, profile: SubjectProfile) -> GeometryGuardReference:
    labeled_masks: list[tuple[str, np.ndarray]] = []
    generic_masks: list[np.ndarray] = []

    if isinstance(image_input, dict):
        for view, image in image_input.items():
            mask = _image_to_guard_mask(image)
            if mask is None:
                continue
            if view in VIEW_ORDER:
                labeled_masks.append((view, mask))
            else:
                generic_masks.append(mask)
    elif image_input is not None:
        mask = _image_to_guard_mask(image_input)
        if mask is not None:
            generic_masks.append(mask)

    note_parts: list[str] = []
    if labeled_masks:
        note_parts.append("views: " + ", ".join(view.capitalize() for view, _ in labeled_masks))
    if generic_masks:
        note_parts.append(f"generic refs: {len(generic_masks)}")
    if not note_parts:
        note = "Geometry guard: no usable silhouette refs"
    else:
        note = "Geometry guard: " + " | ".join(note_parts)
        if profile.is_vehicle:
            note += " | vehicle silhouette checks active"
        elif profile.is_hard_surface:
            note += " | hard-surface silhouette checks active"

    return GeometryGuardReference(
        labeled_masks=tuple(labeled_masks),
        generic_masks=tuple(generic_masks),
        note=note,
    )


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _mask_fill(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    return float(mask.mean())


def _mask_center(mask: np.ndarray) -> tuple[float, float] | None:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    mean_y, mean_x = coords.mean(axis=0)
    height, width = mask.shape
    return float(mean_x / max(width, 1)), float(mean_y / max(height, 1))


def _mask_bbox_ratio(mask: np.ndarray) -> float | None:
    bbox = _mask_bbox(mask)
    if bbox is None:
        return None
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    return float(width / height)


def _mask_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    union = np.logical_or(mask_a, mask_b).sum()
    if union <= 0:
        return 0.0
    intersection = np.logical_and(mask_a, mask_b).sum()
    return float(intersection / union)


def _mask_symmetry_error(mask: np.ndarray) -> float:
    if mask.size == 0 or not mask.any():
        return 1.0
    mirror = np.fliplr(mask)
    union = np.logical_or(mask, mirror).sum()
    if union <= 0:
        return 1.0
    mismatch = np.logical_xor(mask, mirror).sum()
    return float(mismatch / union)


def _bottom_band_metrics(
    candidate_mask: np.ndarray,
    reference_mask: np.ndarray,
    *,
    band_ratio: float = 0.22,
) -> tuple[float, float] | None:
    if candidate_mask.shape != reference_mask.shape:
        return None
    height = candidate_mask.shape[0]
    if height <= 0:
        return None

    start_row = max(0, min(height - 1, int(round(height * (1.0 - band_ratio)))))
    cand_band = candidate_mask[start_row:, :]
    ref_band = reference_mask[start_row:, :]
    if not ref_band.any():
        return None

    iou = _mask_iou(cand_band, ref_band)
    overlap = float(np.logical_and(cand_band, ref_band).sum() / max(1, ref_band.sum()))
    return iou, overlap


def _bbox_band_metrics(
    candidate_mask: np.ndarray,
    reference_mask: np.ndarray,
    *,
    region: str,
    band_ratio: float = 0.22,
) -> tuple[float, float] | None:
    if candidate_mask.shape != reference_mask.shape:
        return None
    bbox = _mask_bbox(reference_mask)
    if bbox is None:
        return None

    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    band_w = max(1, int(round(width * band_ratio)))
    band_h = max(1, int(round(height * band_ratio)))

    if region == "left":
        xs = slice(x0, min(x1, x0 + band_w))
        ys = slice(y0, y1)
    elif region == "right":
        xs = slice(max(x0, x1 - band_w), x1)
        ys = slice(y0, y1)
    elif region == "top":
        xs = slice(x0, x1)
        ys = slice(y0, min(y1, y0 + band_h))
    elif region == "bottom":
        xs = slice(x0, x1)
        ys = slice(max(y0, y1 - band_h), y1)
    else:
        return None

    ref_band = reference_mask[ys, xs]
    cand_band = candidate_mask[ys, xs]
    if not ref_band.any():
        return None

    iou = _mask_iou(cand_band, ref_band)
    overlap = float(np.logical_and(cand_band, ref_band).sum() / max(1, ref_band.sum()))
    return iou, overlap


def _extremity_band_metrics(
    candidate_mask: np.ndarray,
    reference_mask: np.ndarray,
) -> dict[str, tuple[float, float]]:
    metrics: dict[str, tuple[float, float]] = {}
    for region in ("left", "right", "top"):
        result = _bbox_band_metrics(candidate_mask, reference_mask, region=region, band_ratio=0.22)
        if result is not None:
            metrics[region] = result
    return metrics


def _compare_masks(candidate_mask: np.ndarray, reference_mask: np.ndarray) -> tuple[float, float, float, float, float]:
    iou = _mask_iou(candidate_mask, reference_mask)

    candidate_fill = _mask_fill(candidate_mask)
    reference_fill = _mask_fill(reference_mask)
    fill_gap = abs(candidate_fill - reference_fill)

    candidate_ratio = _mask_bbox_ratio(candidate_mask)
    reference_ratio = _mask_bbox_ratio(reference_mask)
    if candidate_ratio is None or reference_ratio is None:
        ratio_gap = 1.0
    else:
        ratio_gap = abs(candidate_ratio - reference_ratio) / max(reference_ratio, 0.18)

    candidate_center = _mask_center(candidate_mask)
    reference_center = _mask_center(reference_mask)
    if candidate_center is None or reference_center is None:
        center_gap = 1.0
    else:
        center_gap = min(
            1.0,
            float(np.hypot(candidate_center[0] - reference_center[0], candidate_center[1] - reference_center[1]) / 0.7),
        )

    overlap_precision = float(np.logical_and(candidate_mask, reference_mask).sum() / max(1, candidate_mask.sum()))
    overlap_recall = float(np.logical_and(candidate_mask, reference_mask).sum() / max(1, reference_mask.sum()))
    return iou, fill_gap, ratio_gap, center_gap, (overlap_precision + overlap_recall) * 0.5


def _prepare_mesh_for_geometry_guard(mesh, max_faces: int = 12000) -> tuple[np.ndarray, np.ndarray] | None:
    repaired = repair_mesh_geometry(mesh)
    vertices = np.asarray(getattr(repaired, "vertices", []), dtype=float)
    faces = np.asarray(getattr(repaired, "faces", []), dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        return None
    if faces.ndim != 2 or faces.shape[1] < 3:
        return None

    faces = faces[:, :3]
    if len(faces) == 0:
        return None

    if len(faces) > max_faces:
        try:
            simplified = repaired.simplify_quadric_decimation(face_count=max_faces)
            simplified = repair_mesh_geometry(simplified)
            simp_vertices = np.asarray(getattr(simplified, "vertices", []), dtype=float)
            simp_faces = np.asarray(getattr(simplified, "faces", []), dtype=np.int32)
            if (
                simp_vertices.ndim == 2
                and simp_vertices.shape[1] == 3
                and simp_faces.ndim == 2
                and simp_faces.shape[1] >= 3
                and len(simp_faces) > 0
            ):
                vertices = simp_vertices
                faces = simp_faces[:, :3]
        except Exception:
            stride = max(1, int(np.ceil(len(faces) / max_faces)))
            faces = faces[::stride]

    return vertices, faces


def _render_geometry_guard_mask(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    vertical_axis: int,
    yaw_deg: int,
    size: int = 192,
) -> np.ndarray:
    verts = np.asarray(vertices, dtype=float).copy()
    center = np.median(verts, axis=0)
    verts -= center
    extent = np.ptp(verts, axis=0)
    max_extent = float(np.max(extent))
    if max_extent <= 1e-9:
        return np.zeros((size, size), dtype=bool)
    verts /= max_extent

    horizontal_axes = [axis for axis in range(3) if axis != vertical_axis]
    axis_a = verts[:, horizontal_axes[0]]
    axis_b = verts[:, horizontal_axes[1]]
    vertical = verts[:, vertical_axis]

    yaw = np.deg2rad(yaw_deg)
    projected_x = (np.cos(yaw) * axis_a) + (np.sin(yaw) * axis_b)
    projected_depth = (-np.sin(yaw) * axis_a) + (np.cos(yaw) * axis_b)
    projected_y = vertical
    projected = np.stack([projected_x, projected_y], axis=1)

    min_xy = projected.min(axis=0)
    max_xy = projected.max(axis=0)
    span = np.maximum(max_xy - min_xy, 1e-6)

    work_size = 256
    margin = 18
    scale = min((work_size - margin * 2) / span[0], (work_size - margin * 2) / span[1])
    points_2d = np.empty((len(projected), 2), dtype=float)
    points_2d[:, 0] = (projected[:, 0] - min_xy[0]) * scale + margin
    points_2d[:, 1] = (max_xy[1] - projected[:, 1]) * scale + margin

    tris_2d = points_2d[faces]
    finite_mask = np.isfinite(tris_2d).all(axis=(1, 2))
    if not np.any(finite_mask):
        return np.zeros((size, size), dtype=bool)

    tris_2d = tris_2d[finite_mask]
    depth = projected_depth[faces][:, :3].mean(axis=1)[finite_mask]
    order = np.argsort(depth)

    canvas = Image.new("L", (work_size, work_size), 0)
    draw = ImageDraw.Draw(canvas, "L")
    for face_index in order:
        polygon = [tuple(point) for point in tris_2d[face_index]]
        draw.polygon(polygon, fill=255)

    canvas = canvas.filter(ImageFilter.MaxFilter(3))
    canvas = canvas.resize((size, size), Image.Resampling.BILINEAR)
    return np.asarray(canvas) > 42


def review_mesh_against_reference(
    mesh,
    reference: GeometryGuardReference | None,
    profile: SubjectProfile,
) -> GeometryGuardResult:
    if reference is None or (not reference.labeled_masks and not reference.generic_masks):
        return GeometryGuardResult(note="geometry guard skipped")

    prepared = _prepare_mesh_for_geometry_guard(mesh)
    if prepared is None:
        return GeometryGuardResult(score_adjustment=-0.75, needs_retry=True, note="geometry guard could not project mesh")

    vertices, faces = prepared
    required_views = {view for view, _ in reference.labeled_masks}
    if reference.generic_masks:
        required_views.update({"front", "left", "back", "right"})
    if profile.is_vehicle or profile.is_hard_surface:
        required_views.update({"front", "back"})
    if not required_views:
        required_views = {"front", "left", "back", "right"}

    best_result: GeometryGuardResult | None = None
    best_internal_score = -9999.0
    view_offsets = {"front": 0, "left": 90, "back": 180, "right": 270}

    for vertical_axis in range(3):
        for base_yaw in (0, 90, 180, 270):
            rendered_masks = {
                view: _render_geometry_guard_mask(
                    vertices,
                    faces,
                    vertical_axis=vertical_axis,
                    yaw_deg=(base_yaw + offset) % 360,
                )
                for view, offset in view_offsets.items()
                if view in required_views
            }

            ious: list[float] = []
            fill_gaps: list[float] = []
            ratio_gaps: list[float] = []
            center_gaps: list[float] = []
            overlaps: list[float] = []
            bottom_ious: list[float] = []
            bottom_overlaps: list[float] = []
            extremity_ious: list[float] = []
            extremity_overlaps: list[float] = []
            view_notes: list[str] = []

            for view, ref_mask in reference.labeled_masks:
                mesh_mask = rendered_masks.get(view)
                if mesh_mask is None:
                    continue
                iou, fill_gap, ratio_gap, center_gap, overlap = _compare_masks(mesh_mask, ref_mask)
                ious.append(iou)
                fill_gaps.append(fill_gap)
                ratio_gaps.append(ratio_gap)
                center_gaps.append(center_gap)
                overlaps.append(overlap)
                bottom_metrics = _bottom_band_metrics(mesh_mask, ref_mask)
                if bottom_metrics is not None:
                    bottom_ious.append(bottom_metrics[0])
                    bottom_overlaps.append(bottom_metrics[1])
                if profile.is_organic or profile.is_hard_surface:
                    extremity_metrics = _extremity_band_metrics(mesh_mask, ref_mask)
                    if extremity_metrics:
                        extremity_ious.extend(metric[0] for metric in extremity_metrics.values())
                        extremity_overlaps.extend(metric[1] for metric in extremity_metrics.values())
                view_notes.append(f"{view}:{iou:.2f}")

            if reference.generic_masks:
                generic_candidates = tuple(rendered_masks.values()) or tuple(
                    _render_geometry_guard_mask(vertices, faces, vertical_axis=vertical_axis, yaw_deg=(base_yaw + offset) % 360)
                    for offset in (0, 90, 180, 270)
                )
                for generic_mask in reference.generic_masks:
                    best_generic = None
                    for candidate_mask in generic_candidates:
                        comparison = _compare_masks(candidate_mask, generic_mask)
                        if best_generic is None or comparison[0] > best_generic[0]:
                            best_generic = comparison
                    if best_generic is None:
                        continue
                    iou, fill_gap, ratio_gap, center_gap, overlap = best_generic
                    ious.append(iou)
                    fill_gaps.append(fill_gap)
                    ratio_gaps.append(ratio_gap)
                    center_gaps.append(center_gap)
                    overlaps.append(overlap)
                    bottom_metrics = _bottom_band_metrics(candidate_mask, generic_mask)
                    if bottom_metrics is not None:
                        bottom_ious.append(bottom_metrics[0])
                        bottom_overlaps.append(bottom_metrics[1])
                    if profile.is_organic or profile.is_hard_surface:
                        extremity_metrics = _extremity_band_metrics(candidate_mask, generic_mask)
                        if extremity_metrics:
                            extremity_ious.extend(metric[0] for metric in extremity_metrics.values())
                            extremity_overlaps.extend(metric[1] for metric in extremity_metrics.values())

            if not ious:
                continue

            avg_iou = float(np.mean(np.asarray(ious, dtype=float)))
            avg_fill_gap = float(np.mean(np.asarray(fill_gaps, dtype=float)))
            avg_ratio_gap = float(np.mean(np.asarray(ratio_gaps, dtype=float)))
            avg_center_gap = float(np.mean(np.asarray(center_gaps, dtype=float)))
            avg_overlap = float(np.mean(np.asarray(overlaps, dtype=float)))
            avg_bottom_iou = float(np.mean(np.asarray(bottom_ious, dtype=float))) if bottom_ious else None
            avg_bottom_overlap = float(np.mean(np.asarray(bottom_overlaps, dtype=float))) if bottom_overlaps else None
            avg_extremity_iou = float(np.mean(np.asarray(extremity_ious, dtype=float))) if extremity_ious else None
            avg_extremity_overlap = float(np.mean(np.asarray(extremity_overlaps, dtype=float))) if extremity_overlaps else None

            symmetry_error = None
            symmetry_penalty = 0.0
            if profile.is_vehicle or (profile.is_hard_surface and not profile.is_organic):
                symmetry_values = []
                for symmetry_view in ("front", "back"):
                    mask = rendered_masks.get(symmetry_view)
                    if mask is not None and mask.any():
                        symmetry_values.append(_mask_symmetry_error(mask))
                if symmetry_values:
                    symmetry_error = float(np.mean(np.asarray(symmetry_values, dtype=float)))
                    base_tolerance = 0.10 if profile.is_vehicle else 0.14
                    symmetry_penalty = max(0.0, symmetry_error - base_tolerance) * (5.0 if profile.is_vehicle else 3.2)

            bottom_penalty = 0.0
            bottom_bonus = 0.0
            if avg_bottom_iou is not None and avg_bottom_overlap is not None:
                if profile.is_organic:
                    bottom_penalty = (
                        max(0.0, 0.50 - avg_bottom_iou) * 4.8
                        + max(0.0, 0.64 - avg_bottom_overlap) * 2.6
                    )
                    bottom_bonus = max(0.0, avg_bottom_iou - 0.62) * 1.8
                elif profile.is_hard_surface:
                    bottom_penalty = max(0.0, 0.46 - avg_bottom_iou) * 2.6
                    bottom_bonus = max(0.0, avg_bottom_iou - 0.60) * 1.0

            extremity_penalty = 0.0
            extremity_bonus = 0.0
            if avg_extremity_iou is not None and avg_extremity_overlap is not None:
                if profile.is_organic:
                    extremity_penalty = (
                        max(0.0, 0.36 - avg_extremity_iou) * 6.2
                        + max(0.0, 0.50 - avg_extremity_overlap) * 3.4
                    )
                    extremity_bonus = max(0.0, avg_extremity_iou - 0.48) * 2.2
                elif profile.is_hard_surface:
                    extremity_penalty = (
                        max(0.0, 0.34 - avg_extremity_iou) * 3.4
                        + max(0.0, 0.48 - avg_extremity_overlap) * 1.8
                    )
                    extremity_bonus = max(0.0, avg_extremity_iou - 0.46) * 1.2

            penalty = (
                max(0.0, 0.60 - avg_iou) * (9.0 if profile.is_vehicle else 7.0)
                + (avg_ratio_gap * (2.4 if profile.is_vehicle else 1.8))
                + (avg_fill_gap * 4.0)
                + (avg_center_gap * 2.6)
                + symmetry_penalty
                + bottom_penalty
                + extremity_penalty
            )
            bonus = (
                max(0.0, avg_iou - 0.74) * 3.0
                + max(0.0, avg_overlap - 0.82) * 1.6
                + bottom_bonus
                + extremity_bonus
            )
            score_adjustment = bonus - penalty
            internal_score = (
                avg_iou
                + (avg_overlap * 0.35)
                - (avg_ratio_gap * 0.15)
                - (avg_center_gap * 0.10)
                - symmetry_penalty
                - (bottom_penalty * 0.12)
                + (bottom_bonus * 0.18)
                - (extremity_penalty * 0.16)
                + (extremity_bonus * 0.20)
            )

            retry_threshold = 0.56 if profile.is_vehicle else (0.50 if profile.is_hard_surface else 0.44)
            needs_retry = avg_iou < retry_threshold or score_adjustment < (-2.1 if profile.is_vehicle else -1.5)

            note_parts = [f"guard iou {avg_iou:.2f}", f"overlap {avg_overlap:.2f}"]
            if avg_bottom_iou is not None:
                note_parts.append(f"feet/bottom {avg_bottom_iou:.2f}")
            if avg_extremity_iou is not None:
                note_parts.append(f"hands/extremities {avg_extremity_iou:.2f}")
            if view_notes:
                note_parts.append(", ".join(view_notes))
            if symmetry_error is not None:
                note_parts.append(f"sym {symmetry_error:.2f}")
            note_parts.append(f"axis {vertical_axis} yaw {base_yaw}")
            result = GeometryGuardResult(
                score_adjustment=score_adjustment,
                avg_iou=avg_iou,
                matched_views=len(ious),
                best_vertical_axis=vertical_axis,
                best_yaw_deg=base_yaw,
                symmetry_error=symmetry_error,
                needs_retry=needs_retry,
                note=" | ".join(note_parts),
            )

            if internal_score > best_internal_score:
                best_internal_score = internal_score
                best_result = result

    if best_result is None:
        return GeometryGuardResult(score_adjustment=-0.6, needs_retry=True, note="geometry guard found no stable silhouette match")
    return best_result


def compute_geometry_rescue_cap(
    planned_sample_count: int,
    profile: SubjectProfile,
    reference: GeometryGuardReference | None,
    detail_image_count: int = 0,
) -> int:
    if reference is None:
        return planned_sample_count

    labeled_count = len(reference.labeled_masks)
    cap = planned_sample_count
    if profile.is_vehicle:
        cap = max(cap, 4 if labeled_count >= 3 else 3)
    elif profile.is_transparent:
        cap = max(cap, 3 if labeled_count >= 2 else 2)
    elif profile.is_hard_surface:
        cap = max(cap, 3 if labeled_count >= 3 else 2)
    elif profile.is_organic and labeled_count >= 2:
        cap = max(cap, 3 if labeled_count < 4 else 4)
    elif profile.prefers_multiview and labeled_count >= 3:
        cap = max(cap, 2)
    if profile.has_fragile_detail:
        cap = max(cap, min(MAX_SAMPLE_COUNT, planned_sample_count + (2 if labeled_count >= 2 else 1)))
    if detail_image_count > 0:
        cap = max(cap, min(MAX_SAMPLE_COUNT, planned_sample_count + 1))
    return min(MAX_SAMPLE_COUNT, cap)


def normalize_source_resolution(image: Image.Image, preset: QualityPreset) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    min_side = max(1, min(width, height))
    max_side = max(width, height)

    upscale_target = max(SOURCE_MIN_SIDE, preset.min_input_side)
    scale = 1.0

    if min_side < upscale_target:
        scale = max(scale, upscale_target / min_side)

    if (max_side * scale) > SOURCE_MAX_SIDE:
        scale = min(scale, SOURCE_MAX_SIDE / max_side)

    if abs(scale - 1.0) > 0.02:
        new_size = (
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    return image


def _subject_mask(image: Image.Image, threshold: int = 8) -> np.ndarray:
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    mask = alpha > threshold
    if mask.any():
        return mask
    return np.ones((rgba.size[1], rgba.size[0]), dtype=bool)


def _looks_like_sketch_reference(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32) / 255.0
    mask = _subject_mask(rgba, threshold=8)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not mask.any():
        return False

    max_channel = rgb.max(axis=2)
    min_channel = rgb.min(axis=2)
    saturation = (max_channel - min_channel) / np.maximum(max_channel, 1e-5)
    subject_saturation = float(np.mean(saturation[mask]))
    subject_value = float(np.mean(max_channel[mask]))
    return subject_saturation <= 0.16 and subject_value >= 0.28


def _scan_detail_level(scan_label: str) -> int:
    label = (scan_label or "").strip().lower()
    if label in {"shape wide", "shape tight", "proportion pass"}:
        return 0
    if label in {"balanced mid"}:
        return 1
    if label in {"extremity pass", "detail pass"}:
        return 2
    if label in {"detail tight", "surface sweep", "rescue detail"}:
        return 3
    if label in {"final max detail"}:
        return 4
    return 1


def prepare_source_image(image: Image.Image, path: Path, preset: QualityPreset) -> Image.Image:
    image = normalize_source_resolution(image, preset)

    if path.suffix.lower() in {".jpg", ".jpeg", ".webp"} and min(image.size) <= 1400:
        image = image.filter(ImageFilter.MedianFilter(3))

    return image


def remove_background_with_fallback(image: Image.Image) -> Image.Image:
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        if alpha_coverage(rgba, threshold=245) < 0.995:
            return rgba

    removed = get_bg_remover()(image.convert("RGB"))
    coverage = alpha_coverage(removed, threshold=8)
    bbox = alpha_bbox(removed, threshold=8)

    if bbox is None or coverage < 0.05 or coverage > 0.97:
        return image.convert("RGBA")

    x0, y0, x1, y1 = bbox
    width, height = removed.size
    touches_edges = x0 <= 1 and y0 <= 1 and x1 >= (width - 1) and y1 >= (height - 1)
    if touches_edges and coverage > 0.90:
        return image.convert("RGBA")

    return removed


def frame_subject_square(image: Image.Image, border_ratio: float, min_side: int = 640) -> Image.Image:
    image = image.convert("RGBA")
    bbox = alpha_bbox(image, threshold=6) or image.getbbox()
    if not bbox:
        return image

    subject = image.crop(bbox)
    subject_w, subject_h = subject.size
    longest_side = max(subject_w, subject_h, 1)

    usable_ratio = min(0.94, max(0.62, 1.0 - (border_ratio * 2.0)))
    canvas_side = max(1, int(np.ceil(longest_side / usable_ratio)))

    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    offset = ((canvas_side - subject_w) // 2, (canvas_side - subject_h) // 2)
    canvas.alpha_composite(subject, offset)

    if canvas_side < min_side:
        canvas = canvas.resize((min_side, min_side), Image.Resampling.LANCZOS)

    return canvas


def refine_subject_image(image: Image.Image, preset: QualityPreset) -> Image.Image:
    image = image.convert("RGBA")
    r, g, b, a = image.split()

    alpha_clip = max(0, min(255, preset.alpha_clip))
    a = a.point(lambda value: 0 if value < alpha_clip else value)
    a = a.filter(ImageFilter.MaxFilter(3))
    a = a.filter(ImageFilter.SMOOTH_MORE)

    rgb = Image.merge("RGB", (r, g, b))
    rgb = ImageOps.autocontrast(rgb, cutoff=1)
    rgb = ImageEnhance.Contrast(rgb).enhance(preset.contrast_boost)
    rgb = ImageEnhance.Sharpness(rgb).enhance(preset.sharpness_boost)
    rgb = rgb.filter(
        ImageFilter.UnsharpMask(
            radius=preset.unsharp_radius,
            percent=preset.unsharp_percent,
            threshold=2,
        )
    )

    return Image.merge("RGBA", (*rgb.split(), a))


def enhance_scan_reference_image(
    image: Image.Image,
    preset: QualityPreset,
    scan_plan: dict[str, float | int | str],
    profile: SubjectProfile,
) -> Image.Image:
    rgba = image.convert("RGBA")
    detail_level = _scan_detail_level(str(scan_plan.get("label", "")))
    if detail_level <= 0 and not profile.has_fragile_detail:
        return rgba

    sketch_like = _looks_like_sketch_reference(rgba)
    r, g, b, a = rgba.split()
    rgb = Image.merge("RGB", (r, g, b))
    alpha = a

    if detail_level >= 1:
        alpha = alpha.filter(ImageFilter.MaxFilter(3))
    if profile.has_fragile_detail and detail_level >= 2:
        alpha = alpha.filter(ImageFilter.MaxFilter(5))
        alpha = alpha.filter(ImageFilter.SMOOTH_MORE)

    if sketch_like:
        gray = ImageOps.autocontrast(rgb.convert("L"), cutoff=0)
        rgb = Image.merge("RGB", (gray, gray, gray))
        if detail_level >= 2:
            edge = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES), cutoff=1)
            edge_rgb = Image.merge("RGB", (edge, edge, edge))
            edge_weight = min(0.24, 0.08 + (detail_level * 0.035))
            rgb = Image.blend(rgb, ImageChops.subtract(rgb, edge_rgb), edge_weight)

    if detail_level >= 1:
        contrast_gain = 1.02 + (detail_level * 0.05)
        sharpness_gain = 1.06 + (detail_level * 0.14)
        if profile.has_fragile_detail:
            contrast_gain += 0.05
            sharpness_gain += 0.14
        if sketch_like:
            contrast_gain += 0.08
            sharpness_gain += 0.10
        rgb = ImageOps.autocontrast(rgb, cutoff=1 if sketch_like else 0)
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast_gain)
        rgb = ImageEnhance.Sharpness(rgb).enhance(sharpness_gain)
        if detail_level >= 2:
            rgb = rgb.filter(ImageFilter.DETAIL)
        rgb = rgb.filter(
            ImageFilter.UnsharpMask(
                radius=min(1.95, preset.unsharp_radius + (0.12 * detail_level)),
                percent=min(
                    220,
                    preset.unsharp_percent
                    + (detail_level * 14)
                    + (18 if profile.has_fragile_detail else 0)
                    + (16 if sketch_like else 0),
                ),
                threshold=1 if sketch_like else 2,
            )
        )

    enhanced = Image.merge("RGBA", (*rgb.split(), alpha))

    if detail_level >= 2 or profile.has_fragile_detail:
        focus_border = float(scan_plan.get("border_ratio", preset.border_ratio))
        if detail_level >= 2:
            focus_border -= 0.004
        if profile.has_fragile_detail:
            focus_border -= 0.004
        if profile.has_cloth_detail:
            focus_border -= 0.003
        focus_border = max(0.022, min(0.16, focus_border))
        focus_min_side = max(
            preset.min_input_side,
            min(
                SOURCE_MAX_SIDE,
                int(round(max(enhanced.size) * (1.14 if detail_level >= 3 else 1.06))),
            ),
        )
        enhanced = frame_subject_square(enhanced, border_ratio=focus_border, min_side=focus_min_side)

    return enhanced


def build_scan_image_input(
    image_input,
    detail_references: tuple[DetailReference, ...],
    preset: QualityPreset,
    scan_plan: dict[str, float | int | str],
    profile: SubjectProfile,
):
    detail_level = _scan_detail_level(str(scan_plan.get("label", "")))
    if isinstance(image_input, dict):
        staged = {
            view: enhance_scan_reference_image(image, preset, scan_plan, profile)
            for view, image in image_input.items()
        }
        if detail_references and detail_level >= 3:
            preferred_view = "front" if "front" in staged else next(iter(staged), None)
            if preferred_view is not None:
                staged[preferred_view] = compose_detail_assist_image(staged[preferred_view], detail_references, detail_level)
        return harmonize_multiview_subject_scale(staged)
    base = enhance_scan_reference_image(image_input, preset, scan_plan, profile)
    if not detail_references or detail_level < 2:
        return base
    return compose_detail_assist_image(base, detail_references, detail_level)


def _fit_detail_crop_tile(detail_image: Image.Image, tile_side: int) -> Image.Image:
    detail = detail_image.convert("RGBA")
    bbox = alpha_bbox(detail, threshold=6) or detail.getbbox()
    if bbox:
        detail = detail.crop(bbox)
    detail = frame_subject_square(detail, border_ratio=0.08, min_side=tile_side)
    return detail.resize((tile_side, tile_side), Image.Resampling.LANCZOS)


def _edge_guide_strength(target: str, detail_level: int) -> tuple[float, float]:
    normalized = normalize_detail_target(target)
    if normalized in {"Hand", "Foot / Shoe", "Cape / Cloth", "Face"}:
        return 1.55 + (detail_level * 0.10), 0.24 + (detail_level * 0.02)
    if normalized in {"Head / Helmet", "Torso / Chest", "Arm", "Leg", "Back Detail"}:
        return 1.32 + (detail_level * 0.08), 0.18 + (detail_level * 0.02)
    return 1.18 + (detail_level * 0.06), 0.14 + (detail_level * 0.015)


def apply_detail_edge_guide(detail_image: Image.Image, target: str, detail_level: int) -> Image.Image:
    rgba = detail_image.convert("RGBA")
    r, g, b, a = rgba.split()
    rgb = Image.merge("RGB", (r, g, b))
    gray = ImageOps.autocontrast(rgb.convert("L"), cutoff=1)
    tonal_edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES), cutoff=1)
    alpha_edges = ImageOps.autocontrast(a.filter(ImageFilter.FIND_EDGES), cutoff=1)
    edge_map = ImageChops.lighter(tonal_edges, alpha_edges)
    edge_strength, blend_amount = _edge_guide_strength(target, detail_level)
    edge_map = ImageEnhance.Contrast(edge_map).enhance(edge_strength)
    if normalize_detail_target(target) in {"Hand", "Foot / Shoe", "Cape / Cloth"}:
        edge_map = edge_map.filter(ImageFilter.MaxFilter(3))
    edge_rgb = Image.merge("RGB", (edge_map, edge_map, edge_map))
    guided_rgb = Image.blend(rgb, ImageChops.screen(rgb, edge_rgb), min(0.36, blend_amount))
    guided_rgb = ImageEnhance.Sharpness(guided_rgb).enhance(1.08 + (detail_level * 0.10))
    return Image.merge("RGBA", (*guided_rgb.split(), a))


def _build_detail_tile(detail_ref: DetailReference, tile_side: int, detail_level: int) -> Image.Image:
    detail = detail_ref.image.convert("RGBA")
    bbox = alpha_bbox(detail, threshold=6) or detail.getbbox()
    if bbox:
        detail = detail.crop(bbox)
    detail = frame_subject_square(detail, border_ratio=0.08, min_side=tile_side)
    if detail_level >= 3:
        detail = apply_detail_edge_guide(detail, detail_ref.target, detail_level)
    return detail.resize((tile_side, tile_side), Image.Resampling.LANCZOS)


def compose_detail_assist_image(
    base_image: Image.Image,
    detail_references: tuple[DetailReference, ...],
    detail_level: int,
) -> Image.Image:
    canvas = base_image.convert("RGBA").copy()
    if not detail_references:
        return canvas

    side = min(canvas.size)
    shown_count = min(len(detail_references), 2 if detail_level <= 2 else (4 if detail_level <= 3 else MAX_DETAIL_REFERENCES))
    columns = 2 if shown_count > 1 else 1
    rows = 1 if shown_count <= 2 else (2 if shown_count <= 4 else 3)
    scale = 0.28 if shown_count <= 2 else (0.22 if shown_count <= 4 else 0.17)
    tile_side = int(side * scale)
    tile_side = max(120, min(tile_side, side // max(3, columns + 1)))
    margin = max(18, side // 28)
    card_padding = max(8, tile_side // 18)
    gap = max(16, tile_side // 10)

    positions: list[tuple[int, int]] = []
    total_block_height = (rows * tile_side) + ((rows - 1) * gap)
    start_y = max(margin, (side - total_block_height) // 2)
    start_x = side - ((columns * tile_side) + ((columns - 1) * gap)) - margin
    for index in range(shown_count):
        row = index // columns
        col = index % columns
        x = start_x + (col * (tile_side + gap))
        y = start_y + (row * (tile_side + gap))
        positions.append((x, y))

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    for index, detail_ref in enumerate(detail_references[:shown_count]):
        if index >= len(positions):
            break
        x, y = positions[index]
        tile = _build_detail_tile(detail_ref, tile_side, detail_level)
        card_box = (
            x - card_padding,
            y - card_padding,
            x + tile_side + card_padding,
            y + tile_side + card_padding,
        )
        draw.rounded_rectangle(card_box, radius=max(12, tile_side // 12), fill=(250, 252, 255, 238), outline=(150, 162, 176, 255), width=max(2, tile_side // 80))
        overlay.alpha_composite(tile, (x, y))
        label = normalize_detail_target(detail_ref.target)
        if label != "Auto":
            label_text = label.replace(" / ", " ")
            text_box = (
                x + 8,
                y + tile_side - max(30, tile_side // 6),
                x + tile_side - 8,
                y + tile_side - 8,
            )
            draw.rounded_rectangle(text_box, radius=8, fill=(15, 22, 34, 196))
            draw.text((text_box[0] + 8, text_box[1] + 6), label_text, fill=(242, 246, 255, 255))

    composed = canvas.copy()
    composed.alpha_composite(overlay)
    return composed


def load_image(path: Path, remove_background: bool, preset: QualityPreset, profile: SubjectProfile) -> Image.Image:
    image = Image.open(path)
    image = trim_uniform_borders(image)
    image = prepare_source_image(image, path, preset)
    if remove_background:
        image = remove_background_with_fallback(image)
    else:
        image = image.convert("RGBA")
    if profile.is_transparent:
        image = image.filter(ImageFilter.MedianFilter(3))
    image = refine_subject_image(image, preset)
    return frame_subject_square(image, border_ratio=preset.border_ratio)


def resolve_image_input(
    selected_images: list[SelectedImage],
    remove_background: bool,
    preset: QualityPreset,
    profile: SubjectProfile,
) -> tuple[object, tuple[DetailReference, ...], str]:
    active = [item for item in selected_images if (item.view_value or "").strip().lower() != "ignore"]
    if not active:
        raise ValueError("Select at least one image.")

    primary_items, detail_items = split_reference_images(active)
    if not primary_items and detail_items:
        primary_items = [detail_items[0]]
        detail_items = detail_items[1:]

    detail_references = tuple(
        DetailReference(
            image=load_image(item.path, remove_background, preset, profile),
            target=normalize_detail_target(item.detail_target),
            source_name=item.path.name,
        )
        for item in detail_items[:MAX_DETAIL_REFERENCES]
    )
    detail_summary = ""
    if detail_items:
        detail_summary = " | detail crops: " + ", ".join(
            f"{item.path.name} [{normalize_detail_target(item.detail_target)}]"
            if normalize_detail_target(item.detail_target) != "Auto"
            else item.path.name
            for item in detail_items[:MAX_DETAIL_REFERENCES]
        )

    if len(primary_items) == 1:
        single = primary_items[0]
        return (
            load_image(single.path, remove_background, preset, profile),
            detail_references,
            f"Single image: {single.path.name}{detail_summary}",
        )

    explicit: dict[str, Path] = {}
    auto_items: list[SelectedImage] = []

    for item in primary_items[:MAX_PRIMARY_REFERENCES]:
        chosen = item.view_value.lower()
        if chosen == "auto":
            auto_items.append(item)
            continue
        if chosen in explicit:
            raise ValueError(f"Duplicate view assignment: {chosen}")
        explicit[chosen] = item.path

    remaining_views = [view for view in VIEW_ORDER if view not in explicit]

    for item in auto_items:
        guessed = guess_view_from_name(item.path)
        if guessed and guessed in remaining_views:
            explicit[guessed] = item.path
            remaining_views.remove(guessed)

    for item in auto_items:
        if item.path in explicit.values():
            continue
        if not remaining_views:
            break
        explicit[remaining_views.pop(0)] = item.path

    if len(explicit) < 2:
        first_item = primary_items[0]
        return (
            load_image(first_item.path, remove_background, preset, profile),
            detail_references,
            f"Single image fallback: {first_item.path.name}{detail_summary}",
        )

    image_dict = {view: load_image(path, remove_background, preset, profile) for view, path in explicit.items()}
    image_dict = harmonize_multiview_subject_scale(image_dict)
    summary = ", ".join(f"{view}={path.name}" for view, path in explicit.items())
    return image_dict, detail_references, f"Multiview: {summary} | scale-aligned{detail_summary}"


def build_output_path(base_name: str, suffix: str = "") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_name = sanitize_name(base_name)
    if suffix:
        final_name = f"{final_name}_{suffix}"
    return DESKTOP_DIR / f"{final_name}_{stamp}.glb"


def normalize_triangle_budget(value: int | None) -> int | None:
    if value is None:
        return None
    value = int(value)
    return max(MIN_TRIANGLE_BUDGET, min(MAX_TRIANGLE_BUDGET, value))


def normalize_sample_count(value: int | None) -> int:
    if value is None:
        return MIN_SAMPLE_COUNT
    value = int(value)
    return max(MIN_SAMPLE_COUNT, min(MAX_SAMPLE_COUNT, value))


def normalize_percent_limit(value: int | None, fallback: int) -> int:
    if value is None:
        return fallback
    value = int(value)
    return max(35, min(95, value))


SCAN_STAGE_LIBRARY: tuple[dict[str, float | str], ...] = (
    {
        "label": "shape wide",
        "note": "broad silhouette sweep",
        "steps_delta": -10,
        "guidance_delta": -0.25,
        "octree_delta": -96,
        "border_delta": 0.020,
        "chunk_scale": 1.00,
    },
    {
        "label": "shape tight",
        "note": "tighter silhouette pass",
        "steps_delta": -6,
        "guidance_delta": -0.15,
        "octree_delta": -64,
        "border_delta": 0.008,
        "chunk_scale": 1.00,
    },
    {
        "label": "proportion pass",
        "note": "checks bulk and proportion earlier",
        "steps_delta": -2,
        "guidance_delta": -0.08,
        "octree_delta": -32,
        "border_delta": 0.002,
        "chunk_scale": 1.00,
    },
    {
        "label": "balanced mid",
        "note": "middle-pass balance",
        "steps_delta": 0,
        "guidance_delta": 0.00,
        "octree_delta": 0,
        "border_delta": -0.004,
        "chunk_scale": 0.98,
    },
    {
        "label": "extremity pass",
        "note": "tries to help hands, feet, and ends of shapes",
        "steps_delta": 4,
        "guidance_delta": 0.05,
        "octree_delta": 16,
        "border_delta": -0.010,
        "chunk_scale": 0.96,
    },
    {
        "label": "detail pass",
        "note": "pushes more surface definition",
        "steps_delta": 6,
        "guidance_delta": 0.08,
        "octree_delta": 24,
        "border_delta": -0.012,
        "chunk_scale": 0.94,
    },
    {
        "label": "detail tight",
        "note": "denser detail with tighter framing",
        "steps_delta": 8,
        "guidance_delta": 0.10,
        "octree_delta": 32,
        "border_delta": -0.016,
        "chunk_scale": 0.92,
    },
    {
        "label": "surface sweep",
        "note": "extra pass for noisy surfaces and armor folds",
        "steps_delta": 10,
        "guidance_delta": 0.12,
        "octree_delta": 40,
        "border_delta": -0.018,
        "chunk_scale": 0.90,
    },
    {
        "label": "rescue detail",
        "note": "late rescue pass for missed detail",
        "steps_delta": 4,
        "guidance_delta": -0.04,
        "octree_delta": 28,
        "border_delta": -0.006,
        "chunk_scale": 0.88,
    },
    {
        "label": "final max detail",
        "note": "last high-detail sweep",
        "steps_delta": 12,
        "guidance_delta": 0.14,
        "octree_delta": 56,
        "border_delta": -0.014,
        "chunk_scale": 0.86,
    },
)

SINGLE_PASS_SCAN_PROFILE: dict[str, float | str] = {
    "label": "all-round single pass",
    "note": "one-pass shape and detail balance",
    "steps_delta": 6,
    "guidance_delta": 0.05,
    "octree_delta": 24,
    "border_delta": -0.006,
    "chunk_scale": 0.98,
}


def _resolve_scan_base_runtime(
    preset: QualityPreset,
    options: GenerationOptions,
    profile: SubjectProfile,
) -> dict[str, float | int]:
    soft_vram = normalize_percent_limit(options.soft_vram_limit_percent, 84)
    soft_ram = normalize_percent_limit(options.soft_ram_limit_percent, 82)

    base_chunks = preset.num_chunks
    base_octree = preset.octree_resolution
    base_steps = preset.steps
    guidance_scale = preset.guidance_scale
    border_ratio = preset.border_ratio

    if profile.is_vehicle:
        base_steps += 6
        base_octree = min(576, base_octree + 32)
        border_ratio = max(0.04, border_ratio - 0.015)
        guidance_scale = max(4.8, guidance_scale - 0.15)
    elif profile.is_hard_surface:
        base_steps += 4
        base_octree = min(544, base_octree + 16)
        border_ratio = max(0.05, border_ratio - 0.010)
    elif profile.is_transparent:
        border_ratio = min(0.18, border_ratio + 0.010)
        guidance_scale = max(4.5, guidance_scale - 0.10)

    if profile.has_fragile_detail:
        base_steps += 2
        base_octree = min(608, base_octree + 16)
        border_ratio = max(0.038, border_ratio - 0.006)

    if options.memory_guard:
        if soft_vram <= 55 or soft_ram <= 55:
            base_chunks = min(base_chunks, 12000)
        elif soft_vram <= 65 or soft_ram <= 65:
            base_chunks = min(base_chunks, 16000)
        elif soft_vram <= 75 or soft_ram <= 72:
            base_chunks = min(base_chunks, 22000)
        elif soft_vram <= 85 or soft_ram <= 82:
            base_chunks = min(base_chunks, 30000)

    return {
        "steps": int(base_steps),
        "guidance_scale": float(guidance_scale),
        "octree_resolution": int(base_octree),
        "num_chunks": int(base_chunks),
        "border_ratio": float(border_ratio),
    }


def _apply_scan_profile(
    base_runtime: dict[str, float | int],
    profile: SubjectProfile,
    scan_profile: dict[str, float | str],
) -> dict[str, float | int | str]:
    steps = int(base_runtime["steps"]) + int(scan_profile["steps_delta"])
    guidance_scale = float(base_runtime["guidance_scale"]) + float(scan_profile["guidance_delta"])
    octree_resolution = int(base_runtime["octree_resolution"]) + int(scan_profile["octree_delta"])
    border_ratio = float(base_runtime["border_ratio"]) + float(scan_profile["border_delta"])
    num_chunks = int(round(int(base_runtime["num_chunks"]) * float(scan_profile["chunk_scale"])))

    if profile.is_organic and scan_profile["label"] in {"extremity pass", "detail tight", "final max detail"}:
        steps += 2
        octree_resolution += 16
        border_ratio -= 0.003
    elif profile.is_vehicle and scan_profile["label"] in {"shape wide", "shape tight", "proportion pass"}:
        border_ratio += 0.004
        guidance_scale -= 0.04

    if profile.has_fragile_detail and scan_profile["label"] in {
        "extremity pass",
        "detail pass",
        "detail tight",
        "surface sweep",
        "rescue detail",
        "final max detail",
    }:
        steps += 3
        guidance_scale += 0.05
        octree_resolution += 24
        border_ratio -= 0.006

    if profile.has_cloth_detail and scan_profile["label"] in {"surface sweep", "rescue detail", "final max detail"}:
        steps += 2
        octree_resolution += 16
        border_ratio -= 0.003

    return {
        "label": str(scan_profile["label"]),
        "note": str(scan_profile["note"]),
        "steps": max(22, steps),
        "guidance_scale": max(3.5, guidance_scale),
        "octree_resolution": max(256, min(640, octree_resolution)),
        "num_chunks": max(8000, num_chunks),
        "border_ratio": max(0.03, min(0.18, border_ratio)),
    }


def _select_layered_scan_indexes(sample_count: int) -> list[int]:
    if sample_count <= 1:
        return []

    stage_total = len(SCAN_STAGE_LIBRARY)
    positions = np.linspace(0, stage_total - 1, num=sample_count)
    ordered: list[int] = []
    used: set[int] = set()

    for position in positions:
        index = int(round(float(position)))
        index = max(0, min(stage_total - 1, index))
        if index not in used:
            ordered.append(index)
            used.add(index)

    if len(ordered) < sample_count:
        for index in range(stage_total):
            if index in used:
                continue
            ordered.append(index)
            used.add(index)
            if len(ordered) >= sample_count:
                break

    return sorted(ordered[:sample_count])


def build_layered_scan_plan(
    planned_count: int,
    preset: QualityPreset,
    options: GenerationOptions,
    profile: SubjectProfile,
) -> list[dict[str, float | int | str]]:
    planned_count = normalize_sample_count(planned_count)
    base_runtime = _resolve_scan_base_runtime(preset, options, profile)

    if planned_count <= 1:
        return [_apply_scan_profile(base_runtime, profile, SINGLE_PASS_SCAN_PROFILE)]

    selected_indexes = _select_layered_scan_indexes(planned_count)
    if not selected_indexes:
        return [_apply_scan_profile(base_runtime, profile, SINGLE_PASS_SCAN_PROFILE)]

    return [
        _apply_scan_profile(base_runtime, profile, SCAN_STAGE_LIBRARY[index])
        for index in selected_indexes
    ]


def resolve_triangle_target(options: GenerationOptions, preset: QualityPreset) -> int | None:
    explicit_target = normalize_triangle_budget(options.max_triangles)
    if explicit_target is not None:
        return explicit_target
    if options.cleanup_mode == "Clean + Simpler":
        return normalize_triangle_budget(preset.simplify_target_faces)
    return None


def is_memory_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "out of memory",
        "cuda out of memory",
        "hiperroroutofmemory",
        "memory allocation",
        "not enough memory",
        "resource exhausted",
    )
    return any(marker in text for marker in markers)


def build_runtime_attempts(
    scan_runtime: dict[str, float | int | str],
    options: GenerationOptions,
) -> list[dict[str, float | int | str]]:
    base_steps = int(scan_runtime["steps"])
    guidance_scale = float(scan_runtime["guidance_scale"])
    base_octree = int(scan_runtime["octree_resolution"])
    base_chunks = int(scan_runtime["num_chunks"])
    border_ratio = float(scan_runtime["border_ratio"])
    scan_label = str(scan_runtime["label"])
    scan_note = str(scan_runtime.get("note", ""))

    attempts = [
        {
            "label": f"{scan_label} | primary",
            "scan_note": scan_note,
            "steps": base_steps,
            "guidance_scale": guidance_scale,
            "octree_resolution": base_octree,
            "num_chunks": base_chunks,
            "border_ratio": border_ratio,
        },
        {
            "label": f"{scan_label} | safer chunks",
            "scan_note": scan_note,
            "steps": base_steps,
            "guidance_scale": guidance_scale,
            "octree_resolution": base_octree,
            "num_chunks": max(8000, min(base_chunks, max(8000, base_chunks // 2))),
            "border_ratio": border_ratio,
        },
        {
            "label": f"{scan_label} | safer octree",
            "scan_note": scan_note,
            "steps": base_steps,
            "guidance_scale": max(3.5, guidance_scale - 0.10),
            "octree_resolution": max(256, base_octree - 64),
            "num_chunks": max(8000, min(base_chunks, 12000)),
            "border_ratio": min(0.18, border_ratio + 0.01),
        },
        {
            "label": f"{scan_label} | last safe retry",
            "scan_note": scan_note,
            "steps": max(24, base_steps - 6),
            "guidance_scale": max(3.5, guidance_scale - 0.25),
            "octree_resolution": max(256, base_octree - 128),
            "num_chunks": 8000,
            "border_ratio": min(0.18, border_ratio + 0.015),
        },
    ]

    deduped: list[dict[str, float | int | str]] = []
    seen: set[tuple[int, int, int]] = set()
    for attempt in attempts:
        key = (
            int(attempt["steps"]),
            int(attempt["octree_resolution"]),
            int(attempt["num_chunks"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(attempt)

    return deduped


def clone_image_input(image_input):
    if isinstance(image_input, dict):
        return {view: image.copy() for view, image in image_input.items()}
    return image_input.copy()


def repair_mesh_geometry(mesh):
    import trimesh

    if isinstance(mesh, trimesh.Scene):
        combined = trimesh.Trimesh()
        for geom in mesh.geometry.values():
            combined = trimesh.util.concatenate([combined, geom])
        mesh = combined

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    mesh = mesh.copy()

    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass

    try:
        mesh.update_faces(mesh.nondegenerate_faces())
    except Exception:
        pass

    try:
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass

    try:
        mesh.merge_vertices(digits_vertex=6)
    except Exception:
        pass

    try:
        trimesh.repair.fix_normals(mesh, multibody=True)
    except Exception:
        pass

    try:
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass

    return mesh


def smooth_mesh_for_editability(mesh, iterations: int = 4):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    smoothed = mesh.copy()
    try:
        trimesh.smoothing.filter_taubin(
            smoothed,
            lamb=0.5,
            nu=-0.53,
            iterations=iterations,
        )
    except Exception:
        return mesh

    return repair_mesh_geometry(smoothed)


def fill_mesh_holes(mesh):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    filled = mesh.copy()
    try:
        trimesh.repair.fill_holes(filled)
    except Exception:
        return mesh
    return repair_mesh_geometry(filled)


def prune_tiny_components(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    try:
        components = list(mesh.split(only_watertight=False))
    except Exception:
        return mesh

    if len(components) <= 1:
        return mesh

    total_faces = sum(len(getattr(component, "faces", [])) for component in components)
    total_area = sum(float(getattr(component, "area", 0.0)) for component in components)
    if total_faces <= 0:
        return mesh

    ranked = sorted(
        (
            (
                len(getattr(component, "faces", [])),
                float(getattr(component, "area", 0.0)),
                component,
            )
            for component in components
        ),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    main_faces = max(1, ranked[0][0])
    main_area = max(1e-6, ranked[0][1])

    if profile.is_vehicle:
        keep_limit = 5
        face_threshold = 0.0030
        area_threshold = 0.0020
    elif profile.is_hard_surface or profile.is_transparent:
        keep_limit = 4
        face_threshold = 0.0025
        area_threshold = 0.0015
    else:
        keep_limit = 3
        face_threshold = 0.0020
        area_threshold = 0.0010

    if profile.has_fragile_detail:
        keep_limit += 1
        face_threshold *= 0.72
        area_threshold *= 0.72

    kept: list[trimesh.Trimesh] = []
    for index, (face_count, area, component) in enumerate(ranked):
        face_ratio = face_count / max(total_faces, 1)
        area_ratio = area / max(total_area, 1e-6)
        relative_to_main_faces = face_count / max(main_faces, 1)
        relative_to_main_area = area / max(main_area, 1e-6)
        significant = area_ratio >= area_threshold or (
            face_ratio >= face_threshold and relative_to_main_area >= max(0.0035, area_threshold * 0.45)
        )
        early_but_meaningful = (
            index < keep_limit
            and (
                relative_to_main_faces >= 0.012
                or relative_to_main_area >= 0.008
                or face_count >= 180
            )
            and relative_to_main_area >= max(0.0025, area_threshold * 0.35)
        )
        microscopic = face_count < 48 and area_ratio < (area_threshold * 0.25)
        if index == 0 or (not microscopic and (significant or early_but_meaningful)):
            kept.append(component)

    if len(kept) == len(components):
        return mesh
    if not kept:
        return mesh

    combined = trimesh.util.concatenate(kept)
    return repair_mesh_geometry(combined)


def orient_mesh_using_guard(mesh, guard: GeometryGuardResult | None):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh
    if guard is None or guard.best_vertical_axis is None or guard.best_yaw_deg is None:
        return mesh

    vertical_axis = int(guard.best_vertical_axis)
    yaw_deg = int(guard.best_yaw_deg)
    if vertical_axis not in (0, 1, 2):
        return mesh

    horizontal_axes = [axis for axis in range(3) if axis != vertical_axis]
    yaw = np.deg2rad(yaw_deg)

    transform = np.zeros((3, 3), dtype=float)
    transform[0, horizontal_axes[0]] = np.cos(yaw)
    transform[0, horizontal_axes[1]] = np.sin(yaw)
    transform[1, horizontal_axes[0]] = -np.sin(yaw)
    transform[1, horizontal_axes[1]] = np.cos(yaw)
    transform[2, vertical_axis] = 1.0

    oriented = mesh.copy()
    matrix = np.eye(4, dtype=float)
    matrix[:3, :3] = transform
    try:
        oriented.apply_transform(matrix)
    except Exception:
        return mesh
    return repair_mesh_geometry(oriented)


def center_and_ground_mesh(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    centered = mesh.copy()
    vertices = np.asarray(centered.vertices, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        return mesh

    x_mid = float((vertices[:, 0].min() + vertices[:, 0].max()) * 0.5)
    y_mid = float((vertices[:, 1].min() + vertices[:, 1].max()) * 0.5)

    grounded_percentile = 0.8 if (profile.is_vehicle or profile.is_hard_surface or profile.is_transparent) else 0.3
    z_ground = float(np.percentile(vertices[:, 2], grounded_percentile))

    vertices[:, 0] -= x_mid
    vertices[:, 1] -= y_mid
    vertices[:, 2] -= z_ground

    extent_z = max(1e-6, float(vertices[:, 2].max() - vertices[:, 2].min()))
    min_z = float(vertices[:, 2].min())
    if min_z < -max(0.0015, extent_z * 0.003):
        vertices[:, 2] -= min_z

    # Hard-surface objects benefit from a flatter contact patch.
    # Organic characters lose boot and foot shape if we flatten the whole bottom band.
    if not profile.is_organic:
        floor_band = max(0.0015, extent_z * (0.018 if profile.is_vehicle else (0.014 if profile.is_hard_surface else 0.012)))
        low_mask = vertices[:, 2] <= floor_band
        low_ratio = float(low_mask.mean()) if len(vertices) else 0.0
        if 8 <= int(low_mask.sum()) and low_ratio <= 0.18:
            vertices[low_mask, 2] = 0.0

    centered.vertices = vertices
    return repair_mesh_geometry(centered)


def _bounds_gap_xy(bounds_a: np.ndarray, bounds_b: np.ndarray) -> float:
    ax0, ay0 = float(bounds_a[0][0]), float(bounds_a[0][1])
    ax1, ay1 = float(bounds_a[1][0]), float(bounds_a[1][1])
    bx0, by0 = float(bounds_b[0][0]), float(bounds_b[0][1])
    bx1, by1 = float(bounds_b[1][0]), float(bounds_b[1][1])

    gap_x = max(0.0, max(ax0 - bx1, bx0 - ax1))
    gap_y = max(0.0, max(ay0 - by1, by0 - ay1))
    return float(np.hypot(gap_x, gap_y))


def _bounds_overlap_ratio_xy(bounds_a: np.ndarray, bounds_b: np.ndarray) -> float:
    overlap_x = max(0.0, min(float(bounds_a[1][0]), float(bounds_b[1][0])) - max(float(bounds_a[0][0]), float(bounds_b[0][0])))
    overlap_y = max(0.0, min(float(bounds_a[1][1]), float(bounds_b[1][1])) - max(float(bounds_a[0][1]), float(bounds_b[0][1])))
    overlap_area = overlap_x * overlap_y
    area_a = max(1e-6, (float(bounds_a[1][0]) - float(bounds_a[0][0])) * (float(bounds_a[1][1]) - float(bounds_a[0][1])))
    area_b = max(1e-6, (float(bounds_b[1][0]) - float(bounds_b[0][0])) * (float(bounds_b[1][1]) - float(bounds_b[0][1])))
    return float(overlap_area / max(1e-6, min(area_a, area_b)))


def _is_suspicious_low_component(
    *,
    bounds: np.ndarray,
    extents: np.ndarray,
    face_ratio: float,
    area_ratio: float,
    relative_face_ratio: float,
    relative_area_ratio: float,
    main_bounds: np.ndarray,
    main_height: float,
    profile: SubjectProfile,
) -> bool:
    z_max = float(bounds[1][2])
    z_min = float(bounds[0][2])
    z_extent = float(extents[2])
    overlap_ratio_xy = _bounds_overlap_ratio_xy(main_bounds, bounds)
    flatness = float(min(extents) / max(max(extents), 1e-6))
    centroid_z = float(np.mean(bounds[:, 2]))
    gap_xy = _bounds_gap_xy(main_bounds, bounds)

    low_flat_scrap = (
        z_max <= (main_height * 0.30)
        and z_min <= (main_height * 0.10)
        and centroid_z <= (main_height * 0.18)
        and z_extent <= (main_height * 0.16)
        and flatness <= 0.16
        and overlap_ratio_xy <= 0.28
        and face_ratio <= 0.20
        and area_ratio <= 0.14
        and relative_face_ratio <= 0.24
        and relative_area_ratio <= 0.14
    )

    low_isolated_scrap = (
        z_max <= (main_height * 0.42)
        and centroid_z <= (main_height * 0.24)
        and z_extent <= (main_height * 0.22)
        and overlap_ratio_xy <= 0.12
        and gap_xy <= (main_height * 0.18)
        and face_ratio <= 0.08
        and area_ratio <= 0.06
        and relative_face_ratio <= 0.10
        and relative_area_ratio <= 0.06
    )

    low_thin_scrap = (
        z_max <= (main_height * 0.38)
        and centroid_z <= (main_height * 0.22)
        and z_extent <= (main_height * 0.20)
        and flatness <= 0.28
        and overlap_ratio_xy <= 0.18
        and face_ratio <= 0.10
        and area_ratio <= 0.07
        and relative_face_ratio <= 0.12
        and relative_area_ratio <= 0.08
    )

    if not (profile.is_organic or profile.is_hard_surface or profile.is_vehicle):
        return False
    return low_flat_scrap or low_isolated_scrap or low_thin_scrap


def prune_low_detached_scraps(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh

    try:
        components = list(mesh.split(only_watertight=False))
    except Exception:
        return mesh

    if len(components) <= 1:
        return mesh

    ranked = sorted(
        (
            (
                len(getattr(component, "faces", [])),
                float(getattr(component, "area", 0.0)),
                component,
            )
            for component in components
        ),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )

    main_faces, main_area, main_component = ranked[0]
    main_bounds = np.asarray(main_component.bounds, dtype=float)
    main_height = max(1e-6, float(main_component.extents[2]))
    total_faces = sum(item[0] for item in ranked)
    total_area = sum(item[1] for item in ranked)

    kept = [main_component]
    for face_count, area, component in ranked[1:]:
        bounds = np.asarray(component.bounds, dtype=float)
        extents = np.asarray(component.extents, dtype=float)
        face_ratio = face_count / max(total_faces, 1)
        area_ratio = area / max(total_area, 1e-6)
        relative_face_ratio = face_count / max(main_faces, 1)
        relative_area_ratio = area / max(main_area, 1e-6)
        if _is_suspicious_low_component(
            bounds=bounds,
            extents=extents,
            face_ratio=face_ratio,
            area_ratio=area_ratio,
            relative_face_ratio=relative_face_ratio,
            relative_area_ratio=relative_area_ratio,
            main_bounds=main_bounds,
            main_height=main_height,
            profile=profile,
        ):
            continue
        kept.append(component)

    if len(kept) == len(components):
        return mesh

    combined = trimesh.util.concatenate(kept)
    return repair_mesh_geometry(combined)


def prune_low_ground_flaps(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh
    if not (profile.is_organic or profile.is_hard_surface or profile.is_vehicle):
        return mesh

    mesh = repair_mesh_geometry(mesh)
    vertices = np.asarray(getattr(mesh, "vertices", []), dtype=float)
    faces = np.asarray(getattr(mesh, "faces", []), dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        return mesh
    if faces.ndim != 2 or faces.shape[1] < 3 or len(faces) < 16:
        return mesh

    faces = faces[:, :3]
    mesh_height = max(1e-6, float(np.ptp(vertices[:, 2])))
    face_vertices = vertices[faces]
    face_z_min = face_vertices[:, :, 2].min(axis=1)
    face_z_max = face_vertices[:, :, 2].max(axis=1)
    face_z_centroid = face_vertices[:, :, 2].mean(axis=1)

    band_top = mesh_height * (0.115 if profile.is_organic else 0.13)
    center_top = mesh_height * (0.060 if profile.is_organic else 0.075)
    candidate_mask = (
        (face_z_min <= (mesh_height * 0.018))
        & (face_z_max <= band_top)
        & (face_z_centroid <= center_top)
    )
    candidate_indices = np.flatnonzero(candidate_mask)
    if len(candidate_indices) < 2:
        return mesh

    candidate_set = set(int(index) for index in candidate_indices.tolist())
    adjacency_pairs = np.asarray(getattr(mesh, "face_adjacency", []), dtype=np.int32)
    adjacency_map: dict[int, set[int]] = {int(index): set() for index in candidate_indices.tolist()}
    attachment_counts: dict[int, int] = {int(index): 0 for index in candidate_indices.tolist()}

    if adjacency_pairs.ndim == 2 and adjacency_pairs.shape[1] >= 2:
        for left_raw, right_raw in adjacency_pairs[:, :2]:
            left = int(left_raw)
            right = int(right_raw)
            left_is_candidate = left in candidate_set
            right_is_candidate = right in candidate_set
            if left_is_candidate and right_is_candidate:
                adjacency_map[left].add(right)
                adjacency_map[right].add(left)
            elif left_is_candidate:
                attachment_counts[left] += 1
            elif right_is_candidate:
                attachment_counts[right] += 1

    total_area = float(getattr(mesh, "area", 0.0))
    if total_area <= 1e-8:
        total_area = float(np.sum(getattr(mesh, "area_faces", np.zeros(len(faces), dtype=float))))
    area_faces = np.asarray(getattr(mesh, "area_faces", np.zeros(len(faces), dtype=float)), dtype=float)

    removable_face_mask = np.zeros(len(faces), dtype=bool)
    visited: set[int] = set()
    for start in candidate_indices.tolist():
        if start in visited:
            continue

        stack = [int(start)]
        component_faces: list[int] = []
        while stack:
            face_index = stack.pop()
            if face_index in visited:
                continue
            visited.add(face_index)
            component_faces.append(face_index)
            stack.extend(neighbor for neighbor in adjacency_map.get(face_index, ()) if neighbor not in visited)

        unique_vertices = np.unique(faces[np.asarray(component_faces, dtype=np.int32)].reshape(-1))
        component_vertices = vertices[unique_vertices]
        if component_vertices.size == 0:
            continue

        bounds_min = component_vertices.min(axis=0)
        bounds_max = component_vertices.max(axis=0)
        extents = bounds_max - bounds_min
        max_extent = max(float(np.max(extents)), 1e-6)
        flatness = float(min(extents) / max_extent)
        component_area = float(area_faces[np.asarray(component_faces, dtype=np.int32)].sum())
        area_ratio = component_area / max(total_area, 1e-6)
        face_ratio = len(component_faces) / max(len(faces), 1)
        attachment_edges = sum(attachment_counts.get(face_index, 0) for face_index in component_faces)
        z_extent = float(extents[2])
        z_max = float(bounds_max[2])
        centroid_z = float(component_vertices[:, 2].mean())

        is_low_flat_flap = (
            z_extent <= (mesh_height * (0.040 if profile.is_organic else 0.050))
            and z_max <= band_top
            and centroid_z <= center_top
            and flatness <= 0.16
            and face_ratio <= 0.035
            and area_ratio <= 0.040
            and attachment_edges <= max(6, len(component_faces) // 2)
        )

        if is_low_flat_flap:
            removable_face_mask[np.asarray(component_faces, dtype=np.int32)] = True

    if not removable_face_mask.any():
        return mesh

    keep_faces = np.flatnonzero(~removable_face_mask)
    if len(keep_faces) < 12 or len(keep_faces) >= len(faces):
        return mesh

    try:
        trimmed = mesh.submesh([keep_faces], append=True, repair=False)
    except Exception:
        return mesh
    return repair_mesh_geometry(trimmed)


def _connected_candidate_face_regions(mesh, candidate_indices: np.ndarray) -> tuple[list[list[int]], dict[int, int]]:
    candidate_list = [int(index) for index in np.asarray(candidate_indices, dtype=np.int32).tolist()]
    if not candidate_list:
        return [], {}

    candidate_set = set(candidate_list)
    adjacency_map: dict[int, set[int]] = {index: set() for index in candidate_list}
    attachment_counts: dict[int, int] = {index: 0 for index in candidate_list}

    adjacency_pairs = np.asarray(getattr(mesh, "face_adjacency", []), dtype=np.int32)
    if adjacency_pairs.ndim == 2 and adjacency_pairs.shape[1] >= 2:
        for left_raw, right_raw in adjacency_pairs[:, :2]:
            left = int(left_raw)
            right = int(right_raw)
            left_is_candidate = left in candidate_set
            right_is_candidate = right in candidate_set
            if left_is_candidate and right_is_candidate:
                adjacency_map[left].add(right)
                adjacency_map[right].add(left)
            elif left_is_candidate:
                attachment_counts[left] += 1
            elif right_is_candidate:
                attachment_counts[right] += 1

    regions: list[list[int]] = []
    visited: set[int] = set()
    for start in candidate_list:
        if start in visited:
            continue
        stack = [start]
        component_faces: list[int] = []
        while stack:
            face_index = stack.pop()
            if face_index in visited:
                continue
            visited.add(face_index)
            component_faces.append(face_index)
            stack.extend(neighbor for neighbor in adjacency_map.get(face_index, ()) if neighbor not in visited)
        regions.append(component_faces)

    return regions, attachment_counts


def prune_large_bottom_support_sheet(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh
    if not profile.is_organic:
        return mesh

    mesh = repair_mesh_geometry(mesh)
    vertices = np.asarray(getattr(mesh, "vertices", []), dtype=float)
    faces = np.asarray(getattr(mesh, "faces", []), dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        return mesh
    if faces.ndim != 2 or faces.shape[1] < 3 or len(faces) < 20:
        return mesh

    faces = faces[:, :3]
    face_vertices = vertices[faces]
    face_normals = np.asarray(getattr(mesh, "face_normals", []), dtype=float)
    if face_normals.ndim != 2 or face_normals.shape[0] != len(faces):
        return mesh

    mesh_height = max(1e-6, float(np.ptp(vertices[:, 2])))
    face_centroid_z = face_vertices[:, :, 2].mean(axis=1)
    face_z_span = np.ptp(face_vertices[:, :, 2], axis=1)
    horizontal_faces = np.abs(face_normals[:, 2]) >= 0.78
    low_faces = face_centroid_z <= (mesh_height * 0.12)
    thin_faces = face_z_span <= (mesh_height * 0.025)
    candidate_indices = np.flatnonzero(horizontal_faces & low_faces & thin_faces)
    if len(candidate_indices) < 6:
        return mesh

    regions, attachment_counts = _connected_candidate_face_regions(mesh, candidate_indices)
    if not regions:
        return mesh

    area_faces = np.asarray(getattr(mesh, "area_faces", np.zeros(len(faces), dtype=float)), dtype=float)
    total_area = float(getattr(mesh, "area", 0.0))
    if total_area <= 1e-8:
        total_area = float(area_faces.sum())

    region_infos = []
    for region_faces in regions:
        face_array = np.asarray(region_faces, dtype=np.int32)
        unique_vertices = np.unique(faces[face_array].reshape(-1))
        region_vertices = vertices[unique_vertices]
        if region_vertices.size == 0:
            continue
        bounds_min = region_vertices.min(axis=0)
        bounds_max = region_vertices.max(axis=0)
        extents = bounds_max - bounds_min
        xy_area = float(max(extents[0], 1e-6) * max(extents[1], 1e-6))
        region_area = float(area_faces[face_array].sum())
        attachment_edges = sum(attachment_counts.get(int(face_index), 0) for face_index in region_faces)
        region_infos.append(
            {
                "faces": region_faces,
                "face_count": len(region_faces),
                "region_area": region_area,
                "xy_area": xy_area,
                "extents": extents,
                "z_max": float(bounds_max[2]),
                "centroid_z": float(region_vertices[:, 2].mean()),
                "attachment_edges": attachment_edges,
            }
        )

    if len(region_infos) <= 1:
        return mesh

    compact_reference = sorted(
        (
            info["region_area"]
            for info in region_infos
            if info["xy_area"] <= (mesh_height * mesh_height * 0.028)
        )
    )
    baseline_area = compact_reference[len(compact_reference) // 2] if compact_reference else min(
        info["region_area"] for info in region_infos
    )

    removable_face_mask = np.zeros(len(faces), dtype=bool)
    for info in region_infos:
        extents = np.asarray(info["extents"], dtype=float)
        max_xy = float(max(extents[0], extents[1], 1e-6))
        min_xy = float(max(min(extents[0], extents[1]), 1e-6))
        aspect_ratio = max_xy / min_xy
        is_support_sheet = (
            info["region_area"] >= max(baseline_area * 2.2, total_area * 0.010)
            and info["xy_area"] >= (mesh_height * mesh_height * 0.028)
            and max_xy >= (mesh_height * 0.20)
            and info["z_max"] <= (mesh_height * 0.13)
            and info["centroid_z"] <= (mesh_height * 0.070)
            and aspect_ratio <= 6.5
            and info["attachment_edges"] <= max(18, info["face_count"] * 3)
        )
        if is_support_sheet:
            removable_face_mask[np.asarray(info["faces"], dtype=np.int32)] = True

    if not removable_face_mask.any():
        return mesh

    keep_faces = np.flatnonzero(~removable_face_mask)
    if len(keep_faces) < 16 or len(keep_faces) >= len(faces):
        return mesh

    try:
        trimmed = mesh.submesh([keep_faces], append=True, repair=False)
    except Exception:
        return mesh
    return repair_mesh_geometry(trimmed)


def _smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    if edge1 <= edge0:
        return np.where(values >= edge1, 1.0, 0.0)
    t = np.clip((values - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - (2.0 * t))


def shape_organic_foot_soles(mesh, profile: SubjectProfile):
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh):
        return mesh
    if not profile.is_organic:
        return mesh

    shaped = repair_mesh_geometry(mesh)
    vertices = np.asarray(getattr(shaped, "vertices", []), dtype=float)
    faces = np.asarray(getattr(shaped, "faces", []), dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        return mesh
    if faces.ndim != 2 or faces.shape[1] < 3 or len(faces) < 12:
        return mesh

    faces = faces[:, :3]
    face_vertices = vertices[faces]
    face_normals = np.asarray(getattr(shaped, "face_normals", []), dtype=float)
    if face_normals.ndim != 2 or face_normals.shape[0] != len(faces):
        return mesh

    mesh_height = max(1e-6, float(np.ptp(vertices[:, 2])))
    face_centroid_z = face_vertices[:, :, 2].mean(axis=1)
    face_z_span = np.ptp(face_vertices[:, :, 2], axis=1)
    bottomish_faces = (
        (np.abs(face_normals[:, 2]) >= 0.58)
        & (face_centroid_z <= (mesh_height * 0.12))
        & (face_z_span <= (mesh_height * 0.05))
    )
    candidate_indices = np.flatnonzero(bottomish_faces)
    if len(candidate_indices) < 2:
        return mesh

    regions, _ = _connected_candidate_face_regions(shaped, candidate_indices)
    if not regions:
        return mesh

    mutable_vertices = vertices.copy()
    changed = False

    for region_faces in regions:
        face_array = np.asarray(region_faces, dtype=np.int32)
        unique_vertices = np.unique(faces[face_array].reshape(-1))
        region_vertices = mutable_vertices[unique_vertices]
        if region_vertices.size == 0:
            continue

        bounds_min = region_vertices.min(axis=0)
        bounds_max = region_vertices.max(axis=0)
        extents = bounds_max - bounds_min
        max_xy = float(max(extents[0], extents[1], 1e-6))
        min_xy = float(max(min(extents[0], extents[1]), 1e-6))
        xy_area = float(max(extents[0], 1e-6) * max(extents[1], 1e-6))
        z_extent = float(extents[2])
        centroid_z = float(region_vertices[:, 2].mean())

        is_sole_like = (
            max_xy >= (mesh_height * 0.07)
            and max_xy <= (mesh_height * 0.78)
            and min_xy >= (mesh_height * 0.025)
            and min_xy <= (mesh_height * 0.42)
            and xy_area <= (mesh_height * mesh_height * 0.30)
            and z_extent <= (mesh_height * 0.08)
            and centroid_z <= (mesh_height * 0.16)
        )
        if not is_sole_like:
            continue

        points_xy = region_vertices[:, :2]
        center_xy = points_xy.mean(axis=0)
        centered_xy = points_xy - center_xy
        if len(centered_xy) < 3:
            continue

        try:
            covariance = np.cov(centered_xy.T)
            eigvals, eigvecs = np.linalg.eigh(covariance)
            order = np.argsort(eigvals)[::-1]
            length_axis = eigvecs[:, order[0]]
            width_axis = eigvecs[:, order[1]]
        except Exception:
            continue

        u = centered_xy @ length_axis
        v = centered_xy @ width_axis
        u_scale = max(1e-6, float(np.max(np.abs(u))))
        v_scale = max(1e-6, float(np.max(np.abs(v))))
        u_norm = u / u_scale
        v_norm = v / v_scale

        region_min_z = float(region_vertices[:, 2].min())
        bottom_band = region_min_z + (mesh_height * 0.03)
        bottom_mask = region_vertices[:, 2] <= bottom_band
        if int(bottom_mask.sum()) < 4:
            continue

        edge_profile = _smoothstep(0.38, 0.96, np.maximum(np.abs(u_norm), np.abs(v_norm)))
        toe_lift = _smoothstep(0.32, 1.0, u_norm)
        heel_lift = _smoothstep(0.40, 1.0, -u_norm)

        lift = (
            (mesh_height * 0.014) * edge_profile
            + (mesh_height * 0.010) * toe_lift
            + (mesh_height * 0.0055) * heel_lift
        )
        lift = np.clip(lift, 0.0, mesh_height * 0.024)
        lift *= bottom_mask.astype(float)

        if np.max(np.abs(lift)) <= 1e-8:
            continue

        mutable_vertices[unique_vertices, 2] += lift
        changed = True

    if not changed:
        return mesh

    shaped.vertices = mutable_vertices
    return repair_mesh_geometry(shaped)


def _cleanup_smoothing_iterations(profile: SubjectProfile, should_reduce: bool) -> int:
    if profile.is_organic:
        if profile.has_fragile_detail:
            return 0
        return 1 if should_reduce else 0
    if profile.preserve_edges:
        return 2 if should_reduce else 1
    return 4 if should_reduce else 3


def _finalize_smoothing_iterations(profile: SubjectProfile, target_faces: int | None) -> int:
    if profile.has_fragile_detail:
        return 0
    if profile.is_organic:
        return 0 if target_faces is not None else 1
    if profile.preserve_edges:
        return 1
    return 2


def finalize_mesh_for_export(
    mesh,
    cleanup_mode: str,
    target_faces: int | None,
    profile: SubjectProfile,
    guard: GeometryGuardResult | None,
):
    finalized = repair_mesh_geometry(mesh)
    finalized = prune_tiny_components(finalized, profile)
    finalized = fill_mesh_holes(finalized)
    finalized = orient_mesh_using_guard(finalized, guard)
    finalized = center_and_ground_mesh(finalized, profile)
    finalized = prune_low_detached_scraps(finalized, profile)
    finalized = prune_low_ground_flaps(finalized, profile)
    finalized = prune_large_bottom_support_sheet(finalized, profile)
    finalized = center_and_ground_mesh(finalized, profile)
    if cleanup_mode != "Off":
        final_smoothing = _finalize_smoothing_iterations(profile, target_faces)
        if final_smoothing > 0:
            finalized = smooth_mesh_for_editability(finalized, iterations=final_smoothing)
    if target_faces is not None and target_faces > 0:
        finalized = enforce_triangle_budget(finalized, target_faces, profile)
        finalized = prune_tiny_components(finalized, profile)
        finalized = prune_low_detached_scraps(finalized, profile)
        finalized = prune_low_ground_flaps(finalized, profile)
        finalized = prune_large_bottom_support_sheet(finalized, profile)
        finalized = center_and_ground_mesh(finalized, profile)
    finalized = shape_organic_foot_soles(finalized, profile)
    finalized = center_and_ground_mesh(finalized, profile)
    return repair_mesh_geometry(finalized)


def enforce_triangle_budget(mesh, target_faces: int | None, profile: SubjectProfile | None = None):
    if target_faces is None or target_faces <= 0:
        return mesh

    face_count, _ = mesh_counts(mesh)
    tolerance_ratio = 1.08 if profile is not None and profile.has_fragile_detail else 1.0
    if face_count <= int(target_faces * tolerance_ratio):
        return mesh

    candidate = mesh.copy()
    if profile is not None and profile.has_fragile_detail:
        attempts = [
            max(4, int(target_faces * 1.05)),
            max(4, int(target_faces * 1.02)),
            target_faces,
        ]
    else:
        attempts = [target_faces, max(4, int(target_faces * 0.98)), max(4, int(target_faces * 0.95))]
    for desired in attempts:
        try:
            candidate = candidate.simplify_quadric_decimation(face_count=desired)
            candidate = repair_mesh_geometry(candidate)
        except Exception:
            continue

        face_count, _ = mesh_counts(candidate)
        if face_count <= max(target_faces, int(target_faces * (1.08 if profile is not None and profile.has_fragile_detail else 1.02))):
            break

    return candidate


def _reference_ratio_penalty(
    extents: np.ndarray,
    profile: SubjectProfile,
    hints: ReferenceGeometryHints | None,
) -> tuple[float, str]:
    if hints is None or hints.confidence <= 0.0:
        return 0.0, "no reference ratio hint"

    values = [float(value) for value in np.asarray(extents, dtype=float).tolist() if float(value) > 1e-6]
    if len(values) < 3:
        return 0.0, "no stable extents"

    values.sort()
    if profile.is_vehicle:
        height = values[0]
        width = values[1]
        depth = values[2]
    else:
        height = values[2]
        width = values[1]
        depth = values[0]

    if height <= 1e-6:
        return 0.0, "no stable extents"

    actual_width_ratio = width / height
    actual_depth_ratio = depth / height

    penalty = 0.0
    notes: list[str] = []

    if hints.width_to_height is not None:
        gap = abs(actual_width_ratio - hints.width_to_height) / max(hints.width_to_height, 0.18)
        penalty += gap * (1.35 if profile.is_vehicle else 0.95) * hints.confidence
        notes.append(f"front {actual_width_ratio:.2f}/{hints.width_to_height:.2f}")
    elif hints.generic_width_to_height is not None:
        gap = abs(actual_width_ratio - hints.generic_width_to_height) / max(hints.generic_width_to_height, 0.18)
        penalty += gap * 0.45 * hints.confidence
        notes.append(f"silhouette {actual_width_ratio:.2f}/{hints.generic_width_to_height:.2f}")

    if hints.depth_to_height is not None:
        gap = abs(actual_depth_ratio - hints.depth_to_height) / max(hints.depth_to_height, 0.18)
        penalty += gap * (1.55 if profile.is_vehicle else 0.80) * hints.confidence
        notes.append(f"side {actual_depth_ratio:.2f}/{hints.depth_to_height:.2f}")

    if penalty <= 0.01:
        return 0.0, "reference ratios matched well"
    return penalty, "ratio " + " | ".join(notes)


def _count_low_detached_scraps(components: list, profile: SubjectProfile) -> int:
    if len(components) <= 1:
        return 0

    ranked = sorted(
        (
            (
                len(getattr(component, "faces", [])),
                float(getattr(component, "area", 0.0)),
                component,
            )
            for component in components
        ),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    main_faces, main_area, main_component = ranked[0]
    main_bounds = np.asarray(main_component.bounds, dtype=float)
    main_height = max(1e-6, float(main_component.extents[2]))
    total_faces = sum(item[0] for item in ranked)
    total_area = sum(item[1] for item in ranked)

    suspicious_count = 0
    for face_count, area, component in ranked[1:]:
        bounds = np.asarray(component.bounds, dtype=float)
        extents = np.asarray(component.extents, dtype=float)
        face_ratio = face_count / max(total_faces, 1)
        area_ratio = area / max(total_area, 1e-6)
        relative_face_ratio = face_count / max(main_faces, 1)
        relative_area_ratio = area / max(main_area, 1e-6)
        if _is_suspicious_low_component(
            bounds=bounds,
            extents=extents,
            face_ratio=face_ratio,
            area_ratio=area_ratio,
            relative_face_ratio=relative_face_ratio,
            relative_area_ratio=relative_area_ratio,
            main_bounds=main_bounds,
            main_height=main_height,
            profile=profile,
        ):
            suspicious_count += 1

    return suspicious_count


def mesh_quality_score(
    mesh,
    target_faces: int | None,
    profile: SubjectProfile,
    reference_hints: ReferenceGeometryHints | None = None,
    geometry_reference: GeometryGuardReference | None = None,
) -> tuple[float, str, GeometryGuardResult]:
    face_count, _ = mesh_counts(mesh)
    if face_count <= 0:
        return -9999.0, "empty mesh", GeometryGuardResult(score_adjustment=-1.0, needs_retry=True, note="geometry guard: empty mesh")

    try:
        components = list(mesh.split(only_watertight=False))
    except Exception:
        components = [mesh]

    component_count = max(1, len(components))
    largest_component_faces = max(len(getattr(component, "faces", [])) for component in components)
    largest_ratio = largest_component_faces / max(1, face_count)

    extents = np.asarray(getattr(mesh, "extents", [1.0, 1.0, 1.0]), dtype=float)
    max_extent = float(extents.max()) if extents.size else 1.0
    min_extent = float(extents.min()) if extents.size else 1.0
    thin_ratio = min_extent / max(max_extent, 1e-6)

    bbox_area = 2.0 * (
        (extents[0] * extents[1])
        + (extents[0] * extents[2])
        + (extents[1] * extents[2])
    ) if extents.size >= 3 else 1.0
    area_ratio = float(getattr(mesh, "area", 0.0)) / max(bbox_area, 1e-6)

    score = largest_ratio * 4.2
    score -= max(0, component_count - 1) * 0.55
    score -= max(0.0, 0.04 - thin_ratio) * 14.0
    score -= max(0.0, area_ratio - 4.2) * 0.18

    if target_faces:
        score -= min(2.0, abs(face_count - target_faces) / max(target_faces, 1) * 1.8)

    suspicious_low_scraps = _count_low_detached_scraps(components, profile)
    if suspicious_low_scraps:
        score -= suspicious_low_scraps * 1.05

    if profile.is_vehicle:
        score -= max(0, component_count - 1) * 0.55
        score -= max(0.0, 0.12 - thin_ratio) * 12.0
        if largest_ratio >= 0.95:
            score += 0.45

    if profile.is_hard_surface:
        score -= max(0, component_count - 1) * 0.35
        score -= max(0.0, 0.08 - thin_ratio) * 10.0
        if largest_ratio >= 0.92:
            score += 0.30

    if profile.is_transparent:
        score -= max(0, component_count - 1) * 0.45

    if getattr(mesh, "is_watertight", False):
        score += 0.25

    ratio_penalty, ratio_note = _reference_ratio_penalty(extents, profile, reference_hints)
    score -= ratio_penalty
    geometry_guard = review_mesh_against_reference(mesh, geometry_reference, profile)
    score += geometry_guard.score_adjustment

    note = (
        f"score {score:.2f} | parts {component_count} | "
        f"main-part {largest_ratio:.0%} | tris {face_count:,}"
    )
    if suspicious_low_scraps:
        note += f" | low scraps {suspicious_low_scraps}"
    if ratio_note:
        note += f" | {ratio_note}"
    if geometry_guard.note:
        note += f" | {geometry_guard.note}"
    return score, note, geometry_guard


def cleanup_mesh(mesh, cleanup_mode: str, target_faces: int | None, profile: SubjectProfile):
    if cleanup_mode not in CLEANUP_OPTIONS:
        raise ValueError(f"Unsupported cleanup mode: {cleanup_mode}")

    should_clean = cleanup_mode != "Off"
    should_reduce = target_faces is not None and target_faces > 0

    if should_clean or should_reduce:
        floater_remove, degenerate_remove, reducer = get_cleanup_workers()

    if should_clean:
        mesh = floater_remove(mesh)
        mesh = degenerate_remove(mesh)
        mesh = prune_tiny_components(mesh, profile)
        mesh = prune_low_detached_scraps(mesh, profile)
        mesh = prune_low_ground_flaps(mesh, profile)
        mesh = prune_large_bottom_support_sheet(mesh, profile)
        mesh = fill_mesh_holes(mesh)

        if should_reduce:
            mesh = reducer(mesh, max_facenum=target_faces)

    mesh = repair_mesh_geometry(mesh)

    if should_clean:
        smoothing_iterations = _cleanup_smoothing_iterations(profile, should_reduce)
        if smoothing_iterations > 0:
            mesh = smooth_mesh_for_editability(mesh, iterations=smoothing_iterations)

    if should_reduce:
        mesh = enforce_triangle_budget(mesh, target_faces, profile)
        mesh = prune_tiny_components(mesh, profile)
        mesh = prune_low_detached_scraps(mesh, profile)
        mesh = prune_low_ground_flaps(mesh, profile)
        mesh = prune_large_bottom_support_sheet(mesh, profile)

    return repair_mesh_geometry(mesh)


def mesh_counts(mesh) -> tuple[int, int]:
    faces = getattr(mesh, "faces", None)
    vertices = getattr(mesh, "vertices", None)
    face_count = len(faces) if faces is not None else 0
    vertex_count = len(vertices) if vertices is not None else 0
    return face_count, vertex_count


def _preview_path_for_output(output_path: Path) -> Path:
    cleanup_generated_caches()
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return PREVIEW_CACHE_DIR / f"{output_path.stem}_preview.png"


def _preview_is_meaningful(image: Image.Image) -> bool:
    rgb = image.convert("RGB")
    stat = ImageStat.Stat(rgb)
    if max(stat.stddev) < 1.5:
        return False
    extrema = stat.extrema
    channel_ranges = [high - low for low, high in extrema]
    return max(channel_ranges) >= 4


def _rotation_matrix_xyz(x_deg: float, y_deg: float, z_deg: float) -> np.ndarray:
    x = np.deg2rad(x_deg)
    y = np.deg2rad(y_deg)
    z = np.deg2rad(z_deg)

    rx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, np.cos(x), -np.sin(x)],
            [0.0, np.sin(x), np.cos(x)],
        ],
        dtype=float,
    )
    ry = np.array(
        [
            [np.cos(y), 0.0, np.sin(y)],
            [0.0, 1.0, 0.0],
            [-np.sin(y), 0.0, np.cos(y)],
        ],
        dtype=float,
    )
    rz = np.array(
        [
            [np.cos(z), -np.sin(z), 0.0],
            [np.sin(z), np.cos(z), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    return rz @ ry @ rx


def load_preview_mesh(mesh_path: Path, max_faces: int = 42000):
    import trimesh

    mesh_path = Path(mesh_path)
    with mesh_path.open("rb") as handle:
        loaded = trimesh.load(handle, file_type=mesh_path.suffix.lstrip(".").lower())

    if isinstance(loaded, trimesh.Scene):
        scene_meshes = [
            geometry.copy()
            for geometry in loaded.geometry.values()
            if isinstance(geometry, trimesh.Trimesh) and len(getattr(geometry, "faces", []))
        ]
        if not scene_meshes:
            return None
        preview_mesh = trimesh.util.concatenate(scene_meshes)
    else:
        preview_mesh = loaded

    preview_mesh = repair_mesh_geometry(preview_mesh)
    faces = np.asarray(getattr(preview_mesh, "faces", []), dtype=np.int32)
    if faces.ndim == 2 and len(faces) > max_faces:
        try:
            simplified = preview_mesh.simplify_quadric_decimation(face_count=max_faces)
            preview_mesh = repair_mesh_geometry(simplified)
        except Exception:
            pass
    return preview_mesh


def _render_mesh_preview_software_image(
    mesh,
    *,
    pitch_deg: float = -24.0,
    yaw_deg: float = 38.0,
    resolution: int = 640,
    max_preview_faces: int = 220000,
) -> Image.Image | None:
    vertices = np.asarray(getattr(mesh, "vertices", []), dtype=float)
    faces = np.asarray(getattr(mesh, "faces", []), dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        return None
    if faces.ndim != 2 or faces.shape[1] < 3:
        return None

    faces = faces[:, :3]
    if len(faces) == 0:
        return None

    max_preview_faces = max(8000, int(max_preview_faces))
    if len(faces) > max_preview_faces:
        # Sparse face sampling makes solid meshes look like point clouds.
        # Prefer a simplified preview mesh that still preserves surface coverage.
        try:
            preview_mesh = mesh.simplify_quadric_decimation(
                face_count=max(12000, min(max_preview_faces, max(len(faces) // 3, max_preview_faces // 2)))
            )
            preview_mesh = repair_mesh_geometry(preview_mesh)
            preview_vertices = np.asarray(getattr(preview_mesh, "vertices", []), dtype=float)
            preview_faces = np.asarray(getattr(preview_mesh, "faces", []), dtype=np.int32)
            if (
                preview_vertices.ndim == 2
                and preview_vertices.shape[1] == 3
                and preview_faces.ndim == 2
                and preview_faces.shape[1] >= 3
                and len(preview_faces) > 0
            ):
                vertices = preview_vertices
                faces = preview_faces[:, :3]
        except Exception:
            pass

    if len(faces) > max_preview_faces:
        # Last-resort cap for extremely dense meshes if simplification is unavailable.
        stride = max(1, int(np.ceil(len(faces) / max_preview_faces)))
        faces = faces[::stride]

    verts = vertices.astype(float, copy=True)
    center = np.median(verts, axis=0)
    verts -= center
    extent = np.ptp(verts, axis=0)
    max_extent = float(np.max(extent))
    if max_extent <= 1e-9:
        return None
    verts /= max_extent

    rotation = _rotation_matrix_xyz(float(pitch_deg), 0.0, float(yaw_deg))
    rotated = verts @ rotation.T

    denom = 2.8 - rotated[:, 2]
    denom = np.clip(denom, 0.65, None)
    projected = rotated[:, :2] / denom[:, None]
    if not np.isfinite(projected).all():
        return None

    min_xy = projected.min(axis=0)
    max_xy = projected.max(axis=0)
    span = np.maximum(max_xy - min_xy, 1e-6)

    work_size = 960
    margin = 90
    scale = min((work_size - margin * 2) / span[0], (work_size - margin * 2) / span[1])
    points_2d = np.empty((len(projected), 2), dtype=float)
    points_2d[:, 0] = (projected[:, 0] - min_xy[0]) * scale + margin
    points_2d[:, 1] = (max_xy[1] - projected[:, 1]) * scale + margin

    tris_3d = rotated[faces]
    tris_2d = points_2d[faces]
    edges_a = tris_3d[:, 1] - tris_3d[:, 0]
    edges_b = tris_3d[:, 2] - tris_3d[:, 0]
    normals = np.cross(edges_a, edges_b)
    normal_length = np.linalg.norm(normals, axis=1)
    valid = normal_length > 1e-9
    if not np.any(valid):
        return None

    tris_3d = tris_3d[valid]
    tris_2d = tris_2d[valid]
    normals = normals[valid] / normal_length[valid][:, None]

    finite_mask = np.isfinite(tris_2d).all(axis=(1, 2))
    if not np.any(finite_mask):
        return None
    tris_3d = tris_3d[finite_mask]
    tris_2d = tris_2d[finite_mask]
    normals = normals[finite_mask]

    depth = tris_3d[:, :, 2].mean(axis=1)
    order = np.argsort(depth)
    light_dir = np.array([0.45, -0.35, 0.82], dtype=float)
    light_dir /= np.linalg.norm(light_dir)
    lighting = np.clip(normals @ light_dir, 0.0, 1.0)
    lighting = 0.28 + (lighting * 0.72)

    canvas = Image.new("RGBA", (work_size, work_size), (16, 24, 35, 255))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")

    all_x = points_2d[:, 0]
    all_y = points_2d[:, 1]
    x0 = max(30, int(np.min(all_x)) - 20)
    x1 = min(work_size - 30, int(np.max(all_x)) + 20)
    y_mid = min(work_size - 60, int(np.max(all_y)) + 28)
    shadow_draw.ellipse((x0, y_mid - 28, x1, y_mid + 22), fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=20))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas, "RGBA")
    for face_index in order:
        polygon = [tuple(point) for point in tris_2d[face_index]]
        shade = float(lighting[face_index])
        base_r = int(120 + (90 * shade))
        base_g = int(134 + (92 * shade))
        base_b = int(154 + (96 * shade))
        fill = (min(255, base_r), min(255, base_g), min(255, base_b), 255)
        draw.polygon(polygon, fill=fill)

    final_image = canvas.resize((int(resolution), int(resolution)), Image.Resampling.LANCZOS).convert("RGBA")
    if not _preview_is_meaningful(final_image):
        return None
    return final_image


def render_mesh_preview_image(
    mesh,
    *,
    pitch_deg: float = -24.0,
    yaw_deg: float = 38.0,
    resolution: int = 640,
    interactive: bool = False,
) -> Image.Image | None:
    face_cap = 42000 if interactive else 220000
    return _render_mesh_preview_software_image(
        mesh,
        pitch_deg=pitch_deg,
        yaw_deg=yaw_deg,
        resolution=resolution,
        max_preview_faces=face_cap,
    )


def _render_mesh_preview_software(mesh, preview_path: Path) -> Path | None:
    final_image = render_mesh_preview_image(mesh, pitch_deg=-24.0, yaw_deg=38.0, resolution=640, interactive=False)
    if final_image is None:
        return None
    final_image.save(preview_path)
    return preview_path


def _render_mesh_preview_opengl(mesh, preview_path: Path) -> Path | None:
    import trimesh

    preview_mesh = mesh.copy()
    if isinstance(preview_mesh, trimesh.Scene):
        preview_mesh = preview_mesh.dump(concatenate=True)
    preview_mesh = repair_mesh_geometry(preview_mesh)

    try:
        colors = np.tile(np.array([[201, 214, 230, 255]], dtype=np.uint8), (len(preview_mesh.faces), 1))
        preview_mesh.visual.face_colors = colors
    except Exception:
        pass

    scene = trimesh.Scene(preview_mesh)
    extent = float(np.max(preview_mesh.extents)) if len(preview_mesh.extents) else 1.0
    distance = max(2.0, extent * 2.8)
    scene.set_camera(
        angles=(np.deg2rad(62), 0.0, np.deg2rad(42)),
        distance=distance,
        center=preview_mesh.bounding_box.centroid,
        resolution=(640, 640),
        fov=(42, 42),
    )
    image_bytes = scene.save_image(resolution=(640, 640), visible=False)
    if not image_bytes:
        return None
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    if not _preview_is_meaningful(image):
        return None
    image.save(preview_path)
    return preview_path


def render_mesh_preview(mesh, output_path: Path) -> Path | None:
    preview_path = _preview_path_for_output(output_path)

    try:
        software_preview = _render_mesh_preview_software(mesh, preview_path)
        if software_preview is not None:
            return software_preview
    except Exception:
        pass

    try:
        return _render_mesh_preview_opengl(mesh, preview_path)
    except Exception:
        return None


def run_sample_with_retries(
    pipeline,
    image_input,
    scan_plan: dict[str, float | int | str],
    options: GenerationOptions,
    sample_index: int,
    sample_seed: int,
    torch,
    report: Callable[[int, str], None],
    progress_value: int,
):
    runtime_attempts = build_runtime_attempts(scan_plan, options)
    last_error: BaseException | None = None

    for attempt_index, runtime in enumerate(runtime_attempts, start=1):
        try:
            pipeline.image_processor.border_ratio = float(runtime["border_ratio"])
            generator = torch.manual_seed(sample_seed)
            with torch.inference_mode():
                mesh = pipeline(
                    image=clone_image_input(image_input),
                    num_inference_steps=int(runtime["steps"]),
                    guidance_scale=float(runtime["guidance_scale"]),
                    octree_resolution=int(runtime["octree_resolution"]),
                    num_chunks=int(runtime["num_chunks"]),
                    generator=generator,
                    output_type="trimesh",
                )[0]

            runtime_note = (
                f"{runtime['label']} | {str(runtime.get('scan_note', '')).strip()} | "
                f"steps {int(runtime['steps'])} | "
                f"guide {float(runtime['guidance_scale']):.2f} | "
                f"octree {int(runtime['octree_resolution'])} | "
                f"chunks {int(runtime['num_chunks'])} | "
                f"border {float(runtime['border_ratio']):.3f}"
            )
            return mesh, runtime_note
        except RuntimeError as exc:
            last_error = exc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            if not is_memory_error(exc) or attempt_index >= len(runtime_attempts):
                raise

            report(
                progress_value,
                (
                    f"Memory got tight on sample {sample_index + 1}. "
                    f"Retrying slower with safer settings ({runtime_attempts[attempt_index]['label']})."
                ),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("Sample generation failed before a retry profile could run.")


def generate_mesh(
    selected_images: Iterable[SelectedImage],
    options: GenerationOptions,
    progress_callback: Callable[[int, str], None] | None = None,
) -> GenerationResult:
    selected_images = list(selected_images)
    if not selected_images:
        raise ValueError("No images were selected.")
    cleanup_generated_caches()

    def report(progress: int, message: str):
        if progress_callback is not None:
            progress_callback(progress, message)

    preset = QUALITY_PRESETS.get(options.quality_name)
    if preset is None:
        raise ValueError(f"Unknown quality preset: {options.quality_name}")

    ensure_runtime()
    torch = RUNTIME["torch"]

    sample_count = normalize_sample_count(options.sample_count)
    options.soft_ram_limit_percent = normalize_percent_limit(options.soft_ram_limit_percent, 82)
    options.soft_vram_limit_percent = normalize_percent_limit(options.soft_vram_limit_percent, 84)
    detail_focus_terms = build_detail_focus_terms(selected_images)
    enriched_subject_notes = " ".join(part for part in (options.subject_notes, " ".join(detail_focus_terms)) if part).strip()
    subject_profile = build_subject_profile(options.subject_type, options.subject_name, enriched_subject_notes)

    report(8, "Preparing reference images...")
    image_input, detail_references, summary = resolve_image_input(selected_images, options.remove_background, preset, subject_profile)
    reference_hints = build_reference_geometry_hints(image_input, subject_profile)
    geometry_reference = build_geometry_guard_reference(image_input, subject_profile)
    multiview = isinstance(image_input, dict)
    report(20, "Reference images prepared.")
    report(28, "Loading Hunyuan pipeline...")
    pipeline = get_pipeline(multiview, border_ratio=preset.border_ratio)
    target_triangles = resolve_triangle_target(options, preset)
    rescue_sample_cap = compute_geometry_rescue_cap(sample_count, subject_profile, geometry_reference, len(detail_references))
    layered_scan_plan = build_layered_scan_plan(rescue_sample_cap, preset, options, subject_profile)

    best_mesh = None
    best_seed = None
    best_score = -9999.0
    best_index = 1
    best_guard: GeometryGuardResult | None = None
    sample_notes: list[str] = []
    runtime_notes: list[str] = []
    extra_retry_count = 0

    if sample_count <= 1:
        start_note = "Starting AI generation with 1 all-round scan..."
    else:
        start_note = f"Starting layered AI generation with {sample_count} scan stage(s)..."
    if rescue_sample_cap > sample_count:
        start_note += f" Geometry guard can expand to {rescue_sample_cap} total stages if proportions drift."
    report(34, start_note)

    sample_total = sample_count
    sample_index = 0
    while sample_index < sample_total:
        sample_seed = random.randint(0, 10_000_000)
        active_scan = layered_scan_plan[min(sample_index, len(layered_scan_plan) - 1)]
        active_image_input = build_scan_image_input(image_input, detail_references, preset, active_scan, subject_profile)
        sample_start = 36 + int((sample_index / rescue_sample_cap) * 34)
        sample_end = 36 + int(((sample_index + 1) / rescue_sample_cap) * 34)

        report(
            sample_start,
            f"Generating scan {sample_index + 1}/{sample_total}: {active_scan['label']}...",
        )
        sample_mesh, runtime_note = run_sample_with_retries(
            pipeline=pipeline,
            image_input=active_image_input,
            scan_plan=active_scan,
            options=options,
            sample_index=sample_index,
            sample_seed=sample_seed,
            torch=torch,
            report=report,
            progress_value=max(sample_start, sample_end - 2),
        )

        reviewed_mesh = repair_mesh_geometry(sample_mesh)
        score, note, guard = mesh_quality_score(
            reviewed_mesh,
            target_triangles,
            subject_profile,
            reference_hints,
            geometry_reference,
        )
        sample_notes.append(
            f"Scan {sample_index + 1}: {active_scan['label']} | seed {sample_seed} | {runtime_note} | {note}"
        )
        runtime_notes.append(f"Scan {sample_index + 1}: {runtime_note}")
        report(sample_end, f"Reviewed scan {sample_index + 1}/{sample_total}: {note}")

        if score > best_score:
            best_score = score
            best_mesh = sample_mesh
            best_seed = sample_seed
            best_index = sample_index + 1
            best_guard = guard

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if (
            best_guard is not None
            and best_guard.needs_retry
            and (sample_index + 1) >= sample_total
            and sample_total < rescue_sample_cap
        ):
            sample_total += 1
            extra_retry_count += 1
            report(
                min(72, sample_end + 1),
                f"Geometry guard asked for one more rescue scan ({sample_total}/{rescue_sample_cap}) to reduce shape drift.",
            )

        sample_index += 1

    if best_mesh is None or best_seed is None:
        raise RuntimeError("The generator did not produce a usable mesh.")

    actual_samples_ran = len(sample_notes)
    report(74, f"Selected sample {best_index}/{actual_samples_ran} as the cleanest result.")
    report(84, "Cleaning geometry and smoothing for easier editing...")
    raw_output_path = None
    if options.keep_raw_copy:
        raw_output_path = build_output_path(options.output_name, "raw")
        best_mesh.export(raw_output_path)

    final_mesh = cleanup_mesh(best_mesh, options.cleanup_mode, target_faces=target_triangles, profile=subject_profile)
    final_guard = review_mesh_against_reference(final_mesh, geometry_reference, subject_profile)
    final_mesh = finalize_mesh_for_export(
        final_mesh,
        cleanup_mode=options.cleanup_mode,
        target_faces=target_triangles,
        profile=subject_profile,
        guard=final_guard if final_guard.matched_views else best_guard,
    )
    report(94, "Exporting final mesh...")
    output_path = build_output_path(options.output_name)
    final_mesh.export(output_path)
    preview_image_path = render_mesh_preview(final_mesh, output_path)

    face_count, vertex_count = mesh_counts(final_mesh)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    report(100, "Mesh finished.")
    return GenerationResult(
        output_path=output_path,
        raw_output_path=raw_output_path,
        preview_image_path=preview_image_path,
        used_input_summary=summary,
        quality_name=preset.label,
        cleanup_mode=options.cleanup_mode,
        target_triangles=target_triangles,
        seed=best_seed,
        samples_ran=actual_samples_ran,
        face_count=face_count,
        vertex_count=vertex_count,
        selected_sample_index=best_index,
        sample_review_note=" | ".join(sample_notes),
        runtime_profile_note=" | ".join(runtime_notes),
        subject_profile_note=(
            f"{subject_profile.label} | {reference_hints.note} | {geometry_reference.note} | final {final_guard.note}"
            if reference_hints.note or geometry_reference.note
            else subject_profile.label
        ),
        note=(
            f"{preset.note} "
            "Input prep now preserves up to 4K source size, upscales weak small images, falls back when background removal looks suspicious, "
            "and the runtime retries with safer chunking before giving up when memory gets tight. "
            "Layered scanning now moves from broader shape checks toward tighter detail-focused passes as sample count rises, "
            "while thin-detail rescue tightens framing and edge emphasis for fingers, cloth tears, straps, capes, faces, and shoes when your notes imply those weak spots. "
            "Focused detail crops now carry body-part tags and use a stronger late-pass edge guide for weak zones instead of staying generic. "
            "Geometry guard now scores front/side silhouette match, proportions, and symmetry before choosing the best sample, "
            "then export finalization prunes tiny junk pieces, fills small holes, orients the mesh upright, centers it near origin, grounds it for easier Blender import, "
            "and applies a stricter final decimation pass for cleaner Blender/game shading. "
            f"Geometry rescue samples used: {extra_retry_count}. "
            f"Assist profile used: {subject_profile.label}."
        ),
    )
