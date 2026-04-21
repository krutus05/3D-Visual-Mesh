from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "3DVisual Mesh"
APP_CHANNEL = "BETA"
APP_VERSION = "0.1.0"
APP_RELEASE_LABEL = f"{APP_NAME} ({APP_CHANNEL}) (Version {APP_VERSION})"
APP_SHARE_DIR_NAME = f"{APP_NAME} Share ({APP_CHANNEL}) (Version {APP_VERSION})"
APP_STARTER_BAT_NAME = f"Start {APP_NAME} ({APP_CHANNEL}) (Version {APP_VERSION}).bat"
APP_INSTALLER_BAT_NAME = f"Install {APP_NAME} ({APP_CHANNEL}) (Version {APP_VERSION}).bat"
APP_SUBTITLE = "Local image-to-mesh helper for Hunyuan on Windows + AMD / NVIDIA"
APP_ID = "yanis.3dvisualmesh"
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def _optional_path_from_env(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if raw:
        return Path(raw).expanduser()
    return None


def _path_from_env(name: str, default: str | Path) -> Path:
    env_path = _optional_path_from_env(name)
    if env_path is not None:
        return env_path
    return Path(default)


def _default_hunyuan_repo() -> Path:
    env_path = _optional_path_from_env("THREEVISUAL_HUNYUAN_REPO")
    if env_path is not None:
        return env_path

    local_repo = WORKSPACE_ROOT / ".vendor" / "Hunyuan3D-2"
    if local_repo.exists():
        return local_repo

    return Path(r"G:\Hunyuan3D-2")


HUNYUAN_REPO = _default_hunyuan_repo()
DESKTOP_DIR = Path.home() / "Desktop"
PLUGINS_DIR = WORKSPACE_ROOT / "plugins"
BLENDER_ADDON_DIR = WORKSPACE_ROOT / "blender_addon"
BLENDER_ADDON_PACKAGE_DIR = BLENDER_ADDON_DIR / "3dvisual_mesh_blender"
BLENDER_ADDON_ZIP = BLENDER_ADDON_DIR / "3dvisual_mesh_blender.zip"
ASSETS_DIR = WORKSPACE_ROOT / "assets"
TEST_INPUT_DIR = ASSETS_DIR / "test_inputs"
ICON_PATH = ASSETS_DIR / "3dvisual_mesh_icon.png"
ICON_ICO_PATH = ASSETS_DIR / "3dvisual_mesh_icon.ico"
DOG_TEST_IMAGE = TEST_INPUT_DIR / "dog_head_square.png"
LOG_FILE = WORKSPACE_ROOT / "launchers" / "3dvisual_mesh.log"
PREVIEW_CACHE_DIR = WORKSPACE_ROOT / "launchers" / "preview_cache"
SHEET_CACHE_DIR = WORKSPACE_ROOT / "launchers" / "sheet_cache"
MENTOR_CASES_DIR = WORKSPACE_ROOT / "launchers" / "mentor_cases"
APP_SETTINGS_PATH = WORKSPACE_ROOT / "launchers" / "app_settings.json"
BLENDER_BRIDGE_DIR = WORKSPACE_ROOT / "launchers" / "blender_bridge"
PLUGIN_TEMPLATE_PATH = PLUGINS_DIR / "plugin_template.py.example"
PREVIEW_CACHE_KEEP_LATEST = 28
PREVIEW_CACHE_MAX_AGE_DAYS = 21
SHEET_CACHE_KEEP_LATEST = 10
SHEET_CACHE_MAX_AGE_DAYS = 45

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIEW_ORDER = ["front", "left", "back", "right"]
DETAIL_VIEW_OPTION = "Detail Crop"
DETAIL_TARGET_OPTIONS = [
    "Auto",
    "Head / Helmet",
    "Face",
    "Torso / Chest",
    "Shoulder",
    "Arm",
    "Hand",
    "Waist / Belt",
    "Leg",
    "Foot / Shoe",
    "Cape / Cloth",
    "Back Detail",
    "Weapon / Accessory",
    "Other",
]
VIEW_OPTIONS = ["Auto", "Front", "Left", "Back", "Right", DETAIL_VIEW_OPTION, "Ignore"]
MAX_PRIMARY_REFERENCES = 4
MAX_DETAIL_REFERENCES = 6
MAX_REFERENCE_IMAGES = MAX_PRIMARY_REFERENCES + MAX_DETAIL_REFERENCES
ASSIST_SUBJECT_TYPES = [
    "Auto",
    "Vehicle",
    "Hard Surface Object",
    "Glass / Transparent",
    "Creature / Character",
    "Product / Prop",
]
VIEW_HINTS = {
    "front": ["front", "frontal", "nose"],
    "left": ["left", "driver"],
    "back": ["back", "rear", "tail"],
    "right": ["right", "passenger"],
}

CLEANUP_OPTIONS = ["Off", "Clean", "Clean + Simpler"]
DEFAULT_CLEANUP = "Clean"
DEFAULT_QUALITY = "High"
DEFAULT_BACKEND = "Local Hunyuan"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MENTOR_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MENTOR_MODEL_SUGGESTIONS = [
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-4o-mini",
]
MENTOR_REASONING_OPTIONS = ["none", "low", "medium", "high", "xhigh"]
DEFAULT_MENTOR_MODEL = os.environ.get("OPENAI_MENTOR_MODEL", "").strip() or "gpt-5.2"
DEFAULT_MENTOR_REASONING_EFFORT = os.environ.get("OPENAI_MENTOR_REASONING", "").strip().lower() or "high"
DEFAULT_MENTOR_TIMEOUT_SECONDS = 120
DEFAULT_MENTOR_USE_WEB_SEARCH = True
DEFAULT_MENTOR_AUTO_SAVE = True
DEFAULT_MENTOR_AUTO_RUN_BEFORE_GENERATE = True
DEFAULT_MENTOR_AUTO_APPLY_ON_GENERATE = True
BEST_MENTOR_MODEL = "gpt-5.2"
BEST_MENTOR_REASONING_EFFORT = "xhigh"
BEST_MENTOR_TIMEOUT_SECONDS = 150
MIN_TRIANGLE_BUDGET = 5000
MAX_TRIANGLE_BUDGET = 200000
TRIANGLE_BUDGET_STEP = 5000
MIN_SAMPLE_COUNT = 1
MAX_SAMPLE_COUNT = 10
MIN_RESOURCE_LIMIT_PERCENT = 35
MAX_RESOURCE_LIMIT_PERCENT = 95
DEFAULT_SOFT_RAM_LIMIT_PERCENT = 82
DEFAULT_SOFT_VRAM_LIMIT_PERCENT = 84
SYSTEM_REFRESH_MS = 5000
SOURCE_MIN_SIDE = 1024
SOURCE_MAX_SIDE = 4608


@dataclass(frozen=True)
class QualityPreset:
    label: str
    steps: int
    guidance_scale: float
    octree_resolution: int
    num_chunks: int
    min_input_side: int
    border_ratio: float
    simplify_target_faces: int
    alpha_clip: int
    contrast_boost: float
    sharpness_boost: float
    unsharp_radius: float
    unsharp_percent: int
    note: str


@dataclass(frozen=True)
class AssetGoalPreset:
    label: str
    suggested_triangles: int | None
    range_text: str
    note: str


@dataclass(frozen=True)
class MeshStylePreset:
    label: str
    triangle_multiplier: float
    note: str


QUALITY_PRESETS = {
    "Fast": QualityPreset(
        label="Fast",
        steps=20,
        guidance_scale=5.5,
        octree_resolution=320,
        num_chunks=32000,
        min_input_side=896,
        border_ratio=0.14,
        simplify_target_faces=45000,
        alpha_clip=10,
        contrast_boost=1.02,
        sharpness_boost=1.06,
        unsharp_radius=0.9,
        unsharp_percent=60,
        note="Quick preview. Lowest detail, fastest turnaround.",
    ),
    "Balanced": QualityPreset(
        label="Balanced",
        steps=30,
        guidance_scale=6.5,
        octree_resolution=384,
        num_chunks=36000,
        min_input_side=1024,
        border_ratio=0.11,
        simplify_target_faces=55000,
        alpha_clip=14,
        contrast_boost=1.05,
        sharpness_boost=1.12,
        unsharp_radius=1.0,
        unsharp_percent=85,
        note="Good default. Better shape and tighter subject framing than Fast.",
    ),
    "High": QualityPreset(
        label="High",
        steps=56,
        guidance_scale=7.9,
        octree_resolution=512,
        num_chunks=52000,
        min_input_side=1536,
        border_ratio=0.075,
        simplify_target_faces=90000,
        alpha_clip=18,
        contrast_boost=1.10,
        sharpness_boost=1.28,
        unsharp_radius=1.18,
        unsharp_percent=118,
        note="High-end local preset for your RX 9070 XT. Stronger source prep, tighter framing, and heavier reconstruction without going fully reckless.",
    ),
    "Max Detail": QualityPreset(
        label="Max Detail",
        steps=84,
        guidance_scale=8.6,
        octree_resolution=576,
        num_chunks=62000,
        min_input_side=2048,
        border_ratio=0.045,
        simplify_target_faces=125000,
        alpha_clip=24,
        contrast_boost=1.14,
        sharpness_boost=1.42,
        unsharp_radius=1.28,
        unsharp_percent=148,
        note="Slowest local preset. Pushes source detail, edge definition, and reconstruction harder for showcase-style local output, but model limits still remain on hard subjects.",
    ),
}

DEFAULT_ASSET_GOAL = "Game Prop"
DEFAULT_MESH_STYLE = "Normal / Realistic"

ASSET_GOAL_PRESETS = {
    "Custom": AssetGoalPreset(
        label="Custom",
        suggested_triangles=None,
        range_text="Manual",
        note="Manual mode. Keep your own triangle budget.",
    ),
    "Mobile Prop": AssetGoalPreset(
        label="Mobile Prop",
        suggested_triangles=10000,
        range_text="6k-12k",
        note="Internet-informed LOD0 guess for mobile or Fortnite-friendly small props. Keep it light and plan aggressive LODs.",
    ),
    "Game Prop": AssetGoalPreset(
        label="Game Prop",
        suggested_triangles=25000,
        range_text="18k-35k",
        note="Good default for a normal real-time prop on PC/console when the silhouette matters but the mesh is not a hero object.",
    ),
    "Hero Prop": AssetGoalPreset(
        label="Hero Prop",
        suggested_triangles=60000,
        range_text="45k-80k",
        note="Use this when the object is seen up close and carries visual attention. Better shading and silhouette, but heavier in-game.",
    ),
    "Character Head / Bust": AssetGoalPreset(
        label="Character Head / Bust",
        suggested_triangles=85000,
        range_text="60k-100k",
        note="Best for heads, creature busts, or close-up statues where facial or surface curvature matters more than full-body efficiency.",
    ),
    "UE5 Nanite Showcase": AssetGoalPreset(
        label="UE5 Nanite Showcase",
        suggested_triangles=150000,
        range_text="100k-150k+",
        note="Only use this when targeting Unreal 5 Nanite or a showcase render. Great detail, but not a normal game-budget target.",
    ),
}

MESH_STYLE_PRESETS = {
    "Low Poly": MeshStylePreset(
        label="Low Poly",
        triangle_multiplier=0.45,
        note="Pushes the budget down hard. Best when you want a simpler shape language, cheaper runtime cost, and less noisy topology.",
    ),
    "Stylized": MeshStylePreset(
        label="Stylized",
        triangle_multiplier=0.70,
        note="Keeps enough shape for appealing silhouettes, but avoids over-spending triangles on tiny surface noise.",
    ),
    "Normal / Realistic": MeshStylePreset(
        label="Normal / Realistic",
        triangle_multiplier=1.00,
        note="Balanced realistic target for most real-time props and close-up objects.",
    ),
    "Hero Realistic": MeshStylePreset(
        label="Hero Realistic",
        triangle_multiplier=1.35,
        note="For closer inspection and stronger silhouette quality. Heavier, but usually worth it for hero assets.",
    ),
    "Dense / Showcase": MeshStylePreset(
        label="Dense / Showcase",
        triangle_multiplier=1.80,
        note="Only for showcase renders, dense scans, or Nanite-style use cases. Not a normal budget for standard game meshes.",
    ),
}
