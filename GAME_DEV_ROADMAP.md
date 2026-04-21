# 3DVisual Mesh - Game Dev Roadmap

## North Star

Help developers get from image/reference input to a usable game-asset base mesh faster, with less cleanup pain.

## Priority 1 - Fix Geometry First

These are the most important tasks because wrong geometry ruins everything after it:

- stricter vehicle guard
- stronger multiview enforcement for cars and hard-surface objects
- better view detection and missing-view warnings
- object-type-specific preprocessing
- stronger candidate scoring for:
  - wheel placement
  - left/right symmetry
  - silhouette stability
  - top-view width
  - roofline consistency

Success looks like:
- fewer impossible car shapes
- fewer wheels in wrong places
- fewer inflated roofs and sides
- less broken underside guessing

## Priority 2 - Make Topology More Useful

Image-to-3D output will still need cleanup, so the goal is not perfect topology.
The goal is topology that is easier to finish.

Focus:

- cleaner decimation
- flatter density in large smooth areas
- sharper preservation on edges and wheel arches
- fewer tiny floaters
- better non-manifold cleanup
- better triangle target accuracy

Success looks like:
- easier Blender cleanup
- easier retopo
- more predictable triangle counts
- less random noise in flat panels

## Priority 3 - Blender Finish Path

The app should treat Blender as a normal part of the workflow, not an afterthought.

Focus:

- import latest mesh directly
- triangle audit
- cleanup operators
- better decimation presets
- quick mirror / symmetry checks
- simple pre-export validation

Success looks like:
- one-click handoff into Blender
- fewer manual cleanup steps
- easier export to game engines

## Priority 4 - Reference Basket

This is the biggest product upgrade after geometry safety.

Focus:

- collect selected reference images inside the app
- separate:
  - source input images
  - research reference images
  - blueprint / proportion references
- mark references by direction:
  - front
  - left
  - back
  - right
  - top
  - detail

Success looks like:
- better car and hard-surface results
- fewer bad assumptions from one beauty shot

## Priority 5 - Backend Architecture

The app should support more than one generator, but only if it stays clean.

Planned backend idea:

- Hunyuan backend
- optional experimental backend slot

Rule:

- do not add a backend unless it solves a real quality problem
- do not add a backend if it makes Windows + AMD worse

## Priority 6 - Asset-Type Presets

The app should have strong presets for:

- game prop
- vehicle
- weapon
- stylized prop
- hero prop
- character bust
- transparent object

Each preset should change:

- quality
- cleanup
- samples
- triangle target
- reference expectations

## Priority 7 - Open Source Contributor Path

The repo should be easy for outside devs to help with:

- docs
- plugin examples
- backend work
- UI work
- Blender tools
- cleanup / topology experiments

Good first contribution areas:

- better geometry scoring
- better reference parsing
- better Blender validation
- UI polish
- plugin examples

## What To Avoid

- adding ten backends with no quality bar
- pretending single-image cars are solved
- adding fake AI chat features that do not improve results
- prioritizing screenshots over mesh quality
- bloating the app until normal users cannot understand it
