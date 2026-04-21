# 3DVisual Mesh - Three AI Workflow

This app now uses a practical three-role workflow around Hunyuan:

## 1. Reference AI

Input:
- subject type
- known model/name
- user notes
- current selected images

Job:
- build targeted search queries
- decide what extra references would help most
- prefer blueprint and orthographic references for vehicles and hard-surface objects

Output:
- search terms
- search queries
- preferred missing views
- reference note

## 2. Analysis AI

Input:
- reference notes
- selected images and view labels
- subject classification

Job:
- classify the subject as vehicle / hard-surface / transparent / organic
- estimate risk of deformation
- decide whether the object really needs more views
- recommend quality, samples, cleanup, background handling, asset goal, and mesh style

Output:
- risk level
- build recommendations
- missing views
- recommended app settings

## 3. Mesh AI

Input:
- analysis result
- selected images
- final generation options

Job:
- choose single-image or multiview path
- prefer `tencent/Hunyuan3D-2mv` when there are enough views
- run Hunyuan shape generation
- run cleanup, triangle targeting, preview render, and Blender-side follow-up when needed

Output:
- preferred Hunyuan path
- mesh execution note
- final local mesh result

## Important Limit

This is a workflow architecture, not live self-training.

What it does:
- guides the build
- improves search focus
- improves setting choices
- reduces obvious bad assumptions

What it does not do:
- retrain Hunyuan from the web
- automatically trust random internet meshes
- merge external 3D data directly into local generation without a dedicated reconstruction pipeline

## Best Future Upgrade

If you want the next serious step later, add:
- a real search/retrieval panel with selected reference basket
- optional API-based assistant chat
- optional local VLM/LLM for richer reasoning over images + notes
- a Blender-side validation loop for triangle and topology checks
