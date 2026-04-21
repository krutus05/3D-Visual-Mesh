# 3DVisual Mesh (BETA) (Version 0.1.0) Files

3DVisual Mesh is a practical local image-to-mesh helper for Windows. Results are not guaranteed to come out as a 100% finished production mesh every time, and many outputs still benefit from light cleanup or polish in Blender. The project is still a work in progress, and generated meshes can also be used as a starting point for 3D printing tests.

This workspace now keeps the local helper files organized into a few simple folders:

- `app/` - the real app code
- `installer/` - release-package and Windows installer build scripts
- `launchers/` - local `.bat` launchers
- `website/` - public project site for downloads, docs, and open-source landing page
- `START_HERE_EASY.txt` - very short friend-facing startup guide
- `requirements_one_click_windows_amd.txt` - one-file AMD bootstrap stack
- `requirements_one_click_windows_nvidia.txt` - one-file NVIDIA bootstrap stack

Best install path:

- `Install 3DVisual Mesh (BETA) (Version 0.1.0).bat`

Portable start path:

- `Start 3DVisual Mesh (BETA) (Version 0.1.0).bat`

The app code entry point is:

- `app/ui_native.py`
- `THREE_AI_ARCHITECTURE.md` describes the new `Reference AI -> Analysis AI -> Mesh AI` workflow used by the Assist tab
- `OPEN_SOURCE_VISION.md` explains the long-term public goal for the app
- `GAME_DEV_ROADMAP.md` lists the game-asset quality priorities
- `CONTRIBUTING.md` explains what outside developers should improve first

Open source direction:

- The app is being shaped as a practical open-source helper for game developers, not a fake one-click miracle tool.
- The main quality bar is believable geometry, controllable triangles, easier Blender cleanup, and honest limits.

Support:

- The app is free to try and still a work in progress.
- If someone wants to support development, the donation page is:
  `https://ko-fi.com/3dvisualmesh`
- Donations are optional and help fund more app work, plugin support, cleanup tools, and future updates.

Notes:

- The share package now includes both an `installer` path and a `portable one-click bootstrap` launcher.
- The installer copies the app into `%LOCALAPPDATA%\\Programs\\3DVisual Mesh`, creates Desktop and Start Menu shortcuts, and then launches the same bootstrap flow.
- The portable launcher can still create a local venv, auto-detect `AMD` or `NVIDIA`, install the matching torch stack, and download the pinned Hunyuan repo into the package folder.
- Git is optional for the bootstrap path because the launcher can fall back to the pinned GitHub ZIP if Git is not installed yet.
- `installer/build_release_package.ps1` builds a clean share folder and zip for GitHub Releases.
- `installer/build_windows_installer.ps1` is ready for Inno Setup if you want a compiled `Setup.exe` release later.
- The Hunyuan model still resizes images internally, so tight framing and clean backgrounds matter more than raw 4K size.
- Best local quality path is still `1 image` or `2-4 clean labeled views`, then Blender cleanup if you need production-grade topology.
- The native app now supports `Samples (1-4)`, so it can generate multiple candidates and keep the cleanest-looking one using a simple geometry sanity score.
- The native app now supports an optional `Max Triangles` budget, so you can cap the final mesh more cleanly for Blender and game export.
- The main window now also lets you change `Target Triangles` directly, switch back to `Auto`, or turn the cap `Off` without digging into Advanced.
- The native app now also includes internet-informed `Asset Goal` presets like `Mobile Prop`, `Game Prop`, `Hero Prop`, and `UE5 Nanite Showcase` to suggest a starting triangle budget.
- The native app now also includes `Mesh Style` presets like `Low Poly`, `Stylized`, `Normal / Realistic`, and `Hero Realistic` so the triangle suggestion changes with the look you want.
- The native app now uses a darker two-panel layout with rounded `!` hover-help badges, a top `Plugins` button, and an `Advanced` window for extra controls plus quick shortcuts to the app folder, UI code, and log file.
- A `System Snapshot` card now shows CPU, GPU, RAM, VRAM, and live usage in the main app. GPU temperature appears too if `LibreHardwareMonitor` is running.
- The preview card now switches from reference-image preview to a rendered mesh-result preview after generation finishes.
- The right panel now includes an `AI Assist` tab where you can enter subject type, model/name, and detail notes, then apply smart hints or open targeted web searches for references.
- The left panel now includes a `Reference Basket + Direction Guard` that tracks `Front / Left / Back / Right`, can auto-label views from filenames, can open missing-view searches, and blocks weak vehicle starts before they waste time.
- Mesh preview renders are cached inside `launchers/preview_cache/`, and old preview/sheet cache entries are auto-trimmed so the workspace does not keep growing forever.
- The `Advanced` window now includes a window opacity slider so you can make the app more or less transparent.
- The `Advanced` window now also includes a soft `Resource Guard` so the app can retry slower with safer chunking when RAM or VRAM gets tight. This is a soft target, not a hard memory cap.
- The cleanup path now also does light geometry repair after Hunyuan output, uses light smoothing, and applies a stricter final decimation pass to hit triangle targets more reliably.
- Source image prep now keeps up to `4K`, upscales weak small images, and falls back when background removal looks suspicious.
- AI Assist hints now slightly change the runtime profile for hard-surface, vehicle, glass, and organic subjects, but they do not retrain Hunyuan or make it ingest live web data on their own.
- A Blender add-on ZIP is now bundled in `blender_addon/3dvisual_mesh_blender.zip` for Blender-side import, triangle audit, and tighter decimation.
