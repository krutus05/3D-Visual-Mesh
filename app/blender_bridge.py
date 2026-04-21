import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import BLENDER_BRIDGE_DIR


@dataclass(frozen=True)
class BlenderBridgeOptions:
    mesh_path: Path
    mode: str = "cleanup"
    quadriflow_target_faces: int = 12000
    quadriflow_preserve_sharp: bool = True
    quadriflow_preserve_boundary: bool = True
    quadriflow_use_symmetry: bool = False
    quadriflow_seed: int = 0
    merge_distance: float = 0.0005
    island_min_faces: int = 28
    island_ratio: float = 0.006
    auto_smooth_angle_deg: float = 42.0
    use_weighted_normals: bool = True
    keep_source_copy: bool = True


def _version_key(path: Path) -> tuple:
    parts = re.findall(r"\d+", path.as_posix())
    return tuple(int(part) for part in parts) if parts else (0,)


def detect_blender_executable(candidate: str | None = None) -> Path | None:
    if candidate:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists() and candidate_path.is_file():
            return candidate_path

    env_candidate = os.environ.get("BLENDER_EXE", "").strip()
    if env_candidate:
        env_path = Path(env_candidate).expanduser()
        if env_path.exists() and env_path.is_file():
            return env_path

    search_roots = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(env_name, "").strip()
        if value:
            search_roots.append(Path(value))

    patterns = (
        "Blender Foundation/Blender */blender.exe",
        "Programs/Blender Foundation/Blender */blender.exe",
        "Blender*/blender.exe",
    )

    found: list[Path] = []
    for root in search_roots:
        for pattern in patterns:
            found.extend(path for path in root.glob(pattern) if path.exists() and path.is_file())

    if not found:
        return None
    return sorted(found, key=_version_key, reverse=True)[0]


def _startup_script(options: BlenderBridgeOptions) -> str:
    payload = {
        "mesh_path": str(Path(options.mesh_path)),
        "mode": options.mode,
        "quadriflow_target_faces": int(options.quadriflow_target_faces),
        "quadriflow_preserve_sharp": bool(options.quadriflow_preserve_sharp),
        "quadriflow_preserve_boundary": bool(options.quadriflow_preserve_boundary),
        "quadriflow_use_symmetry": bool(options.quadriflow_use_symmetry),
        "quadriflow_seed": int(options.quadriflow_seed),
        "merge_distance": float(options.merge_distance),
        "island_min_faces": int(options.island_min_faces),
        "island_ratio": float(options.island_ratio),
        "auto_smooth_angle_deg": float(options.auto_smooth_angle_deg),
        "use_weighted_normals": bool(options.use_weighted_normals),
        "keep_source_copy": bool(options.keep_source_copy),
    }
    payload_json = json.dumps(payload)
    return f"""\
import json
import math
from pathlib import Path

import bmesh
import bpy

SETTINGS = json.loads({json.dumps(payload_json)})
MESH_PATH = Path(SETTINGS["mesh_path"])
MODE = SETTINGS["mode"]
MERGE_DISTANCE = float(SETTINGS["merge_distance"])
ISLAND_MIN_FACES = int(SETTINGS["island_min_faces"])
ISLAND_RATIO = float(SETTINGS["island_ratio"])
AUTO_SMOOTH_ANGLE = math.radians(float(SETTINGS["auto_smooth_angle_deg"]))
USE_WEIGHTED_NORMALS = bool(SETTINGS["use_weighted_normals"])
QUADRIFLOW_TARGET_FACES = int(SETTINGS["quadriflow_target_faces"])
QUADRIFLOW_PRESERVE_SHARP = bool(SETTINGS["quadriflow_preserve_sharp"])
QUADRIFLOW_PRESERVE_BOUNDARY = bool(SETTINGS["quadriflow_preserve_boundary"])
QUADRIFLOW_USE_SYMMETRY = bool(SETTINGS["quadriflow_use_symmetry"])
QUADRIFLOW_SEED = int(SETTINGS["quadriflow_seed"])
KEEP_SOURCE_COPY = bool(SETTINGS["keep_source_copy"])


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablock in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(datablock):
            if item.users == 0:
                datablock.remove(item)


def ensure_object_mode():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def merge_by_distance(obj, distance: float):
    if distance <= 0:
        return
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=distance)
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()


def remove_loose_geometry(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        loose_edges = [edge for edge in bm.edges if not edge.link_faces]
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
        loose_verts = [vert for vert in bm.verts if not vert.link_edges]
        if loose_verts:
            bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()


def remove_small_face_islands(obj, min_faces: int, min_ratio: float):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        if not bm.faces:
            return 0

        for face in bm.faces:
            face.tag = False

        components = []
        for face in bm.faces:
            if face.tag:
                continue
            face.tag = True
            stack = [face]
            component = []
            while stack:
                current = stack.pop()
                component.append(current)
                for edge in current.edges:
                    for linked in edge.link_faces:
                        if not linked.tag:
                            linked.tag = True
                            stack.append(linked)
            components.append(component)

        if len(components) <= 1:
            return 0

        largest = max(len(component) for component in components)
        threshold = max(int(min_faces), int(round(largest * max(0.0, min_ratio))))
        if threshold <= 0:
            return 0

        to_delete = [face for component in components if len(component) < threshold for face in component]
        if not to_delete:
            return 0

        removed = len(to_delete)
        bmesh.ops.delete(bm, geom=to_delete, context="FACES")
        bm.to_mesh(obj.data)
        obj.data.update()
        return removed
    finally:
        bm.free()


def recalc_normals(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()


def set_shading_defaults(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True

    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
    if hasattr(obj.data, "auto_smooth_angle"):
        obj.data.auto_smooth_angle = AUTO_SMOOTH_ANGLE

    modifier = obj.modifiers.get("TVM_WeightedNormal")
    if USE_WEIGHTED_NORMALS:
        if modifier is None:
            modifier = obj.modifiers.new(name="TVM_WeightedNormal", type="WEIGHTED_NORMAL")
        modifier.keep_sharp = True
        modifier.weight = 50
    elif modifier is not None:
        obj.modifiers.remove(modifier)


def expert_cleanup_object(obj):
    merge_by_distance(obj, MERGE_DISTANCE)
    remove_loose_geometry(obj)
    removed = remove_small_face_islands(obj, ISLAND_MIN_FACES, ISLAND_RATIO)
    remove_loose_geometry(obj)
    recalc_normals(obj)
    set_shading_defaults(obj)
    return removed


def duplicate_hidden_source(obj):
    source = obj.copy()
    source.data = obj.data.copy()
    source.name = obj.name + "_source"
    bpy.context.collection.objects.link(source)
    source.hide_viewport = True
    source.hide_render = True
    source.hide_select = True
    return source


def frame_view():
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((region for region in area.regions if region.type == "WINDOW"), None)
            if region is None:
                continue
            override = {{
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
            }}
            try:
                bpy.ops.view3d.view_all(override, center=False)
            except Exception:
                pass
            return


clear_scene()
ensure_object_mode()
bpy.ops.import_scene.gltf(filepath=str(MESH_PATH))
mesh_objects = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
if mesh_objects:
    bpy.context.view_layer.objects.active = mesh_objects[0]

removed_total = 0
for obj in mesh_objects:
    removed_total += expert_cleanup_object(obj)

active = mesh_objects[0] if mesh_objects else None
retopo_note = "cleanup only"

if MODE == "retopo" and active is not None:
    bpy.ops.object.select_all(action="DESELECT")
    active.select_set(True)
    bpy.context.view_layer.objects.active = active

    if KEEP_SOURCE_COPY:
        duplicate_hidden_source(active)

    try:
        bpy.ops.object.quadriflow_remesh(
            use_preserve_sharp=QUADRIFLOW_PRESERVE_SHARP,
            use_preserve_boundary=QUADRIFLOW_PRESERVE_BOUNDARY,
            use_paint_symmetry=QUADRIFLOW_USE_SYMMETRY,
            smooth_normals=False,
            mode="FACES",
            target_faces=QUADRIFLOW_TARGET_FACES,
            seed=QUADRIFLOW_SEED,
        )
        expert_cleanup_object(active)
        retopo_note = f"Quadriflow target {{QUADRIFLOW_TARGET_FACES:,}} faces"
    except Exception as exc:
        retopo_note = "Quadriflow failed: " + str(exc)

for obj in [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]:
    obj.select_set(False)
if active is not None:
    active.select_set(True)
    bpy.context.view_layer.objects.active = active

frame_view()
print(
    f"3DVisual Mesh Blender bridge loaded {{len(mesh_objects)}} mesh object(s). "
    f"Removed {{removed_total}} tiny-island faces. Mode: {{MODE}}. {{retopo_note}}."
)
"""


def launch_blender_session(blender_executable: Path, options: BlenderBridgeOptions) -> Path:
    blender_executable = Path(blender_executable)
    mesh_path = Path(options.mesh_path)

    if not blender_executable.exists():
        raise FileNotFoundError(f"Blender executable was not found: {blender_executable}")
    if not mesh_path.exists():
        raise FileNotFoundError(f"Mesh file was not found: {mesh_path}")

    BLENDER_BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "retopo" if options.mode == "retopo" else "cleanup"
    script_path = BLENDER_BRIDGE_DIR / f"open_{suffix}_session.py"
    script_path.write_text(_startup_script(options), encoding="utf-8")

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    subprocess.Popen(
        [str(blender_executable), "--python", str(script_path)],
        cwd=str(mesh_path.parent),
        creationflags=creationflags,
    )
    return script_path


def launch_blender_cleanup(blender_executable: Path, mesh_path: Path) -> Path:
    return launch_blender_session(
        blender_executable,
        BlenderBridgeOptions(mesh_path=Path(mesh_path), mode="cleanup"),
    )


def launch_blender_retopo(blender_executable: Path, options: BlenderBridgeOptions) -> Path:
    return launch_blender_session(blender_executable, BlenderBridgeOptions(**{**options.__dict__, "mode": "retopo"}))
