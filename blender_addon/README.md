# 3DVisual Mesh Blender Add-on

This add-on gives Blender-side help after the AI mesh is already generated:

- import the latest `.glb` from Desktop
- read the real triangle count of the active mesh
- apply a tighter Blender decimate pass toward your target
- do a small merge-by-distance cleanup
- apply an approximate reference-image base color material with box projection

Install in Blender:

1. `Edit > Preferences > Add-ons > Install`
2. Pick `3dvisual_mesh_blender.zip`
3. Enable `3DVisual Mesh`
4. Open the `3DVisual` tab in the 3D View sidebar

Why this exists:

- Hunyuan itself is still the shape generator
- this add-on does not train the AI
- it gives you a better Blender-side finishing step when the raw output ignores triangle budget too loosely
- the reference color pass is a fast visual helper for characters, creatures, and props, not a full automatic texture bake
