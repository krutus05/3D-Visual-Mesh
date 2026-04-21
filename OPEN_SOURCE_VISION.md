# 3DVisual Mesh - Open Source Vision

## Goal

3DVisual Mesh should be a free open-source tool that helps developers turn images and references into usable 3D game assets faster.

This project is not trying to pretend that one random image can always become a production-ready mesh.

The real goal is:
- make image-to-3D practical on local hardware
- help users collect better references
- reduce obvious geometry failures
- improve cleanup and triangle control
- make the output easier to finish in Blender or a game pipeline

## Who It Is For

- indie game developers
- modders
- technical artists
- prop artists
- environment artists
- hobbyists learning game asset workflows
- tool developers who want to improve open-source image-to-mesh pipelines

## What Good Looks Like

For game use, a "good" output means:

- the silhouette is believable
- proportions are stable
- major parts are in the correct position
- triangle count is predictable
- the mesh is easy to clean up
- the mesh is easy to unwrap, bake, or rework in Blender
- the result is useful as:
  - a base mesh
  - a blockout
  - a prop starting point
  - a hero reference

## What This Project Should Be Honest About

The app should say the truth clearly:

- single-image car generation is weak
- transparent objects are hard
- exact wheel placement from one photo is unreliable
- AI detail is not the same as correct topology
- "more triangles" does not fix wrong geometry
- game-ready topology usually still needs cleanup or retopo

## Core Product Principles

### 1. Windows First

The easiest working Windows path should be the default.

### 2. AMD Friendly

The project should not assume NVIDIA unless there is no realistic AMD path.

### 3. Local First

Local generation is the base product.
Cloud or API backends can be optional, not mandatory.

### 4. Game-Asset Focused

The project should optimize for:
- believable shape
- manageable triangles
- cleaner shading
- easier Blender cleanup
- export quality

### 5. Practical Over Hype

The tool should help users get a better asset, not sell fantasy.

## Product Positioning

3DVisual Mesh should position itself as:

> A local image-to-mesh helper for game developers that improves references, generation settings, cleanup, and Blender finishing.

Not:

> A magic one-click system that always makes production topology from a single image.

## Main Quality Targets

### Detail Quality

- preserve important shape lines
- keep the main silhouette stable
- use better subject-aware preprocessing
- use multiview whenever possible

### Geometry Quality

- fewer floating parts
- fewer collapsed or stretched regions
- better part placement
- better profile and top-view consistency

### Topology / Triangle Quality

- target triangle budgets reliably
- reduce pointless density in flat areas
- avoid destroying shape with over-smoothing
- make output easier to decimate and retopo

### Pipeline Quality

- easy preview
- clear risk warnings
- Blender handoff
- plugin support
- predictable exports

## Long-Term Open Source Direction

The project should eventually support:

- plugin backends
- multiple mesh generators
- reference basket workflows
- Blender validation loops
- asset-type presets
- low-end / mid / high-end runtime profiles
- optional cloud backends

## Important Open Source Rule

Contributors should improve:
- reliability
- geometry
- cleanup
- topology
- usability

They should not turn the project into:
- a bloated AI launcher
- a random model zoo with no quality standard
- a UI full of fake "smart" features that do not really help asset quality
