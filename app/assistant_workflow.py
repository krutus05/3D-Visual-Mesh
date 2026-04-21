from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DETAIL_VIEW_OPTION, VIEW_ORDER
from .generation import (
    SelectedImage,
    SubjectProfile,
    build_detail_focus_terms,
    build_subject_profile,
    guess_view_from_name,
    is_detail_view_value,
    normalize_detail_target,
    split_reference_images,
)


@dataclass(frozen=True)
class ReferencePlan:
    subject_label: str
    search_terms: str
    queries: tuple[str, ...]
    target_reference_types: tuple[str, ...]
    preferred_views: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class AnalysisPlan:
    profile: SubjectProfile
    image_count: int
    selected_views: tuple[str, ...]
    auto_view_count: int
    missing_views: tuple[str, ...]
    coverage_note: str
    risk_level: str
    recommendations: tuple[str, ...]
    recommended_quality: str
    recommended_samples: int
    recommended_asset_goal: str
    recommended_mesh_style: str
    recommended_cleanup: str
    recommended_remove_background: bool
    weak_parts: tuple["WeakPartReport", ...]
    weak_part_note: str
    note: str


@dataclass(frozen=True)
class MeshPlan:
    pipeline_mode: str
    preferred_model: str
    recommended_quality: str
    recommended_samples: int
    recommended_cleanup: str
    recommended_remove_background: bool
    needs_blender_finalize: bool
    note: str


@dataclass(frozen=True)
class SpecialistPlan:
    role_name: str
    provider: str
    mode: str
    active: bool
    note: str


@dataclass(frozen=True)
class ThreeRoleWorkflow:
    reference: ReferencePlan
    analysis: AnalysisPlan
    specialist: SpecialistPlan
    mesh: MeshPlan


@dataclass(frozen=True)
class WeakPartReport:
    part: str
    status: str
    note: str


@dataclass(frozen=True)
class DirectionGuardReport:
    status: str
    badge_text: str
    allow_generation: bool
    known_views: tuple[str, ...]
    missing_views: tuple[str, ...]
    duplicate_views: tuple[str, ...]
    unresolved_auto_images: tuple[str, ...]
    slot_lines: tuple[str, ...]
    note: str


def _normalize_views(selected_images: list[SelectedImage]) -> tuple[tuple[str, ...], int]:
    views: list[str] = []
    auto_count = 0
    for item in selected_images:
        value = (item.view_value or "Auto").strip()
        if not value or value.lower() == "ignore":
            continue
        if is_detail_view_value(value):
            continue
        if value.lower() == "auto":
            guessed = guess_view_from_name(item.path)
            if guessed:
                views.append(guessed.capitalize())
            else:
                auto_count += 1
            continue
        views.append(value)
    deduped: list[str] = []
    for view in views:
        if view not in deduped:
            deduped.append(view)
    return tuple(deduped), auto_count


def _build_profile(
    subject_type: str,
    subject_name: str,
    subject_notes: str,
    selected_images: list[SelectedImage] | None = None,
) -> SubjectProfile:
    selected_images = selected_images or []
    file_name_terms = " ".join(item.path.stem for item in selected_images[:6])
    detail_focus_terms = " ".join(build_detail_focus_terms(selected_images))
    enriched_name = " ".join(part for part in (subject_name, file_name_terms) if part).strip()
    enriched_notes = " ".join(part for part in (subject_notes, detail_focus_terms) if part).strip()
    return build_subject_profile(subject_type, enriched_name, enriched_notes)


def _collect_reference_slots(
    selected_images: list[SelectedImage],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...], tuple[str, ...]]:
    slot_names = {view.capitalize(): [] for view in VIEW_ORDER}
    unresolved_auto: list[str] = []
    ignored_items: list[str] = []

    for item in selected_images:
        value = (item.view_value or "Auto").strip()
        lowered = value.lower()
        if not value or lowered == "ignore":
            ignored_items.append(item.path.name)
            continue
        if is_detail_view_value(value):
            continue
        if lowered == "auto":
            guessed = guess_view_from_name(item.path)
            if guessed:
                slot_names[guessed.capitalize()].append(f"{item.path.name} (auto)")
            else:
                unresolved_auto.append(item.path.name)
            continue
        slot_names[value.capitalize()].append(item.path.name)

    frozen_slots = {view: tuple(names) for view, names in slot_names.items()}
    return frozen_slots, tuple(unresolved_auto), tuple(ignored_items)


def _mentioned_detail_targets(subject_name: str, subject_notes: str) -> tuple[str, ...]:
    text = " ".join(part for part in (subject_name, subject_notes) if part).lower()
    ordered_targets: list[str] = []
    for option in (
        "Face",
        "Head / Helmet",
        "Torso / Chest",
        "Shoulder",
        "Arm",
        "Hand",
        "Waist / Belt",
        "Leg",
        "Foot / Shoe",
        "Cape / Cloth",
        "Back Detail",
        "Weapon / Accessory",
    ):
        normalized = normalize_detail_target(option)
        keywords = {
            "Head / Helmet": ("head", "helmet", "hood"),
            "Face": ("face", "eyes", "mouth", "nose"),
            "Torso / Chest": ("torso", "chest", "body", "armor"),
            "Shoulder": ("shoulder", "pauldron"),
            "Arm": ("arm", "arms", "elbow", "forearm"),
            "Hand": ("hand", "hands", "finger", "fingers", "glove"),
            "Waist / Belt": ("waist", "belt", "hip"),
            "Leg": ("leg", "legs", "thigh", "knee", "shin"),
            "Foot / Shoe": ("foot", "feet", "shoe", "shoes", "boot", "boots", "sole"),
            "Cape / Cloth": ("cape", "cloth", "cloak", "robe", "fabric", "scarf", "torn"),
            "Back Detail": ("back", "rear"),
            "Weapon / Accessory": ("weapon", "sword", "shield", "accessory", "bag", "pack"),
        }.get(normalized, ())
        if any(keyword in text for keyword in keywords) and normalized not in ordered_targets:
            ordered_targets.append(normalized)
    return tuple(ordered_targets)


def build_weak_part_reports(
    primary_images: list[SelectedImage],
    detail_images: list[SelectedImage],
    profile: SubjectProfile,
    selected_views: tuple[str, ...],
    subject_name: str,
    subject_notes: str,
) -> tuple[tuple[WeakPartReport, ...], str]:
    expected_parts: list[str] = []

    if profile.is_organic or profile.has_fragile_detail:
        expected_parts.extend(["Face", "Hand", "Foot / Shoe"])
    if profile.has_cloth_detail:
        expected_parts.append("Cape / Cloth")
    if profile.is_organic and len(primary_images) <= 2:
        expected_parts.extend(["Torso / Chest", "Arm"])

    for target in _mentioned_detail_targets(subject_name, subject_notes):
        if target not in expected_parts:
            expected_parts.append(target)

    deduped_expected: list[str] = []
    for target in expected_parts:
        normalized = normalize_detail_target(target)
        if normalized != "Auto" and normalized not in deduped_expected:
            deduped_expected.append(normalized)

    focused_targets: list[str] = []
    generic_detail_count = 0
    for item in detail_images:
        target = normalize_detail_target(item.detail_target)
        if target == "Auto":
            generic_detail_count += 1
            continue
        if target not in focused_targets:
            focused_targets.append(target)

    weak_parts: list[WeakPartReport] = []
    has_front_view = "Front" in selected_views
    single_main = len(primary_images) <= 1

    for part in deduped_expected:
        if part in focused_targets:
            weak_parts.append(WeakPartReport(part=part, status="ready", note="Focused detail crop is already present."))
            continue

        if generic_detail_count > 0:
            weak_parts.append(
                WeakPartReport(
                    part=part,
                    status="generic",
                    note="Only generic detail crops are present. A dedicated crop would be safer for this part.",
                )
            )
            continue

        if part == "Face" and has_front_view:
            weak_parts.append(
                WeakPartReport(
                    part=part,
                    status="watch",
                    note="Front coverage exists, but a face crop would still help helmet, eyes, and mouth detail.",
                )
            )
            continue

        if part in {"Torso / Chest", "Arm"} and len(primary_images) >= 2:
            weak_parts.append(
                WeakPartReport(
                    part=part,
                    status="watch",
                    note="Main views may be enough for broad volume, but close detail still benefits from a crop.",
                )
            )
            continue

        weak_parts.append(
            WeakPartReport(
                part=part,
                status="missing" if single_main or profile.has_fragile_detail else "watch",
                note="Add a focused detail crop if this area matters in the final mesh.",
            )
        )

    if not weak_parts:
        return tuple(), "Weak Part Analyzer: no fragile parts detected."

    missing = [item.part for item in weak_parts if item.status == "missing"]
    generic = [item.part for item in weak_parts if item.status == "generic"]
    if missing:
        note = "Weak Part Analyzer: add focused crops for " + ", ".join(missing[:4]) + "."
    elif generic:
        note = "Weak Part Analyzer: retag generic detail crops for " + ", ".join(generic[:4]) + "."
    else:
        note = "Weak Part Analyzer: the risky thin-detail zones are at least partly covered."

    return tuple(weak_parts), note


def build_reference_plan(
    subject_type: str,
    subject_name: str,
    subject_notes: str,
    selected_images: list[SelectedImage] | None = None,
) -> ReferencePlan:
    selected_images = selected_images or []
    profile = _build_profile(subject_type, subject_name, subject_notes, selected_images)
    image_count = len(selected_images)
    search_terms = " ".join(
        part.strip()
        for part in (subject_name, subject_type if subject_type != "Auto" else "", subject_notes)
        if part and part.strip()
    ).strip() or profile.label

    if profile.is_vehicle:
        queries = (
            f"{search_terms} front left right rear reference",
            f"{search_terms} side profile wheelbase blueprint",
            f"{search_terms} roofline rear quarter wheel arch reference",
        )
        ref_types = ("front/left/right/rear photos", "side blueprint and wheelbase refs", "roofline, wheel arch, and glass details")
        preferred_views = ("Front", "Left", "Back", "Right")
        note = "Vehicle meshes improve most when the app sees real side and rear references, not just one glamor shot."
    elif profile.is_transparent:
        queries = (
            f"{search_terms} reference photos neutral lighting",
            f"{search_terms} silhouette dimensions",
            f"{search_terms} 3d model reference",
        )
        ref_types = ("clean silhouette photos", "dimension references", "simple 3D references")
        preferred_views = ("Front", "Left", "Back")
        note = "Transparent objects need silhouette help more than reflection-heavy beauty shots."
    elif profile.is_hard_surface:
        queries = (
            f"{search_terms} orthographic reference",
            f"{search_terms} dimensions reference",
            f"{search_terms} 3d model reference",
        )
        ref_types = ("orthographic photos", "dimension references", "hard-surface detail refs")
        preferred_views = ("Front", "Left", "Back")
        note = "Hard-surface generation is more reliable when the app can compare multiple straight views."
    else:
        queries = (
            f"{search_terms} reference photos",
            f"{search_terms} front side reference",
            f"{search_terms} 3d model reference",
        )
        ref_types = ("reference photos", "front and side views", "style references")
        preferred_views = ("Front", "Left")
        note = "Organic subjects tolerate looser input, but front and side views still help."

    if image_count >= 2:
        note += f" You already have {image_count} image(s), so Reference AI should focus on missing angles instead of generic inspiration."

    return ReferencePlan(
        subject_label=profile.label,
        search_terms=search_terms,
        queries=queries,
        target_reference_types=ref_types,
        preferred_views=preferred_views,
        note=note,
    )


def build_analysis_plan(
    selected_images: list[SelectedImage],
    subject_type: str,
    subject_name: str,
    subject_notes: str,
) -> AnalysisPlan:
    profile = _build_profile(subject_type, subject_name, subject_notes, selected_images)
    primary_images, detail_images = split_reference_images(selected_images)
    selected_views, auto_view_count = _normalize_views(primary_images)
    image_count = len(primary_images)
    detail_count = len(detail_images)
    preferred_views = ["Front", "Left", "Back", "Right"] if profile.is_vehicle else (["Front", "Left", "Back"] if profile.prefers_multiview else ["Front", "Left"])
    missing_views = tuple(view for view in preferred_views if view not in selected_views)

    if selected_views:
        coverage_note = f"Known directions: {', '.join(selected_views)}"
    else:
        coverage_note = "Known directions: none"
    if auto_view_count:
        coverage_note += f" | unresolved Auto images: {auto_view_count}"
    if detail_count:
        detail_targets: list[str] = []
        for item in detail_images[:4]:
            detail_target = normalize_detail_target(item.detail_target)
            if detail_target != "Auto" and detail_target not in detail_targets:
                detail_targets.append(detail_target)
        if detail_targets:
            coverage_note += f" | {detail_count} {DETAIL_VIEW_OPTION.lower()}(s): {', '.join(detail_targets)}"
        else:
            coverage_note += f" | {detail_count} {DETAIL_VIEW_OPTION.lower()}(s)"

    if profile.is_vehicle and (len(selected_views) < 3 or missing_views):
        risk_level = "Very High"
    elif profile.is_vehicle or profile.is_transparent:
        risk_level = "High"
    elif profile.is_hard_surface and image_count < 2:
        risk_level = "Medium-High"
    elif image_count <= 1:
        risk_level = "Medium"
    else:
        risk_level = "Lower"

    recommendations: list[str] = []
    if profile.is_vehicle:
        recommendations.append("Prioritize side profile and rear shape. Wheels, roofline, and glass are common failure points.")
        recommendations.append("Do not trust wheel placement unless left/right profile coverage is real or strongly implied.")
    if profile.is_transparent:
        recommendations.append("Do not trust reflections as geometry. Use silhouette and dimensions as the truth.")
    if profile.is_hard_surface:
        recommendations.append("Keep edge-preserving cleanup. Avoid over-smoothing hard lines.")
    if profile.has_fragile_detail:
        recommendations.append("Thin parts like fingers, torn cloth, straps, hair, or capes need slower layered scans and still depend heavily on clean source silhouettes.")
        recommendations.append("Best next upgrade is a second clean view or a separated detail crop for hands / cloth, not triangles alone.")
    if detail_count:
        recommendations.append("Detail crops are active. They help late detail passes, but they do not replace missing main front/side/back coverage.")
    if profile.prefers_multiview and image_count < 2:
        recommendations.append("Best next upgrade is more real views, not just more scan stages.")
    if auto_view_count:
        recommendations.append("Assign view labels manually when possible. Auto images do not guarantee real directional coverage.")
    if missing_views:
        recommendations.append("Missing useful views: " + ", ".join(missing_views))

    weak_parts, weak_part_note = build_weak_part_reports(
        primary_images,
        detail_images,
        profile,
        selected_views,
        subject_name,
        subject_notes,
    )
    missing_weak_parts = [item.part for item in weak_parts if item.status == "missing"]
    generic_weak_parts = [item.part for item in weak_parts if item.status == "generic"]
    if missing_weak_parts:
        recommendations.append("Weak Part Analyzer wants focused crops for: " + ", ".join(missing_weak_parts[:4]))
    elif generic_weak_parts:
        recommendations.append("Weak Part Analyzer sees generic detail crops only. Tag these better: " + ", ".join(generic_weak_parts[:4]))

    if profile.is_vehicle:
        quality = "Max Detail" if image_count <= 1 else "High"
        samples = 4 if len(selected_views) <= 1 else (3 if len(selected_views) <= 2 else 2)
        asset_goal = "Hero Prop"
        mesh_style = "Hero Realistic"
        cleanup = "Clean + Simpler"
        remove_bg = True
    elif profile.is_transparent:
        quality = "High"
        samples = 3
        asset_goal = "Hero Prop"
        mesh_style = "Normal / Realistic"
        cleanup = "Clean + Simpler"
        remove_bg = False
    elif profile.is_hard_surface:
        quality = "Balanced"
        samples = 3 if image_count <= 2 else 2
        asset_goal = "Hero Prop"
        mesh_style = "Normal / Realistic"
        cleanup = "Clean + Simpler"
        remove_bg = True
    else:
        quality = "Max Detail" if profile.has_fragile_detail and image_count <= 1 else ("High" if profile.has_fragile_detail else "Balanced")
        samples = 4 if profile.has_fragile_detail and image_count <= 1 else (5 if profile.has_fragile_detail else (2 if image_count <= 1 else 3))
        asset_goal = "Game Prop"
        mesh_style = "Normal / Realistic"
        cleanup = "Clean"
        remove_bg = True

    note = (
        f"Analysis AI sees this as {profile.label}. "
        f"Risk is {risk_level}. "
        "Its job is to choose safer build settings and tell you when the real bottleneck is missing reference coverage."
    )

    return AnalysisPlan(
        profile=profile,
        image_count=image_count,
        selected_views=selected_views,
        auto_view_count=auto_view_count,
        missing_views=missing_views,
        coverage_note=coverage_note,
        risk_level=risk_level,
        recommendations=tuple(recommendations),
        recommended_quality=quality,
        recommended_samples=samples,
        recommended_asset_goal=asset_goal,
        recommended_mesh_style=mesh_style,
        recommended_cleanup=cleanup,
        recommended_remove_background=remove_bg,
        weak_parts=weak_parts,
        weak_part_note=weak_part_note,
        note=note,
    )


def build_direction_guard(
    selected_images: list[SelectedImage],
    subject_type: str,
    subject_name: str,
    subject_notes: str,
) -> DirectionGuardReport:
    profile = _build_profile(subject_type, subject_name, subject_notes, selected_images)
    slot_names, unresolved_auto_images, _ignored_items = _collect_reference_slots(selected_images)
    primary_images, detail_images = split_reference_images(selected_images)
    known_views = tuple(view for view in ("Front", "Left", "Back", "Right") if slot_names.get(view))
    missing_views = tuple(view for view in ("Front", "Left", "Back", "Right") if not slot_names.get(view))
    duplicate_views = tuple(view for view, names in slot_names.items() if len(names) > 1)
    active_count = len(primary_images)
    has_side_profile = bool(slot_names["Left"] or slot_names["Right"])

    slot_lines: list[str] = []
    for view in ("Front", "Left", "Back", "Right"):
        names = slot_names[view]
        if not names:
            slot_lines.append(f"{view}: missing")
        elif len(names) == 1:
            slot_lines.append(f"{view}: {names[0]}")
        else:
            slot_lines.append(f"{view}: duplicate ({', '.join(names)})")

    if unresolved_auto_images:
        slot_lines.append("Auto: " + ", ".join(unresolved_auto_images))
    if detail_images:
        detail_descriptions = []
        for item in detail_images[:4]:
            detail_target = normalize_detail_target(item.detail_target)
            if detail_target != "Auto":
                detail_descriptions.append(f"{item.path.name} ({detail_target})")
            else:
                detail_descriptions.append(item.path.name)
        slot_lines.append(f"{DETAIL_VIEW_OPTION}: " + ", ".join(detail_descriptions))

    status = "ready"
    badge_text = "Ready"
    note = "Coverage looks usable."

    if profile.is_vehicle:
        if active_count < 2:
            status = "block"
            note = "Vehicle builds need at least 2 references. Add a side view before starting."
        elif not has_side_profile:
            status = "block"
            note = "Vehicle builds need a real left or right profile. Without it, wheelbase and wheel placement often fail."
        elif duplicate_views:
            status = "block"
            note = "Vehicle basket has duplicate direction slots. Keep one main image per direction before you start."
        elif len(known_views) < 2:
            status = "block"
            note = "Label at least 2 different directions for a vehicle. Auto alone is not enough."
        elif len(known_views) < 3:
            status = "warn"
            note = "Usable but risky. Add one more direction, ideally the rear or the opposite side."
        elif unresolved_auto_images:
            status = "warn"
            note = "Coverage is close, but some images are still Auto. Label them manually for safer part placement."
        else:
            note = "Vehicle coverage is good enough to start, but Blender cleanup is still expected."
    elif profile.prefers_multiview:
        if duplicate_views:
            status = "warn"
            note = "Some directions are duplicated. You can still start, but one image per direction is cleaner."
        elif active_count < 2 or len(known_views) < 2:
            status = "warn"
            note = "This subject usually works better with at least 2 labeled directions."
        elif unresolved_auto_images:
            status = "warn"
            note = "Coverage is decent, but labeling Auto images will make the build plan more reliable."
        else:
            note = "Reference coverage looks solid for a multiview-friendly subject."
    else:
        if duplicate_views:
            status = "warn"
            note = "You have duplicate direction labels. That is okay, but not always helpful."
        elif unresolved_auto_images and active_count >= 2:
            status = "warn"
            note = "If you label the views, the planner can give better advice."
        else:
            note = "This subject can start with loose reference coverage."

    if detail_images:
        note += f" {len(detail_images)} detail crop(s) will help thin-detail passes but will not replace missing main directions."

    if status == "warn":
        badge_text = "Warning"
    elif status == "block":
        badge_text = "Blocked"

    return DirectionGuardReport(
        status=status,
        badge_text=badge_text,
        allow_generation=status != "block",
        known_views=known_views,
        missing_views=missing_views,
        duplicate_views=duplicate_views,
        unresolved_auto_images=unresolved_auto_images,
        slot_lines=tuple(slot_lines),
        note=note,
    )


def build_mesh_plan(analysis: AnalysisPlan) -> MeshPlan:
    pipeline_mode = "multi-view" if analysis.image_count >= 2 else "single-image"
    preferred_model = "tencent/Hunyuan3D-2mv" if pipeline_mode == "multi-view" else "tencent/Hunyuan3D-2"
    needs_blender_finalize = analysis.profile.is_vehicle or analysis.profile.is_hard_surface or analysis.profile.is_transparent

    if needs_blender_finalize:
        note = (
            "Mesh AI should generate with Hunyuan first, then expect Blender cleanup/triangle audit as a normal part of the path."
        )
    else:
        note = "Mesh AI can usually trust the current cleanup path and lighter post-fix workflow."

    return MeshPlan(
        pipeline_mode=pipeline_mode,
        preferred_model=preferred_model,
        recommended_quality=analysis.recommended_quality,
        recommended_samples=analysis.recommended_samples,
        recommended_cleanup=analysis.recommended_cleanup,
        recommended_remove_background=analysis.recommended_remove_background,
        needs_blender_finalize=needs_blender_finalize,
        note=note,
    )


def build_specialist_plan(analysis: AnalysisPlan) -> SpecialistPlan:
    if analysis.profile.is_vehicle:
        active = True
        mode = "secondary shape critic"
        note = (
            "TRELLIS specialist should be treated as a second opinion for silhouette, wheel placement, and body proportion checks. "
            "Keep Hunyuan local as the main Windows AMD builder."
        )
    elif analysis.profile.is_hard_surface or analysis.profile.is_transparent:
        active = analysis.image_count >= 2
        mode = "secondary detail critic"
        note = (
            "TRELLIS specialist can help flag proportion drift and missing hard-surface volume, but it should not replace the local main builder."
        )
    elif analysis.profile.is_organic:
        active = analysis.image_count >= 2
        mode = "secondary pose and silhouette critic"
        note = (
            "TRELLIS specialist is useful as a second pass for limb width, cape flow, and broad silhouette consistency."
        )
    else:
        active = False
        mode = "optional second opinion"
        note = "TRELLIS specialist is optional here. GPT mentor plus the local builder is usually enough."

    return SpecialistPlan(
        role_name="TRELLIS Specialist",
        provider="Linux/cloud specialist path",
        mode=mode,
        active=active,
        note=note,
    )


def build_three_role_workflow(
    selected_images: list[SelectedImage],
    subject_type: str,
    subject_name: str,
    subject_notes: str,
) -> ThreeRoleWorkflow:
    reference = build_reference_plan(subject_type, subject_name, subject_notes, selected_images)
    analysis = build_analysis_plan(selected_images, subject_type, subject_name, subject_notes)
    specialist = build_specialist_plan(analysis)
    mesh = build_mesh_plan(analysis)
    return ThreeRoleWorkflow(reference=reference, analysis=analysis, specialist=specialist, mesh=mesh)


def describe_three_role_workflow(workflow: ThreeRoleWorkflow) -> str:
    lines = [
        f"Reference AI: {workflow.reference.subject_label}",
        f"Search focus: {workflow.reference.search_terms}",
        f"Reference types: {', '.join(workflow.reference.target_reference_types)}",
        f"Preferred views: {', '.join(workflow.reference.preferred_views)}",
        "",
        f"GPT Mentor: risk {workflow.analysis.risk_level}",
        f"Build hints: quality {workflow.analysis.recommended_quality}, samples {workflow.analysis.recommended_samples}, cleanup {workflow.analysis.recommended_cleanup}",
        workflow.analysis.coverage_note,
        f"Missing views: {', '.join(workflow.analysis.missing_views) if workflow.analysis.missing_views else 'none'}",
        "",
        f"{workflow.specialist.role_name}: {'On' if workflow.specialist.active else 'Optional'}",
        f"Specialist mode: {workflow.specialist.mode}",
        workflow.specialist.note,
        "",
        f"Mesh AI: {workflow.mesh.pipeline_mode} via {workflow.mesh.preferred_model}",
        f"Blender finalize: {'Yes' if workflow.mesh.needs_blender_finalize else 'Optional'}",
        workflow.analysis.weak_part_note,
    ]

    if workflow.analysis.weak_parts:
        lines.append("Weak parts:")
        lines.extend(
            f"- {item.part}: {item.status} | {item.note}"
            for item in workflow.analysis.weak_parts
        )

    if workflow.analysis.recommendations:
        lines.append("")
        lines.append("Advice:")
        lines.extend(f"- {item}" for item in workflow.analysis.recommendations)

    return "\n".join(lines)
