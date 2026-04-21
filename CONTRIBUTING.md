# Contributing to 3DVisual Mesh

Thanks for helping.

This project is trying to become a practical open-source image-to-mesh tool for game developers on local hardware, especially Windows and AMD.

## What Kind of Contributions Help Most

High-value contributions:

- geometry reliability
- better reference workflows
- better cleanup and triangle control
- Blender integration
- UI clarity
- plugin system improvements
- documentation that helps real users

Lower-value contributions:

- flashy UI ideas with no mesh benefit
- adding random models with no quality standard
- features that make the app more confusing for normal users

## Main Quality Rule

Please optimize for:

- believable shape
- better proportions
- cleaner triangles
- easier Blender finishing
- honest user feedback

Not for:

- marketing claims
- fake "AI intelligence"
- one-click promises that are not true

## Before You Add a Feature

Ask:

- does this improve geometry, topology, cleanup, or workflow?
- does this help Windows users?
- does this help AMD users?
- does this make the app easier or harder to understand?
- is this a real gain or just another option?

## Current Project Focus

The highest-priority areas are:

- vehicle and hard-surface geometry
- multiview workflows
- triangle control
- Blender cleanup path
- reference basket / direction-aware research

## File Areas

- `app/ui_native.py`
  - native Windows UI
- `app/generation.py`
  - image prep, generation flow, cleanup, export
- `app/assistant_workflow.py`
  - Reference AI -> Analysis AI -> Mesh AI planning
- `app/plugin_system.py`
  - simple plugin loading
- `blender_addon/`
  - Blender-side import and cleanup tools

## Suggested Contribution Types

### UI / UX

- make warnings clearer
- improve flow for reference labeling
- improve result preview and post-build actions

### Geometry / Cleanup

- improve mesh scoring
- improve edge-preserving cleanup
- improve hard-surface decimation
- improve part-placement sanity checks

### Blender

- better validation operators
- symmetry checks
- export helpers
- cleanup presets for game assets

### Plugin Support

- new safe plugin examples
- structured plugin hooks
- backend adapter architecture

## What We Need From Contributors

When possible, describe:

- what problem you saw
- what object type failed
- what images were used
- whether the issue is:
  - shape
  - proportion
  - triangles
  - texture
  - export
  - UI

That makes the project much easier to improve in a real way.

## License Note

The project should have a clear public license before public release.
That decision should be made carefully because model wrappers, plugins, and redistribution have real consequences.
