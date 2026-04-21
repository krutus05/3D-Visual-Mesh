from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .config import (
    ASSET_GOAL_PRESETS,
    ASSIST_SUBJECT_TYPES,
    CLEANUP_OPTIONS,
    DEFAULT_MENTOR_AUTO_SAVE,
    DEFAULT_MENTOR_MODEL,
    DEFAULT_MENTOR_REASONING_EFFORT,
    DEFAULT_MENTOR_TIMEOUT_SECONDS,
    DEFAULT_MENTOR_USE_WEB_SEARCH,
    MAX_SAMPLE_COUNT,
    MAX_TRIANGLE_BUDGET,
    MENTOR_CASES_DIR,
    MENTOR_REASONING_OPTIONS,
    MESH_STYLE_PRESETS,
    MIN_SAMPLE_COUNT,
    MIN_TRIANGLE_BUDGET,
    OPENAI_RESPONSES_URL,
    QUALITY_PRESETS,
)
from .generation import SelectedImage, sanitize_name


MENTOR_VIEW_ENUM = ["Front", "Left", "Back", "Right"]
MENTOR_SEARCH_LIMIT = 4
MENTOR_IMAGE_MAX_SIDE = 1280


@dataclass(frozen=True)
class MentorSettings:
    api_key: str
    model: str = DEFAULT_MENTOR_MODEL
    reasoning_effort: str = DEFAULT_MENTOR_REASONING_EFFORT
    timeout_seconds: int = DEFAULT_MENTOR_TIMEOUT_SECONDS
    use_web_search: bool = DEFAULT_MENTOR_USE_WEB_SEARCH
    auto_save_case: bool = DEFAULT_MENTOR_AUTO_SAVE


@dataclass(frozen=True)
class MentorContext:
    selected_images: tuple[SelectedImage, ...]
    subject_type: str
    subject_name: str
    subject_notes: str
    backend_name: str
    quality_name: str
    cleanup_mode: str
    sample_count: int
    asset_goal: str
    mesh_style: str
    max_triangles: int | None
    detail_label: str
    detail_scale: float


@dataclass
class MentorAdvice:
    subject_type: str
    subject_name_guess: str
    generation_profile: str
    recommended_quality: str
    recommended_samples: int
    recommended_asset_goal: str
    recommended_mesh_style: str
    recommended_cleanup: str
    recommended_remove_background: bool
    triangle_target: int
    missing_views: tuple[str, ...]
    geometry_risks: tuple[str, ...]
    search_terms: tuple[str, ...]
    teaching_note: str
    apply_now_summary: str
    used_web_search: bool = False
    sources: tuple[str, ...] = ()
    response_id: str = ""
    raw_payload: dict[str, Any] | None = None


def build_mentor_signature(context: MentorContext) -> str:
    payload = {
        "images": [
            {
                "path": str(item.path),
                "mtime_ns": item.path.stat().st_mtime_ns if item.path.exists() else 0,
                "view": item.view_value,
                "detail_target": item.detail_target,
            }
            for item in context.selected_images
        ],
        "subject_type": context.subject_type,
        "subject_name": context.subject_name,
        "subject_notes": context.subject_notes,
        "backend_name": context.backend_name,
        "quality_name": context.quality_name,
        "cleanup_mode": context.cleanup_mode,
        "sample_count": context.sample_count,
        "asset_goal": context.asset_goal,
        "mesh_style": context.mesh_style,
        "max_triangles": context.max_triangles,
        "detail_label": context.detail_label,
        "detail_scale": round(context.detail_scale, 4),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _mentor_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subject_type": {
                "type": "string",
                "enum": ASSIST_SUBJECT_TYPES,
            },
            "subject_name_guess": {"type": "string"},
            "generation_profile": {
                "type": "string",
                "enum": ["general", "vehicle", "hard_surface", "glass", "character", "product"],
            },
            "recommended_quality": {
                "type": "string",
                "enum": list(QUALITY_PRESETS.keys()),
            },
            "recommended_samples": {
                "type": "integer",
                "minimum": MIN_SAMPLE_COUNT,
                "maximum": MAX_SAMPLE_COUNT,
            },
            "recommended_asset_goal": {
                "type": "string",
                "enum": list(ASSET_GOAL_PRESETS.keys()),
            },
            "recommended_mesh_style": {
                "type": "string",
                "enum": list(MESH_STYLE_PRESETS.keys()),
            },
            "recommended_cleanup": {
                "type": "string",
                "enum": CLEANUP_OPTIONS,
            },
            "recommended_remove_background": {"type": "boolean"},
            "triangle_target": {
                "type": "integer",
                "minimum": MIN_TRIANGLE_BUDGET,
                "maximum": MAX_TRIANGLE_BUDGET,
            },
            "missing_views": {
                "type": "array",
                "items": {"type": "string", "enum": MENTOR_VIEW_ENUM},
            },
            "geometry_risks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "search_terms": {
                "type": "array",
                "items": {"type": "string"},
            },
            "teaching_note": {"type": "string"},
            "apply_now_summary": {"type": "string"},
        },
        "required": [
            "subject_type",
            "subject_name_guess",
            "generation_profile",
            "recommended_quality",
            "recommended_samples",
            "recommended_asset_goal",
            "recommended_mesh_style",
            "recommended_cleanup",
            "recommended_remove_background",
            "triangle_target",
            "missing_views",
            "geometry_risks",
            "search_terms",
            "teaching_note",
            "apply_now_summary",
        ],
    }


def _context_payload(context: MentorContext) -> dict[str, Any]:
    labeled_views = [
        item.view_value
        for item in context.selected_images
        if (item.view_value or "").strip() and (item.view_value or "").strip().lower() not in {"auto", "ignore"}
    ]
    auto_views = sum(1 for item in context.selected_images if (item.view_value or "Auto").strip().lower() == "auto")
    return {
        "subject_type": context.subject_type,
        "subject_name": context.subject_name,
        "subject_notes": context.subject_notes,
        "backend_name": context.backend_name,
        "quality_name": context.quality_name,
        "cleanup_mode": context.cleanup_mode,
        "sample_count": context.sample_count,
        "asset_goal": context.asset_goal,
        "mesh_style": context.mesh_style,
        "max_triangles": context.max_triangles,
        "image_detail": {
            "label": context.detail_label,
            "scale": round(context.detail_scale, 3),
        },
        "reference_coverage": {
            "image_count": len(context.selected_images),
            "labeled_views": labeled_views,
            "auto_view_count": auto_views,
        },
        "references": [
            {
                "filename": item.path.name,
                "view": item.view_value,
                "detail_target": item.detail_target,
            }
            for item in context.selected_images
        ],
    }


def _mentor_instructions() -> str:
    return (
        "You are 3DVisual Mesh Mentor, a practical teacher AI for an image-to-mesh Windows app. "
        "You help choose safer mesh-generation settings, missing reference directions, and cleanup guidance. "
        "You are the GPT mentor in a stack where a TRELLIS specialist may later act as a second-opinion shape critic, but Hunyuan stays the main local Windows AMD builder. "
        "Return JSON only. Do not explain outside the schema. "
        "Be direct, practical, and conservative. "
        "Focus on generation quality, geometry risks, missing views, triangle budget, and build settings. "
        "Cross-check proportion, part placement, and silhouette consistency across every provided image. "
        "If the references are weak, missing, duplicated, cropped badly, or conflict with each other, say so clearly in geometry_risks and teaching_note instead of pretending they are enough. "
        "Never use a higher triangle count as a fake fix for weak references or missing directions. "
        "If TRELLIS specialist use would help, describe that need in teaching_note or geometry_risks rather than pretending it already ran. "
        "For vehicles and other hard-surface objects, prioritize wheelbase, wheel placement, roofline, glass shape, side profile, and rear proportions. "
        "For character sheets or orthographic concept art, prioritize front/side/back consistency, limb width, cape or cloth silhouette, and symmetry risks. "
        "For cups, bottles, and simple glass props, keep the triangle target realistic for the object size instead of always pushing it high. "
        "If web search is available, only use it when the subject name or notes clearly point to a real model, product, or vehicle that benefits from reference lookup. "
        "Prefer settings that actually help a local Windows workflow rather than unrealistic promises."
    )


def _image_to_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    with Image.open(path) as source:
        image = source.convert("RGB")
        if max(image.size) > MENTOR_IMAGE_MAX_SIDE:
            image.thumbnail((MENTOR_IMAGE_MAX_SIDE, MENTOR_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        save_format = "PNG" if mime_type.endswith("png") else "JPEG"
        image.save(buffer, format=save_format, quality=92)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        normalized_mime = "image/png" if save_format == "PNG" else "image/jpeg"
        return f"data:{normalized_mime};base64,{encoded}"


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise RuntimeError(content.get("refusal") or "The mentor model refused this request.")
            if content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    if parts:
        return "\n".join(parts)
    raise RuntimeError("Mentor response did not include structured text output.")


def _extract_web_sources(payload: dict[str, Any]) -> tuple[str, ...]:
    collected: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            title = node.get("title")
            url = node.get("url")
            if isinstance(url, str) and url.strip():
                label = url.strip()
                if isinstance(title, str) and title.strip():
                    label = f"{title.strip()} - {label}"
                if label not in collected:
                    collected.append(label)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload.get("output", []))
    return tuple(collected[:6])


def _uses_gpt5_reasoning(model_name: str) -> bool:
    normalized = (model_name or "").strip().lower()
    return normalized.startswith("gpt-5")


def request_mentor_advice(context: MentorContext, settings: MentorSettings) -> MentorAdvice:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Analyze these references for image-to-mesh generation. "
                "Use the schema to return practical build advice for 3DVisual Mesh.\n\n"
                f"Job JSON:\n{json.dumps(_context_payload(context), indent=2)}"
            ),
        }
    ]

    for index, item in enumerate(context.selected_images, start=1):
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"Reference {index}: filename={item.path.name}, declared_view={item.view_value}, "
                    f"detail_target={item.detail_target}"
                ),
            }
        )
        content.append(
            {
                "type": "input_image",
                "image_url": _image_to_data_url(item.path),
                "detail": "high",
            }
        )

    body: dict[str, Any] = {
        "model": settings.model,
        "instructions": _mentor_instructions(),
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "3dvisual_mesh_mentor",
                "description": "Structured mentor advice for an image-to-mesh build.",
                "strict": True,
                "schema": _mentor_schema(),
            }
        },
        "max_output_tokens": 1100,
    }
    reasoning_effort = (settings.reasoning_effort or "").strip().lower()
    if reasoning_effort and reasoning_effort not in MENTOR_REASONING_OPTIONS:
        reasoning_effort = DEFAULT_MENTOR_REASONING_EFFORT
    if _uses_gpt5_reasoning(settings.model):
        body["reasoning"] = {"effort": reasoning_effort or DEFAULT_MENTOR_REASONING_EFFORT}
        if reasoning_effort in {"", "none"}:
            body["temperature"] = 0.1
    else:
        body["temperature"] = 0.2
    if settings.use_web_search:
        body["tools"] = [{"type": "web_search"}]
        body["include"] = ["web_search_call.action.sources"]

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mentor API returned HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Mentor API could not be reached: {exc.reason}") from exc

    parsed = json.loads(_extract_output_text(raw_payload))
    advice = MentorAdvice(
        subject_type=str(parsed["subject_type"]),
        subject_name_guess=str(parsed["subject_name_guess"]).strip(),
        generation_profile=str(parsed["generation_profile"]),
        recommended_quality=str(parsed["recommended_quality"]),
        recommended_samples=max(MIN_SAMPLE_COUNT, min(MAX_SAMPLE_COUNT, int(parsed["recommended_samples"]))),
        recommended_asset_goal=str(parsed["recommended_asset_goal"]),
        recommended_mesh_style=str(parsed["recommended_mesh_style"]),
        recommended_cleanup=str(parsed["recommended_cleanup"]),
        recommended_remove_background=bool(parsed["recommended_remove_background"]),
        triangle_target=max(MIN_TRIANGLE_BUDGET, min(MAX_TRIANGLE_BUDGET, int(parsed["triangle_target"]))),
        missing_views=tuple(str(item) for item in parsed.get("missing_views", [])),
        geometry_risks=tuple(str(item).strip() for item in parsed.get("geometry_risks", []) if str(item).strip()),
        search_terms=tuple(str(item).strip() for item in parsed.get("search_terms", [])[:MENTOR_SEARCH_LIMIT] if str(item).strip()),
        teaching_note=str(parsed["teaching_note"]).strip(),
        apply_now_summary=str(parsed["apply_now_summary"]).strip(),
        used_web_search=settings.use_web_search,
        sources=_extract_web_sources(raw_payload),
        response_id=str(raw_payload.get("id", "")),
        raw_payload=raw_payload,
    )
    return advice


def save_mentor_case(context: MentorContext, advice: MentorAdvice) -> Path:
    MENTOR_CASES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_name = sanitize_name(context.subject_name or advice.subject_name_guess or "mentor_case")
    case_dir = MENTOR_CASES_DIR / f"{stamp}_{case_name}"
    case_dir.mkdir(parents=True, exist_ok=True)
    images_dir = case_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    saved_images: list[dict[str, str]] = []
    for index, item in enumerate(context.selected_images, start=1):
        target_name = f"{index:02d}_{sanitize_name(item.path.stem)}{item.path.suffix.lower() or '.png'}"
        target_path = images_dir / target_name
        target_path.write_bytes(item.path.read_bytes())
        saved_images.append(
            {
                "original_path": str(item.path),
                "saved_path": str(target_path),
                "relative_path": str(Path("images") / target_name),
                "view": item.view_value,
                "detail_target": item.detail_target,
            }
        )

    context_payload = _context_payload(context)
    normalized_advice = {
        "subject_type": advice.subject_type,
        "subject_name_guess": advice.subject_name_guess,
        "generation_profile": advice.generation_profile,
        "recommended_quality": advice.recommended_quality,
        "recommended_samples": advice.recommended_samples,
        "recommended_asset_goal": advice.recommended_asset_goal,
        "recommended_mesh_style": advice.recommended_mesh_style,
        "recommended_cleanup": advice.recommended_cleanup,
        "recommended_remove_background": advice.recommended_remove_background,
        "triangle_target": advice.triangle_target,
        "missing_views": list(advice.missing_views),
        "geometry_risks": list(advice.geometry_risks),
        "search_terms": list(advice.search_terms),
        "teaching_note": advice.teaching_note,
        "apply_now_summary": advice.apply_now_summary,
        "used_web_search": advice.used_web_search,
        "sources": list(advice.sources),
        "response_id": advice.response_id,
    }

    manifest = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "signature": build_mentor_signature(context),
        "context": {
            **context_payload,
            "selected_images": saved_images,
        },
        "advice": normalized_advice,
    }
    manifest_path = case_dir / "mentor_case.json"
    context_path = case_dir / "context.json"
    advice_path = case_dir / "advice.json"
    dataset_record_path = case_dir / "dataset_record.json"
    training_example_path = case_dir / "training_example.json"

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    context_path.write_text(
        json.dumps(
            {
                "saved_at": manifest["saved_at"],
                "signature": manifest["signature"],
                "context": manifest["context"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    advice_path.write_text(json.dumps(normalized_advice, indent=2), encoding="utf-8")

    dataset_record = {
        "schema": "3dvisual_mesh_mentor_dataset_v1",
        "case_id": case_dir.name,
        "saved_at": manifest["saved_at"],
        "signature": manifest["signature"],
        "input": {
            **context_payload,
            "images": [
                {
                    "relative_path": item["relative_path"],
                    "view": item["view"],
                    "detail_target": item.get("detail_target", "Auto"),
                }
                for item in saved_images
            ],
        },
        "target": normalized_advice,
    }
    dataset_record_path.write_text(json.dumps(dataset_record, indent=2), encoding="utf-8")

    training_example = {
        "schema": "3dvisual_mesh_teacher_example_v1",
        "case_id": case_dir.name,
        "teacher_input": context_payload,
        "teacher_output": normalized_advice,
        "image_files": [
            {
                "file": item["relative_path"],
                "view": item["view"],
                "detail_target": item.get("detail_target", "Auto"),
            }
            for item in saved_images
        ],
    }
    training_example_path.write_text(json.dumps(training_example, indent=2), encoding="utf-8")

    if advice.raw_payload is not None:
        raw_path = case_dir / "mentor_response_raw.json"
        raw_path.write_text(json.dumps(advice.raw_payload, indent=2), encoding="utf-8")

    index_path = MENTOR_CASES_DIR / "mentor_dataset.jsonl"
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataset_record, ensure_ascii=False) + "\n")

    return manifest_path


def summarize_mentor_advice(advice: MentorAdvice, *, stale: bool = False) -> str:
    lines = [
        "3DVisual Mesh Mentor",
        "",
        f"Subject: {advice.subject_type} | {advice.subject_name_guess or 'No exact name guess'}",
        f"Profile: {advice.generation_profile}",
        f"Use now: {advice.recommended_quality} | {advice.recommended_samples} sample(s) | {advice.recommended_asset_goal}",
        f"Mesh: {advice.recommended_mesh_style} | {advice.recommended_cleanup} | BG {'On' if advice.recommended_remove_background else 'Off'}",
        f"Triangle target: {advice.triangle_target:,}",
    ]

    if advice.missing_views:
        lines.append("Missing views: " + ", ".join(advice.missing_views))
    if advice.geometry_risks:
        lines.append("Geometry risks: " + "; ".join(advice.geometry_risks[:4]))
    if advice.search_terms:
        lines.append("Search terms: " + " | ".join(advice.search_terms[:3]))
    if advice.sources:
        lines.append("Sources: " + " | ".join(advice.sources[:2]))

    lines.extend(
        [
            "",
            advice.apply_now_summary,
            advice.teaching_note,
        ]
    )

    if stale:
        lines.extend(
            [
                "",
                "This mentor advice is stale because the images or notes changed. Run Mentor again.",
            ]
        )

    return "\n".join(lines)
