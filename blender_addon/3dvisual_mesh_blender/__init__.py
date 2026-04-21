from __future__ import annotations

bl_info = {
    "name": "3DVisual Mesh",
    "author": "OpenAI Codex + Yanis",
    "version": (0, 3, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > 3DVisual",
    "description": "Import the latest 3DVisual Mesh result, audit triangles, run expert cleanup or QuadriFlow retopo, decimate, and apply an approximate reference color material.",
    "category": "Import-Export",
}

import math
from pathlib import Path

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel


def default_output_dir() -> str:
    return str(Path.home() / "Desktop")


def get_active_mesh(context):
    obj = context.active_object
    if obj and obj.type == "MESH":
        return obj
    return None


def get_target_mesh_objects(context):
    selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if selected_meshes:
        return selected_meshes

    active = get_active_mesh(context)
    return [active] if active is not None else []


def ensure_object_mode(context):
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def evaluated_triangle_count(context, obj) -> int:
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    finally:
        evaluated.to_mesh_clear()


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


def remove_small_face_islands(obj, *, min_faces: int, min_ratio: float) -> int:
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

        removed_count = len(to_delete)
        bmesh.ops.delete(bm, geom=to_delete, context="FACES")
        bm.to_mesh(obj.data)
        obj.data.update()
        return removed_count
    finally:
        bm.free()


def recalculate_normals(obj):
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


def set_shading_defaults(obj, *, auto_smooth_angle: float, use_weighted_normals: bool):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True

    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
    if hasattr(obj.data, "auto_smooth_angle"):
        obj.data.auto_smooth_angle = auto_smooth_angle

    modifier = obj.modifiers.get("TVM_WeightedNormal")
    if use_weighted_normals:
        if modifier is None:
            modifier = obj.modifiers.new(name="TVM_WeightedNormal", type="WEIGHTED_NORMAL")
        modifier.keep_sharp = True
        modifier.weight = 50
    elif modifier is not None:
        obj.modifiers.remove(modifier)


def refresh_triangle_total(context, mesh_objects=None) -> int:
    targets = mesh_objects or get_target_mesh_objects(context)
    total = sum(evaluated_triangle_count(context, obj) for obj in targets)
    context.scene.tvm_current_triangles = total
    return total


def expert_cleanup_object(obj, scene) -> dict[str, int]:
    merge_by_distance(obj, scene.tvm_merge_distance)
    remove_loose_geometry(obj)
    removed_faces = remove_small_face_islands(
        obj,
        min_faces=scene.tvm_island_min_faces,
        min_ratio=scene.tvm_island_ratio,
    )
    remove_loose_geometry(obj)
    recalculate_normals(obj)
    set_shading_defaults(
        obj,
        auto_smooth_angle=scene.tvm_auto_smooth_angle,
        use_weighted_normals=scene.tvm_use_weighted_normals,
    )
    return {"removed_faces": removed_faces}


def ensure_reference_material(
    image,
    *,
    material_name: str,
    roughness: float,
    metallic: float,
    projection_blend: float,
    use_alpha: bool,
):
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(name=material_name)

    material.use_nodes = True
    material.blend_method = "HASHED" if use_alpha else "OPAQUE"
    material.shadow_method = "HASHED" if use_alpha else "OPAQUE"

    node_tree = material.node_tree
    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-760, 0)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-560, 0)

    image_node = nodes.new("ShaderNodeTexImage")
    image_node.location = (-300, 80)
    image_node.image = image
    image_node.projection = "BOX"
    image_node.projection_blend = projection_blend

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 40)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (250, 40)

    links.new(texcoord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], image_node.inputs["Vector"])
    links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
    if use_alpha:
        links.new(image_node.outputs["Alpha"], principled.inputs["Alpha"])
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    return material


def assign_material(obj, material, *, replace_material: bool):
    if replace_material or not obj.data.materials:
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)
        obj.active_material = material
        return

    obj.data.materials.append(material)
    obj.active_material_index = len(obj.data.materials) - 1
    obj.active_material = material


def find_latest_glb(output_dir: str) -> Path | None:
    directory = Path(bpy.path.abspath(output_dir))
    if not directory.exists():
        return None

    def sort_key(path: Path):
        stem = path.stem.lower()
        is_raw = "_raw_" in stem or stem.endswith("_raw")
        return (1 if is_raw else 0, -path.stat().st_mtime)

    glbs = sorted(directory.glob("*.glb"), key=sort_key)
    return glbs[0] if glbs else None


class TVM_OT_import_latest(Operator):
    bl_idname = "tvm.import_latest"
    bl_label = "Import Latest GLB"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        latest = find_latest_glb(scene.tvm_output_dir)
        if latest is None:
            self.report({"WARNING"}, "No GLB file found in the selected output folder.")
            return {"CANCELLED"}

        bpy.ops.import_scene.gltf(filepath=str(latest))
        mesh_objects = [obj for obj in context.selected_objects if obj.type == "MESH"]
        if mesh_objects:
            context.view_layer.objects.active = mesh_objects[0]
            scene.tvm_current_triangles = sum(evaluated_triangle_count(context, obj) for obj in mesh_objects)
        scene.tvm_last_import_path = str(latest)
        self.report({"INFO"}, f"Imported {latest.name}")
        return {"FINISHED"}


class TVM_OT_count_tris(Operator):
    bl_idname = "tvm.count_tris"
    bl_label = "Refresh Triangle Count"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mesh_objects = get_target_mesh_objects(context)
        if not mesh_objects:
            self.report({"WARNING"}, "Select one or more mesh objects first.")
            return {"CANCELLED"}

        total = refresh_triangle_total(context, mesh_objects)
        self.report({"INFO"}, f"Current triangles: {total:,}")
        return {"FINISHED"}


class TVM_OT_expert_cleanup(Operator):
    bl_idname = "tvm.expert_cleanup"
    bl_label = "Expert Cleanup"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mesh_objects = get_target_mesh_objects(context)
        if not mesh_objects:
            self.report({"WARNING"}, "Select one or more mesh objects first.")
            return {"CANCELLED"}

        ensure_object_mode(context)
        total_removed = 0
        for obj in mesh_objects:
            result = expert_cleanup_object(obj, context.scene)
            total_removed += result["removed_faces"]

        total = refresh_triangle_total(context, mesh_objects)
        self.report(
            {"INFO"},
            f"Expert cleanup finished. Removed {total_removed:,} tiny-island faces. Current triangles: {total:,}",
        )
        return {"FINISHED"}


class TVM_OT_quadriflow_retopo(Operator):
    bl_idname = "tvm.quadriflow_retopo"
    bl_label = "QuadriFlow Retopo"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = get_active_mesh(context)
        if obj is None:
            self.report({"WARNING"}, "Select one active mesh first.")
            return {"CANCELLED"}

        ensure_object_mode(context)
        scene = context.scene
        expert_cleanup_object(obj, scene)

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj

        try:
            bpy.ops.object.quadriflow_remesh(
                use_mesh_symmetry=scene.tvm_qf_use_symmetry,
                use_preserve_sharp=scene.tvm_qf_preserve_sharp,
                use_preserve_boundary=scene.tvm_qf_preserve_boundary,
                mode="FACES",
                target_faces=scene.tvm_qf_target_faces,
                seed=scene.tvm_qf_seed,
            )
        except Exception as exc:
            self.report(
                {"WARNING"},
                "QuadriFlow failed. Run Expert Cleanup first and make sure the mesh is manifold. "
                f"Error: {exc}",
            )
            return {"CANCELLED"}

        set_shading_defaults(
            obj,
            auto_smooth_angle=scene.tvm_auto_smooth_angle,
            use_weighted_normals=scene.tvm_use_weighted_normals,
        )
        total = refresh_triangle_total(context, [obj])
        self.report({"INFO"}, f"QuadriFlow finished. Current triangles: {total:,}")
        return {"FINISHED"}


class TVM_OT_apply_target(Operator):
    bl_idname = "tvm.apply_target"
    bl_label = "Apply Target Triangles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mesh_objects = get_target_mesh_objects(context)
        if not mesh_objects:
            self.report({"WARNING"}, "Select one or more mesh objects first.")
            return {"CANCELLED"}

        scene = context.scene
        ensure_object_mode(context)
        target = max(1, scene.tvm_target_triangles)
        total_current = sum(evaluated_triangle_count(context, obj) for obj in mesh_objects)
        tolerance = max(10, int(target * 0.03))

        for obj in mesh_objects:
            context.view_layer.objects.active = obj
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)

            expert_cleanup_object(obj, scene)

            object_current = evaluated_triangle_count(context, obj)
            object_target = max(1, int(round(target * (object_current / max(total_current, 1)))))
            object_tolerance = max(6, int(object_target * 0.03))

            for attempt in range(6):
                object_current = evaluated_triangle_count(context, obj)
                if object_current <= object_target + object_tolerance:
                    break

                ratio = max(0.01, min(1.0, object_target / max(object_current, 1)))
                modifier = obj.modifiers.new(name=f"TVM_Decimate_{attempt + 1}", type="DECIMATE")
                modifier.decimate_type = "COLLAPSE"
                modifier.ratio = ratio
                modifier.use_collapse_triangulate = scene.tvm_keep_triangulated

                bpy.ops.object.modifier_apply(modifier=modifier.name)

            if scene.tvm_shade_smooth:
                bpy.ops.object.shade_smooth()
            set_shading_defaults(
                obj,
                auto_smooth_angle=scene.tvm_auto_smooth_angle,
                use_weighted_normals=scene.tvm_use_weighted_normals,
            )

        bpy.ops.object.select_all(action="DESELECT")
        for obj in mesh_objects:
            obj.select_set(True)
        context.view_layer.objects.active = mesh_objects[0]

        scene.tvm_current_triangles = refresh_triangle_total(context, mesh_objects)
        self.report(
            {"INFO"},
            f"Triangle target {target:,}, current result {scene.tvm_current_triangles:,}",
        )
        return {"FINISHED"}


class TVM_OT_apply_reference_color(Operator):
    bl_idname = "tvm.apply_reference_color"
    bl_label = "Apply Reference Base Color"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        mesh_objects = get_target_mesh_objects(context)
        if not mesh_objects:
            self.report({"WARNING"}, "Select one or more mesh objects first.")
            return {"CANCELLED"}

        image_path = Path(bpy.path.abspath(scene.tvm_color_reference_image))
        if not image_path.exists():
            self.report({"WARNING"}, "Pick a valid reference image first.")
            return {"CANCELLED"}

        image = bpy.data.images.load(filepath=str(image_path), check_existing=True)
        material = ensure_reference_material(
            image,
            material_name=f"TVM_BaseColor_{image_path.stem}",
            roughness=scene.tvm_color_roughness,
            metallic=scene.tvm_color_metallic,
            projection_blend=scene.tvm_color_projection_blend,
            use_alpha=scene.tvm_color_use_alpha,
        )

        for obj in mesh_objects:
            assign_material(obj, material, replace_material=scene.tvm_replace_material)

        self.report({"INFO"}, f"Applied approximate reference color from {image_path.name}")
        return {"FINISHED"}


class VIEW3D_PT_tvm_panel(Panel):
    bl_label = "3DVisual Mesh"
    bl_idname = "VIEW3D_PT_tvm_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "3DVisual"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = get_active_mesh(context)

        col = layout.column(align=True)
        col.label(text="Output Folder")
        col.prop(scene, "tvm_output_dir", text="")
        col.operator("tvm.import_latest", icon="IMPORT")

        box = layout.box()
        box.label(text="Triangle Audit")
        if obj is not None:
            box.label(text=f"Active Mesh: {obj.name}")
        else:
            box.label(text="Active Mesh: none")
        box.label(text=f"Current Triangles: {scene.tvm_current_triangles:,}")
        box.operator("tvm.count_tris", icon="MESH_DATA")

        box = layout.box()
        box.label(text="Cleanup + Target")
        box.prop(scene, "tvm_target_triangles")
        box.prop(scene, "tvm_merge_distance")
        box.prop(scene, "tvm_island_min_faces")
        box.prop(scene, "tvm_island_ratio")
        box.prop(scene, "tvm_keep_triangulated")
        box.prop(scene, "tvm_shade_smooth")
        box.prop(scene, "tvm_use_weighted_normals")
        box.prop(scene, "tvm_auto_smooth_angle")
        box.operator("tvm.apply_target", icon="MOD_DECIM")

        box = layout.box()
        box.label(text="Expert Topology")
        box.prop(scene, "tvm_qf_target_faces")
        box.prop(scene, "tvm_qf_preserve_sharp")
        box.prop(scene, "tvm_qf_preserve_boundary")
        box.prop(scene, "tvm_qf_use_symmetry")
        box.prop(scene, "tvm_qf_seed")
        row = box.row(align=True)
        row.operator("tvm.expert_cleanup", icon="BRUSH_DATA")
        row.operator("tvm.quadriflow_retopo", icon="MOD_REMESH")

        box = layout.box()
        box.label(text="Reference Base Color")
        box.prop(scene, "tvm_color_reference_image")
        box.prop(scene, "tvm_color_projection_blend")
        box.prop(scene, "tvm_color_roughness")
        box.prop(scene, "tvm_color_metallic")
        box.prop(scene, "tvm_color_use_alpha")
        box.prop(scene, "tvm_replace_material")
        box.operator("tvm.apply_reference_color", icon="MATERIAL")

        note = layout.box()
        note.label(text="Practical Notes")
        note.label(text="2-4 real views beat 1 view + more samples.")
        note.label(text="Use QuadriFlow for static props, armor, and hard-surface cleanup.")
        note.label(text="For animated characters, manual retopo is still the final expert path.")
        note.label(text="Reference color is approximate, not full texture baking.")


CLASSES = (
    TVM_OT_import_latest,
    TVM_OT_count_tris,
    TVM_OT_expert_cleanup,
    TVM_OT_quadriflow_retopo,
    TVM_OT_apply_target,
    TVM_OT_apply_reference_color,
    VIEW3D_PT_tvm_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.tvm_output_dir = StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        default=default_output_dir(),
    )
    bpy.types.Scene.tvm_last_import_path = StringProperty(
        name="Last Import",
        default="",
    )
    bpy.types.Scene.tvm_current_triangles = IntProperty(
        name="Current Triangles",
        default=0,
        min=0,
    )
    bpy.types.Scene.tvm_target_triangles = IntProperty(
        name="Target Triangles",
        default=25000,
        min=1,
        max=500000,
    )
    bpy.types.Scene.tvm_merge_distance = FloatProperty(
        name="Merge Distance",
        default=0.0005,
        min=0.0,
        max=0.1,
        precision=5,
    )
    bpy.types.Scene.tvm_island_min_faces = IntProperty(
        name="Island Min Faces",
        default=28,
        min=0,
        max=100000,
    )
    bpy.types.Scene.tvm_island_ratio = FloatProperty(
        name="Island Ratio",
        default=0.006,
        min=0.0,
        max=0.25,
        precision=4,
    )
    bpy.types.Scene.tvm_keep_triangulated = BoolProperty(
        name="Keep Triangulated",
        default=True,
    )
    bpy.types.Scene.tvm_shade_smooth = BoolProperty(
        name="Shade Smooth",
        default=True,
    )
    bpy.types.Scene.tvm_use_weighted_normals = BoolProperty(
        name="Weighted Normals",
        default=True,
    )
    bpy.types.Scene.tvm_auto_smooth_angle = FloatProperty(
        name="Auto Smooth Angle",
        subtype="ANGLE",
        default=math.radians(42.0),
        min=math.radians(1.0),
        max=math.radians(180.0),
    )
    bpy.types.Scene.tvm_qf_target_faces = IntProperty(
        name="QuadriFlow Faces",
        default=12000,
        min=100,
        max=500000,
    )
    bpy.types.Scene.tvm_qf_preserve_sharp = BoolProperty(
        name="Preserve Sharp",
        default=True,
    )
    bpy.types.Scene.tvm_qf_preserve_boundary = BoolProperty(
        name="Preserve Boundary",
        default=True,
    )
    bpy.types.Scene.tvm_qf_use_symmetry = BoolProperty(
        name="Use Symmetry",
        default=False,
    )
    bpy.types.Scene.tvm_qf_seed = IntProperty(
        name="QuadriFlow Seed",
        default=0,
        min=0,
        max=999999,
    )
    bpy.types.Scene.tvm_color_reference_image = StringProperty(
        name="Reference Image",
        subtype="FILE_PATH",
        default="",
    )
    bpy.types.Scene.tvm_color_projection_blend = FloatProperty(
        name="Box Blend",
        default=0.18,
        min=0.0,
        max=1.0,
        precision=3,
    )
    bpy.types.Scene.tvm_color_roughness = FloatProperty(
        name="Roughness",
        default=0.68,
        min=0.0,
        max=1.0,
        precision=3,
    )
    bpy.types.Scene.tvm_color_metallic = FloatProperty(
        name="Metallic",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=3,
    )
    bpy.types.Scene.tvm_color_use_alpha = BoolProperty(
        name="Use Alpha",
        default=False,
    )
    bpy.types.Scene.tvm_replace_material = BoolProperty(
        name="Replace First Material",
        default=True,
    )


def unregister():
    del bpy.types.Scene.tvm_replace_material
    del bpy.types.Scene.tvm_color_use_alpha
    del bpy.types.Scene.tvm_color_metallic
    del bpy.types.Scene.tvm_color_roughness
    del bpy.types.Scene.tvm_color_projection_blend
    del bpy.types.Scene.tvm_color_reference_image
    del bpy.types.Scene.tvm_qf_seed
    del bpy.types.Scene.tvm_qf_use_symmetry
    del bpy.types.Scene.tvm_qf_preserve_boundary
    del bpy.types.Scene.tvm_qf_preserve_sharp
    del bpy.types.Scene.tvm_qf_target_faces
    del bpy.types.Scene.tvm_auto_smooth_angle
    del bpy.types.Scene.tvm_use_weighted_normals
    del bpy.types.Scene.tvm_shade_smooth
    del bpy.types.Scene.tvm_keep_triangulated
    del bpy.types.Scene.tvm_island_ratio
    del bpy.types.Scene.tvm_island_min_faces
    del bpy.types.Scene.tvm_merge_distance
    del bpy.types.Scene.tvm_target_triangles
    del bpy.types.Scene.tvm_current_triangles
    del bpy.types.Scene.tvm_last_import_path
    del bpy.types.Scene.tvm_output_dir

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
