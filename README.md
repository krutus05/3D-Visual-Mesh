# 3DVisual Mesh (BETA) (Version 0.1.1)

[Website](https://krutus05.github.io/3D-Visual-Mesh/) | [GitHub Releases](https://github.com/krutus05/3D-Visual-Mesh/releases) | [Optional Support](https://ko-fi.com/3dvisualmesh)

3DVisual Mesh is a practical local image-to-mesh helper for Windows. Results are not guaranteed to come out as a 100% finished production mesh every time, and many outputs still benefit from light cleanup or polish in Blender. The project is still a work in progress, and generated meshes can also be used as a starting point for 3D printing tests.

## v0.1.1 Beta - Workflow + Mesh Guidance Update

### Added
- Hardware profiles and Safe Mode for weaker PCs.
- Fast Preview and Final Mesh workflow.
- Preflight warnings for risky settings.
- Manual detail crop flow for hands, feet, face, cape/cloth, armor, hair, accessories, and other detail areas.
- Mesh Health panel with geometry diagnostics.
- Repair recommendation display.
- Game geometry intelligence guidance for smarter triangle budgets and output workflows.
- Blender bake/export foundation without fake outputs.

### Improved
- Website messaging now focuses more clearly on the app-first beta workflow.
- Triangle budget guidance is more honest: high triangle count alone does not guarantee better quality.
- Reference/detail workflow is clearer for multi-view character sheets.
- Repair recommendations now react to detail crops and mesh health.

### Still Experimental / Not Finished
- Real Blender normal/AO/curvature baking.
- Real game-quality retopo.
- Pose normalization.
- Semantic geometry prior insertion/replacement.
- Full offline NVIDIA/AMD package flow.

### Beta Warning
3DVisual Mesh is still beta software. Meshes are not guaranteed to be fully finished. Outputs may need cleanup or manual polish, especially for hands, feet, capes/cloth, hidden backsides, and complex armor.

This workspace now keeps the local helper files organized into a few simple folders:

- `app/` - the real app code
- `installer/` - release-package and Windows installer build scripts
- `launchers/` - local `.bat` launchers
- `tools/` - maintainer-only wheelhouse and offline-package build scripts
- `marketing/` - launch, sponsor, and internet-post copy
- `website/` - public project site for downloads, docs, and open-source landing page
- `README_FIRST.txt` - short friend-facing startup guide for the packaged build
- `requirements_one_click_windows_amd.txt` - one-file AMD bootstrap stack
- `requirements_one_click_windows_nvidia.txt` - one-file NVIDIA bootstrap stack

Best install path:

- `3DVisualMesh_0.1.1_Online_Setup.exe`

Portable start path:

- `Start 3DVisual Mesh.bat`
- `Start 3DVisual Mesh - NVIDIA.bat`
- `Start 3DVisual Mesh - AMD.bat`
- `Repair Install.bat`

Download / install types:

- `3DVisualMesh_0.1.1_NVIDIA_Full_Offline.zip` - larger download for NVIDIA users. Recommended when you want the smoother local-first setup path.
- `3DVisualMesh_0.1.1_AMD_Full_Offline.zip` - larger download for AMD users. Recommended when you want the smoother local-first setup path.
- `3DVisualMesh_0.1.1_Online_Setup.exe` - smaller download, still needs internet on first setup, now writes clearer logs and supports repair mode.
- `3DVisualMesh_0.1.1_Portable_Source.zip` - advanced users only.

Cleanup:

- Dry run: `powershell -ExecutionPolicy Bypass -File tools/clean_release_leftovers.ps1 -DryRun`
- Normal cleanup: `powershell -ExecutionPolicy Bypass -File tools/clean_release_leftovers.ps1`
- Forced cleanup: `powershell -ExecutionPolicy Bypass -File tools/clean_release_leftovers.ps1 -Force`

The app code entry point is:

- `app/ui_native.py`
- `THREE_AI_ARCHITECTURE.md` describes the new `Reference AI -> Analysis AI -> Mesh AI` workflow used by the Assist tab
- `OPEN_SOURCE_VISION.md` explains the long-term public goal for the app
- `GAME_DEV_ROADMAP.md` lists the game-asset quality priorities
- `CONTRIBUTING.md` explains what outside developers should improve first

Open source direction:

- The app is being shaped as a practical open-source helper for game developers, not a fake one-click miracle tool.
- The main quality bar is believable geometry, controllable triangles, easier Blender cleanup, and honest limits.

General geometry system:

- The geometry system is general, not anime-only. `Anime / Toon` is just one style target beside `Realistic`, `Semi-Realistic`, `Stylized`, `Low Poly`, `Hard Surface`, `Creature / Organic`, and `3D Print / Statue`.
- Better game-looking results do not come only from raw triangle count. The app now starts recommending triangle budgets, smart distribution, retopo/bake strategy, mesh health checks, and LOD direction instead of assuming `155k` raw AI triangles is automatically better.
- For game-ready work, geometry should carry silhouette, hands, feet, armor edges, hair chunks, hard-surface bevels, and deformation zones. Smaller surface detail should usually go into normal/AO maps later.
- For 3D print/statue work, watertight real geometry matters more than baked-map detail.
- Legal prior/reference data belongs under `resources/game_geometry_data/` and should only use original, `CC0`, `Public Domain`, or properly attributed `CC-BY` sources.
- Avoid ripped game assets, unknown-license meshes, and `CC-BY-NC` content for bundled or commercial-facing features.

Support:

- The app is free to try and still a work in progress.
- If someone wants to support development, the donation page is:
  `https://ko-fi.com/3dvisualmesh`
- Donations are optional and help fund more app work, plugin support, cleanup tools, and future updates.

Feedback:

- If you hit a real bug, open a `Bug Report` issue.
- If a mesh comes out wrong, open a `Mesh Quality Report` issue with screenshots and hardware info.
- Good reports should include your GPU, VRAM, RAM, Windows version, subject type, and result screenshots.

Notes:

- The current `v0.1.1` packaging flow stages a package-root layout with `resources\\app`, `resources\\launchers`, `resources\\tools`, `resources\\python`, `resources\\wheels`, `resources\\vendor`, `resources\\models`, and `resources\\logs`.
- The full offline package top level is now meant to stay simple: `Start 3DVisual Mesh - NVIDIA`, `Start 3DVisual Mesh - AMD`, `Repair Install`, and `README_FIRST`.
- The installer copies the staged package into `%LOCALAPPDATA%\\Programs\\3DVisual Mesh`, creates Desktop and Start Menu shortcuts, and then launches the same bootstrap flow.
- The launcher now writes `resources\\logs\\install.log`, `resources\\logs\\launcher.log`, or `resources\\logs\\repair.log` depending on the path used.
- The launcher can now auto-detect `AMD` or `NVIDIA`, force a chosen GPU path from the dedicated NVIDIA/AMD batch launchers, check disk space first, route the Hugging Face cache into `resources\\models\\huggingface`, and fall back cleanly between local wheelhouse installs and the online bootstrap path.
- Git is optional for the bootstrap path because the launcher can fall back to the pinned GitHub ZIP if Git is not installed yet.
- `installer/build_release_package.ps1` now stages `3DVisualMesh_0.1.1_Portable_Source.zip`.
- `installer/build_windows_installer.ps1` now builds `3DVisualMesh_0.1.1_Online_Setup.exe` through Inno Setup.
- `tools/build_wheelhouse_common.ps1`, `tools/build_wheelhouse_amd.ps1`, and `tools/build_wheelhouse_nvidia.ps1` build local wheelhouses for offline packaging.
- `tools/build_full_offline_package_amd.ps1` and `tools/build_full_offline_package_nvidia.ps1` build the GPU-specific full offline packages without bundling both wheel stacks together.
- The Hunyuan model still resizes images internally, so tight framing and clean backgrounds matter more than raw 4K size.
- Best local quality path is still `1 image` or `2-4 clean labeled views`, then Blender cleanup if you need production-grade topology.
- The native app now supports layered `Scans (1-10)`, so it can generate multiple candidates and keep the cleanest-looking one using a simple geometry sanity score.
- The native app now supports an optional `Max Triangles` budget, so you can cap the final mesh more cleanly for Blender and game export.
- The main window now also lets you change `Target Triangles` directly, switch back to `Auto`, or turn the cap `Off` without digging into Advanced.
- The native app now supports `Split Reference Sheet` for labeled concept sheets like `2x2`, `1x3`, `1x4`, `3x1`, and `4x1`, then loads the split panels as separate main references you can still retag manually.
- The preview panel now includes `Add Detail Crop`, so you can draw a box on a source image, tag it as `Hand`, `Foot`, `Face`, `Cape / Cloth`, `Armor`, and more, and keep those crops inside the app instead of using external image editing.
- Finished meshes now show a richer `Mesh Health` summary plus a repair recommendation. Bake-map export is prepared through Blender detection, but automatic bake output is still not fully implemented yet.
- The native app now also includes internet-informed `Asset Goal` presets like `Mobile Prop`, `Game Prop`, `Hero Prop`, and `UE5 Nanite Showcase` to suggest a starting triangle budget.
- The native app now also includes `Mesh Style` presets like `Low Poly`, `Stylized`, `Normal / Realistic`, and `Hero Realistic` so the triangle suggestion changes with the look you want.
- The native app now uses a darker two-panel layout with rounded `!` hover-help badges, a top `Plugins` button, and an `Advanced` window for extra controls plus quick shortcuts to the app folder, UI code, and log file.
- A `System Snapshot` card now shows CPU, GPU, RAM, VRAM, and live usage in the main app. GPU temperature appears too if `LibreHardwareMonitor` is running.
- The preview card now switches from reference-image preview to a rendered mesh-result preview after generation finishes.
- The preview card now keeps the mesh-preview path and can also show repaired meshes after `Repair Existing Mesh`.
- The right panel now includes an `AI Assist` tab where you can enter subject type, model/name, and detail notes, then apply smart hints or open targeted web searches for references.
- The left panel now includes a `Reference Basket + Direction Guard` that tracks `Front / Left / Back / Right`, can auto-label views from filenames, can open missing-view searches, and blocks weak vehicle starts before they waste time.
- The main window now adds `Hardware Profile` and `Repair Preset` controls so users can stay conservative on smaller GPUs or run a repair pass without leaving the app.
- The main generate area now splits into `Generate Fast Preview` and `Generate Final Mesh` so you can validate shape direction before spending time on the heavier final pass.
- `Safe Mode / Low VRAM` now forces a weak-PC baseline, and the app warns before generation when the current image size or scan count looks too heavy for the detected hardware.
- Repair presets currently include `Fast Repair`, `Watertight / 3D Print`, `Fix Hands + Feet`, `Fix Cape / Cloth`, and `Experimental Missing Back Fill`.
- Hidden or unseen areas are still estimated, and repaired outputs may still need manual polish.
- Mesh preview renders are cached inside `launchers/preview_cache/`, and old preview/sheet cache entries are auto-trimmed so the workspace does not keep growing forever.
- The `Advanced` window now includes a window opacity slider so you can make the app more or less transparent.
- The `Advanced` window now also includes a soft `Resource Guard` so the app can retry slower with safer chunking when RAM or VRAM gets tight. This is a soft target, not a hard memory cap.
- The cleanup path now also does light geometry repair after Hunyuan output, uses light smoothing, and applies a stricter final decimation pass to hit triangle targets more reliably.
- Source image prep now keeps up to `4K`, upscales weak small images, and falls back when background removal looks suspicious.
- AI Assist hints now slightly change the runtime profile for hard-surface, vehicle, glass, and organic subjects, but they do not retrain Hunyuan or make it ingest live web data on their own.
- A Blender add-on ZIP is now bundled in `blender_addon/3dvisual_mesh_blender.zip` for Blender-side import, triangle audit, and tighter decimation.
