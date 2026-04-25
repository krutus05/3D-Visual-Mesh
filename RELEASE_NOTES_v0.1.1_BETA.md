# 3DVisual Mesh v0.1.1 Beta - Workflow + Mesh Guidance Update

This update focuses on making the app easier and safer to use, especially for testing different hardware and improving image-to-mesh workflow.

## Highlights
- Hardware profiles and Safe Mode
- Fast Preview / Final Mesh workflow
- Preflight warnings
- Manual detail crops for hands, feet, face, cape/cloth, armor, hair, and accessories
- Mesh Health panel
- Repair recommendation display
- Game geometry intelligence guidance
- Smarter triangle budget recommendations
- Blender bake/export foundation

## Important
This is still beta. Real baking, real retopo, pose normalization, and semantic prior insertion are not fully implemented yet. Meshes may still need manual cleanup.

## Release Asset Note
This beta release currently includes the Portable Source package. The online installer and full offline NVIDIA/AMD packages are still being prepared and are not included in this release yet.

## Testing Checklist Before Final Release
1. Open app.
2. Load image.
3. Add one hand crop.
4. Add one foot crop.
5. Generate Fast Preview.
6. Generate Final Mesh.
7. Confirm Mesh Health panel fills in.
8. Confirm Repair Recommendation updates.
9. Confirm no fake bake PNGs are created.
10. Confirm website still loads.
11. Confirm README release notes are honest.
