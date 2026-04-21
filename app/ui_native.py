from __future__ import annotations

import ctypes
import json
import os
import time
import traceback
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote_plus

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from .assistant_workflow import build_direction_guard, build_three_role_workflow, describe_three_role_workflow
from .blender_bridge import BlenderBridgeOptions, detect_blender_executable, launch_blender_cleanup, launch_blender_retopo
from .config import (
    APP_SETTINGS_PATH,
    APP_ID,
    APP_NAME,
    APP_SUBTITLE,
    ASSIST_SUBJECT_TYPES,
    ASSET_GOAL_PRESETS,
    BEST_MENTOR_MODEL,
    BEST_MENTOR_REASONING_EFFORT,
    BEST_MENTOR_TIMEOUT_SECONDS,
    BLENDER_ADDON_DIR,
    BLENDER_ADDON_ZIP,
    CLEANUP_OPTIONS,
    DEFAULT_BACKEND,
    DEFAULT_ASSET_GOAL,
    DEFAULT_CLEANUP,
    DEFAULT_MESH_STYLE,
    DEFAULT_MENTOR_API_KEY,
    DEFAULT_MENTOR_AUTO_APPLY_ON_GENERATE,
    DEFAULT_MENTOR_AUTO_RUN_BEFORE_GENERATE,
    DEFAULT_MENTOR_AUTO_SAVE,
    DEFAULT_MENTOR_MODEL,
    DEFAULT_MENTOR_REASONING_EFFORT,
    DEFAULT_MENTOR_TIMEOUT_SECONDS,
    DEFAULT_MENTOR_USE_WEB_SEARCH,
    DEFAULT_QUALITY,
    DEFAULT_SOFT_RAM_LIMIT_PERCENT,
    DEFAULT_SOFT_VRAM_LIMIT_PERCENT,
    DETAIL_TARGET_OPTIONS,
    DETAIL_VIEW_OPTION,
    DESKTOP_DIR,
    DOG_TEST_IMAGE,
    ICON_ICO_PATH,
    ICON_PATH,
    LOG_FILE,
    MAX_DETAIL_REFERENCES,
    MAX_PRIMARY_REFERENCES,
    MAX_REFERENCE_IMAGES,
    MAX_SAMPLE_COUNT,
    MAX_RESOURCE_LIMIT_PERCENT,
    MAX_TRIANGLE_BUDGET,
    MENTOR_CASES_DIR,
    MENTOR_MODEL_SUGGESTIONS,
    MENTOR_REASONING_OPTIONS,
    MESH_STYLE_PRESETS,
    MIN_RESOURCE_LIMIT_PERCENT,
    MIN_SAMPLE_COUNT,
    MIN_TRIANGLE_BUDGET,
    PLUGIN_TEMPLATE_PATH,
    PLUGINS_DIR,
    QUALITY_PRESETS,
    SUPPORTED_EXTS,
    SYSTEM_REFRESH_MS,
    TRIANGLE_BUDGET_STEP,
    VIEW_OPTIONS,
)
from .generation import (
    GenerationOptions,
    SelectedImage,
    build_subject_profile,
    cleanup_generated_caches,
    generate_mesh,
    guess_detail_crop_from_name,
    guess_detail_target_from_name,
    guess_view_from_name,
    is_detail_view_value,
    load_preview_mesh,
    normalize_detail_target,
    render_mesh_preview_image,
    split_reference_images,
    split_ortho_reference_sheet,
)
from .mentor_cloud import (
    MentorAdvice,
    MentorContext,
    MentorSettings,
    build_mentor_signature,
    request_mentor_advice,
    save_mentor_case,
    summarize_mentor_advice,
)
from .plugin_system import LoadedPlugin, ensure_plugin_template, load_plugins
from .system_monitor import SystemMonitor, describe_snapshot

try:
    import winsound
except ImportError:
    winsound = None


APP_ROOT = Path(__file__).resolve().parent.parent
UI_CODE_PATH = Path(__file__).resolve()

COLORS = {
    "root": "#0b1016",
    "card": "#121924",
    "card_alt": "#0f1520",
    "card_soft": "#151f2d",
    "border": "#273346",
    "accent": "#66b7ff",
    "accent_soft": "#1d3551",
    "text": "#eef4ff",
    "muted": "#99a8bf",
    "drop": "#1a2331",
    "drop_border": "#415067",
    "success": "#8bd6a2",
    "success_soft": "#173424",
    "warning": "#ffd27a",
    "warning_soft": "#3f3114",
    "danger": "#ff8e8e",
    "danger_soft": "#421d22",
}


class HoverTip:
    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 350):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window: tk.Toplevel | None = None
        self.after_id = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self):
        self._cancel()
        if self.tip_window is not None or not self.text.strip():
            return

        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.attributes("-topmost", True)
        self.tip_window.configure(bg=COLORS["card_soft"])

        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() - 2
        self.tip_window.geometry(f"+{x}+{y}")

        label = tk.Label(
            self.tip_window,
            text=self.text,
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=10,
            pady=7,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=260,
        )
        label.pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


@dataclass(frozen=True)
class PreviewGuide:
    label: str
    bounds: tuple[float, float, float, float]
    status: str


class HunyuanMeshApp:
    def __init__(self):
        self._set_windows_identity()

        self.root = TkinterDnD.Tk()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = self._report_callback_exception
        self._set_initial_geometry()

        self.selected_images: list[SelectedImage] = []
        self.row_widgets: list[tuple[tk.Widget, ...]] = []
        self.worker_queue: Queue = Queue()
        self.is_running = False
        self.last_output_path: Path | None = None
        self.pending_options: GenerationOptions | None = None
        self.pending_selection: list[SelectedImage] = []
        self.current_progress = 0.0
        self.target_progress = 0.0
        self.generation_started_at: float | None = None
        self.last_elapsed_seconds = 0.0
        self.progress_markers: list[tuple[float, float]] = []
        self.smoothed_total_seconds: float | None = None
        self.history_predicted_total_seconds: float | None = None
        self.eta_prediction_source = "none"
        self.active_eta_profile: dict[str, object] | None = None
        self.advanced_window: tk.Toplevel | None = None
        self.plugins_window: tk.Toplevel | None = None
        self.max_triangles_spin: tk.Spinbox | None = None
        self.banner_photo = None
        self.icon_photo = None
        self.header_icon_photo = None
        self.preview_photo = None
        self.preview_image_label: tk.Label | None = None
        self.preview_source_path: Path | None = None
        self.preview_reject_blank = False
        self.preview_guides: tuple[PreviewGuide, ...] = ()
        self._preview_refresh_after_id = None
        self.preview_mesh_path: Path | None = None
        self.preview_mesh_object = None
        self.preview_mesh_yaw = 38.0
        self.preview_mesh_pitch = -24.0
        self.preview_drag_origin: tuple[int, int] | None = None
        self._preview_mesh_render_after_id = None
        self._preview_mesh_rendering = False
        self.preview_assist_notebook: ttk.Notebook | None = None
        self.assist_tab: tk.Frame | None = None
        self.assist_notes_box: tk.Text | None = None
        self.run_mentor_button: ttk.Button | None = None
        self.apply_mentor_button: ttk.Button | None = None
        self.open_mentor_case_button: ttk.Button | None = None
        self.open_result_button: ttk.Button | None = None
        self.open_blender_cleanup_button: ttk.Button | None = None
        self.open_blender_retopo_button: ttk.Button | None = None
        self.start_button: ttk.Button | None = None
        self.mentor_badge_label: tk.Label | None = None
        self.hover_tips: list[HoverTip] = []
        self.loaded_plugins: list[LoadedPlugin] = []
        self.scroll_canvas: tk.Canvas | None = None
        self.canvas_window = None
        self._mousewheel_bound = False
        self._scroll_focus_targets: dict[str, tk.Misc] = {}
        self._window_scroll_roots: dict[str, tk.Misc] = {}
        self._wheel_override_widgets: set[str] = set()
        self._scroll_region_after_id = None
        self._scroll_restore_after_id = None
        self._last_canvas_width = 0
        self._scroll_perf_active = False
        self._requested_alpha = 1.0
        self._force_opaque_windows = (os.name == "nt")
        self._system_snapshot_running = False
        self._preview_mesh_error_logged = False
        self.auto_triangle_budget = True
        self.last_preview_path: Path | None = None
        self.last_mentor_advice: MentorAdvice | None = None
        self.last_mentor_case_path: Path | None = None
        self.last_mentor_signature: str | None = None
        self.mentor_running = False
        self.pending_start_after_mentor = False
        self.system_monitor = SystemMonitor()
        self.reference_guard_badge: tk.Label | None = None
        self.blender_status_var = tk.StringVar(value="Blender bridge: checking...")

        self.app_settings = self._load_app_settings()
        app_settings = self.app_settings
        self.run_history = self._sanitize_run_history(app_settings.get("run_history", []))
        self.output_name_var = tk.StringVar(value="3dvisual_mesh")
        self.backend_var = tk.StringVar(value=DEFAULT_BACKEND)
        self.remove_bg_var = tk.BooleanVar(value=True)
        self.keep_raw_copy_var = tk.BooleanVar(value=False)
        self.limit_triangles_var = tk.BooleanVar(value=False)
        self.max_triangles_var = tk.IntVar(value=QUALITY_PRESETS[DEFAULT_QUALITY].simplify_target_faces)
        self.memory_guard_var = tk.BooleanVar(value=True)
        self.soft_ram_limit_var = tk.IntVar(value=DEFAULT_SOFT_RAM_LIMIT_PERCENT)
        self.soft_vram_limit_var = tk.IntVar(value=DEFAULT_SOFT_VRAM_LIMIT_PERCENT)
        self.asset_goal_var = tk.StringVar(value=DEFAULT_ASSET_GOAL)
        self.mesh_style_var = tk.StringVar(value=DEFAULT_MESH_STYLE)
        self.quality_var = tk.StringVar(value=DEFAULT_QUALITY)
        self.cleanup_var = tk.StringVar(value=DEFAULT_CLEANUP)
        self.sample_count_var = tk.StringVar(value=str(MIN_SAMPLE_COUNT))
        self.window_opacity_var = tk.IntVar(value=100)
        self.selection_count_var = tk.StringVar(value=f"0 main + 0 detail (0 tagged) / {MAX_REFERENCE_IMAGES} total")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_eta_var = tk.StringVar(value="ETA --:--")
        self.triangle_summary_var = tk.StringVar(value="Auto")
        self.triangle_mode_var = tk.StringVar(value="Mode: Auto")
        self.summary_var = tk.StringVar(value="")
        self.result_summary_var = tk.StringVar(
            value="No mesh generated yet. Your latest Desktop export and Blender tools will appear here."
        )
        self.quality_note_var = tk.StringVar(value="")
        self.asset_goal_note_var = tk.StringVar(value="")
        self.mesh_style_note_var = tk.StringVar(value="")
        self.preview_title_var = tk.StringVar(value="No preview yet")
        self.preview_note_var = tk.StringVar(value="Add up to 4 main views and 6 optional detail crops. Detail crops can target hands, feet, torso, cape, and other weak parts.")
        self.detail_level_var = tk.StringVar(value="Visual detail: waiting for image")
        self.assist_subject_type_var = tk.StringVar(value="Auto")
        self.assist_model_var = tk.StringVar(value="")
        self.assist_summary_var = tk.StringVar(value="Describe the object here. I will use the notes as build hints and search helpers.")
        self.mentor_api_key_var = tk.StringVar(value=DEFAULT_MENTOR_API_KEY)
        self.mentor_model_var = tk.StringVar(value=DEFAULT_MENTOR_MODEL)
        self.mentor_reasoning_var = tk.StringVar(value=DEFAULT_MENTOR_REASONING_EFFORT)
        self.mentor_timeout_var = tk.StringVar(value=str(DEFAULT_MENTOR_TIMEOUT_SECONDS))
        self.mentor_use_web_search_var = tk.BooleanVar(value=DEFAULT_MENTOR_USE_WEB_SEARCH)
        self.mentor_auto_save_var = tk.BooleanVar(value=DEFAULT_MENTOR_AUTO_SAVE)
        self.mentor_auto_run_var = tk.BooleanVar(value=DEFAULT_MENTOR_AUTO_RUN_BEFORE_GENERATE)
        self.mentor_auto_apply_var = tk.BooleanVar(value=DEFAULT_MENTOR_AUTO_APPLY_ON_GENERATE)
        self.mentor_badge_var = tk.StringVar(value="Mentor Off")
        self.mentor_summary_var = tk.StringVar(
            value="3DVisual Mesh Mentor is optional. Add an OpenAI API key in Advanced, then click Run 3DVisual Mesh Mentor."
        )
        self.blender_exe_var = tk.StringVar(value=str(app_settings.get("blender_executable", "")).strip())
        self.system_cpu_var = tk.StringVar(value="CPU: reading...")
        self.system_gpu_var = tk.StringVar(value="GPU: reading...")
        self.system_live_var = tk.StringVar(value="Live: waiting for usage data...")
        self.system_note_var = tk.StringVar(value="")
        self.reference_guard_var = tk.StringVar(value="Direction Guard: Waiting")
        self.reference_guard_note_var = tk.StringVar(value="Add references to build the basket.")
        self.reference_slots_var = tk.StringVar(value="Front: missing\nLeft: missing\nBack: missing\nRight: missing")
        self.weak_part_summary_var = tk.StringVar(
            value="Weak Part Analyzer: add references to see whether face, hands, feet, cape, or other fragile parts still need focused crops."
        )
        self.refresh_blender_summary()
        try:
            cleanup_generated_caches()
        except Exception:
            self._write_log("Startup cache cleanup failed:\n" + traceback.format_exc())

        self._load_branding()
        self._build_ui()
        self.refresh_plugins(log_message=False)
        self._bind_live_updates()
        self.on_asset_goal_change(log_message=False)
        if self._force_opaque_windows:
            self.window_opacity_var.set(100)
        self._apply_opacity()
        self.root.after(160, self._animate_progress)
        self.root.after(200, self._poll_worker_queue)
        self.root.after(400, self._request_system_snapshot)

    def _set_windows_identity(self):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    def _set_initial_geometry(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1140, max(930, screen_w - 120))
        height = min(790, max(640, screen_h - 140))
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(820, 560)
        self.root.configure(bg=COLORS["root"])

    def _load_branding(self):
        try:
            if ICON_ICO_PATH.exists():
                self.root.iconbitmap(default=str(ICON_ICO_PATH))
        except tk.TclError:
            pass

        try:
            if ICON_PATH.exists():
                self.icon_photo = tk.PhotoImage(file=str(ICON_PATH))
                self.root.iconphoto(True, self.icon_photo)
                icon_image = Image.open(ICON_PATH).resize((56, 56), Image.Resampling.LANCZOS)
                self.header_icon_photo = ImageTk.PhotoImage(icon_image)
        except tk.TclError:
            self.icon_photo = None
            self.header_icon_photo = None

    def _write_log(self, text: str):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_200_000:
                trimmed = LOG_FILE.read_text(encoding="utf-8", errors="ignore")[-240_000:]
                LOG_FILE.write_text(trimmed, encoding="utf-8")
        except Exception:
            pass
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now().isoformat(timespec='seconds')}] {text}\n")

    def _load_app_settings(self) -> dict:
        if not APP_SETTINGS_PATH.exists():
            return {}
        try:
            return json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_app_settings(self):
        APP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(self.app_settings)
        payload["blender_executable"] = self.blender_exe_var.get().strip()
        payload["run_history"] = self.run_history[-48:]
        self.app_settings = payload
        APP_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _sanitize_run_history(self, raw_history) -> list[dict[str, object]]:
        if not isinstance(raw_history, list):
            return []

        def safe_int(value, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        cleaned: list[dict[str, object]] = []
        for item in raw_history[-80:]:
            if not isinstance(item, dict):
                continue
            try:
                duration_seconds = float(item.get("duration_seconds", 0.0))
            except (TypeError, ValueError):
                continue
            if not (5.0 <= duration_seconds <= 21600.0):
                continue

            cleaned.append(
                {
                    "timestamp": str(item.get("timestamp", "")),
                    "duration_seconds": duration_seconds,
                    "backend": str(item.get("backend", "")),
                    "quality": str(item.get("quality", "")),
                    "cleanup": str(item.get("cleanup", "")),
                    "sample_count": safe_int(item.get("sample_count", 0), 0),
                    "subject_type": str(item.get("subject_type", "")),
                    "asset_goal": str(item.get("asset_goal", "")),
                    "mesh_style": str(item.get("mesh_style", "")),
                    "primary_refs": safe_int(item.get("primary_refs", 0), 0),
                    "detail_refs": safe_int(item.get("detail_refs", 0), 0),
                    "detail_label": str(item.get("detail_label", "")),
                    "memory_guard": bool(item.get("memory_guard", False)),
                    "triangle_mode": str(item.get("triangle_mode", "")),
                    "triangle_bucket": safe_int(item.get("triangle_bucket", 0), 0),
                }
            )

        return cleaned[-48:]

    def _triangle_bucket(self, value: int | None) -> int:
        if value is None or value <= 0:
            return 0
        bucket_size = max(5000, TRIANGLE_BUDGET_STEP * 5)
        return int(round(value / bucket_size) * bucket_size)

    def _build_eta_profile(
        self,
        selected_images: list[SelectedImage],
        options: GenerationOptions,
    ) -> dict[str, object]:
        primary_images, detail_images = split_reference_images(selected_images)
        _detail_scale, detail_label = self.estimate_image_complexity()
        recommended_triangles, _reason = self.recommend_triangle_budget()
        triangle_target = options.max_triangles if options.max_triangles is not None else recommended_triangles
        return {
            "backend": options.backend_name,
            "quality": options.quality_name,
            "cleanup": options.cleanup_mode,
            "sample_count": int(options.sample_count),
            "subject_type": options.subject_type or "Auto",
            "asset_goal": self.asset_goal_var.get(),
            "mesh_style": self.mesh_style_var.get(),
            "primary_refs": len(primary_images),
            "detail_refs": len(detail_images),
            "detail_label": detail_label,
            "memory_guard": bool(options.memory_guard),
            "triangle_mode": "manual" if options.max_triangles is not None else "auto",
            "triangle_bucket": self._triangle_bucket(triangle_target),
        }

    def _history_match_score(self, record: dict[str, object], profile: dict[str, object]) -> float:
        score = 0.0

        if record.get("backend") == profile.get("backend"):
            score += 4.0
        if record.get("quality") == profile.get("quality"):
            score += 3.6
        if record.get("cleanup") == profile.get("cleanup"):
            score += 2.4

        try:
            sample_gap = abs(int(record.get("sample_count", 0) or 0) - int(profile.get("sample_count", 0) or 0))
        except (TypeError, ValueError):
            sample_gap = 5
        score += max(0.0, 4.0 - (sample_gap * 1.35))

        if record.get("subject_type") == profile.get("subject_type"):
            score += 2.1
        if record.get("asset_goal") == profile.get("asset_goal"):
            score += 1.4
        if record.get("mesh_style") == profile.get("mesh_style"):
            score += 1.2

        try:
            primary_gap = abs(int(record.get("primary_refs", 0) or 0) - int(profile.get("primary_refs", 0) or 0))
        except (TypeError, ValueError):
            primary_gap = 4
        try:
            detail_gap = abs(int(record.get("detail_refs", 0) or 0) - int(profile.get("detail_refs", 0) or 0))
        except (TypeError, ValueError):
            detail_gap = 2
        score += max(0.0, 1.5 - (primary_gap * 0.75))
        score += max(0.0, 1.0 - (detail_gap * 0.5))

        if record.get("detail_label") == profile.get("detail_label"):
            score += 0.9
        if bool(record.get("memory_guard", False)) == bool(profile.get("memory_guard", False)):
            score += 0.7
        if record.get("triangle_mode") == profile.get("triangle_mode"):
            score += 0.7

        try:
            record_bucket = int(record.get("triangle_bucket", 0) or 0)
            profile_bucket = int(profile.get("triangle_bucket", 0) or 0)
        except (TypeError, ValueError):
            record_bucket = 0
            profile_bucket = 0
        if record_bucket and profile_bucket:
            score += max(0.0, 1.2 - (abs(record_bucket - profile_bucket) / 10000.0))

        return score

    def _predict_duration_from_history(self, profile: dict[str, object] | None) -> float | None:
        if profile is None or not self.run_history:
            return None

        matches: list[tuple[float, float]] = []
        now = datetime.now()
        for record in self.run_history:
            score = self._history_match_score(record, profile)
            if score < 5.0:
                continue

            weight = max(0.5, score) ** 1.35
            timestamp_text = str(record.get("timestamp", ""))
            if timestamp_text:
                try:
                    age_days = max(0.0, (now - datetime.fromisoformat(timestamp_text)).total_seconds() / 86400.0)
                except ValueError:
                    age_days = 0.0
                weight *= max(0.58, 1.0 - min(age_days, 150.0) / 300.0)

            duration_seconds = float(record.get("duration_seconds", 0.0))
            if duration_seconds > 0.0:
                matches.append((weight, duration_seconds))

        if not matches:
            return None

        matches.sort(key=lambda item: item[0], reverse=True)
        top_matches = matches[:8]
        total_weight = sum(weight for weight, _duration in top_matches)
        if total_weight <= 0.0:
            return None

        weighted_average = sum(weight * duration for weight, duration in top_matches) / total_weight
        ordered_durations = sorted(duration for _weight, duration in top_matches)
        midpoint = len(ordered_durations) // 2
        if len(ordered_durations) % 2:
            median_duration = ordered_durations[midpoint]
        else:
            median_duration = (ordered_durations[midpoint - 1] + ordered_durations[midpoint]) / 2.0
        return (weighted_average * 0.72) + (median_duration * 0.28)

    def _predict_duration_from_profile(self, profile: dict[str, object] | None) -> float | None:
        if profile is None:
            return None

        quality_base = {
            "Fast": 80.0,
            "Balanced": 120.0,
            "High": 175.0,
            "Max Detail": 245.0,
        }
        duration = quality_base.get(str(profile.get("quality", "")), 150.0)

        try:
            sample_count = max(1, int(profile.get("sample_count", 1) or 1))
        except (TypeError, ValueError):
            sample_count = 1
        duration += max(0, sample_count - 1) * 26.0

        detail_label = str(profile.get("detail_label", "medium"))
        duration *= {
            "simple": 0.92,
            "medium": 1.0,
            "detailed": 1.15,
        }.get(detail_label, 1.0)

        try:
            primary_refs = max(0, int(profile.get("primary_refs", 0) or 0))
            detail_refs = max(0, int(profile.get("detail_refs", 0) or 0))
        except (TypeError, ValueError):
            primary_refs = 0
            detail_refs = 0
        duration += primary_refs * 6.0
        duration += detail_refs * 12.0

        subject_type = str(profile.get("subject_type", "")).lower()
        if any(word in subject_type for word in ("vehicle", "car", "bike")):
            duration *= 1.12
        elif any(word in subject_type for word in ("character", "human", "creature", "animal")):
            duration *= 1.08
        elif "transparent" in subject_type or "glass" in subject_type:
            duration *= 0.94

        cleanup = str(profile.get("cleanup", ""))
        if cleanup == "Clean":
            duration *= 1.08
        elif cleanup == "Aggressive":
            duration *= 1.14

        if bool(profile.get("memory_guard", False)):
            duration *= 1.04

        try:
            triangle_bucket = int(profile.get("triangle_bucket", 0) or 0)
        except (TypeError, ValueError):
            triangle_bucket = 0
        if triangle_bucket >= 40000:
            duration *= 1.10
        elif triangle_bucket >= 25000:
            duration *= 1.05

        return max(35.0, duration)

    def _remember_completed_run(self, duration_seconds: float):
        if duration_seconds <= 5.0 or self.active_eta_profile is None:
            return

        record = dict(self.active_eta_profile)
        record["duration_seconds"] = float(duration_seconds)
        record["timestamp"] = datetime.now().isoformat(timespec="seconds")
        self.run_history.append(record)
        self.run_history = self._sanitize_run_history(self.run_history)
        self._save_app_settings()

    def _record_progress_marker(self, progress: float):
        if not self.is_running or self.generation_started_at is None:
            return

        elapsed = max(0.0, time.monotonic() - self.generation_started_at)
        if self.progress_markers:
            last_elapsed, last_progress = self.progress_markers[-1]
            if progress <= last_progress + 0.2:
                return
            if (elapsed - last_elapsed) < 0.35 and (progress - last_progress) < 1.0:
                return

        self.progress_markers.append((elapsed, progress))
        self.progress_markers = self.progress_markers[-32:]

    def _estimate_total_from_progress_markers(self, elapsed: float) -> float | None:
        markers = [(point_elapsed, point_progress) for point_elapsed, point_progress in self.progress_markers if point_progress >= 8.0]
        if len(markers) < 2:
            return None

        first_elapsed, first_progress = markers[0]
        last_elapsed, last_progress = markers[-1]
        progress_delta = last_progress - first_progress
        time_delta = last_elapsed - first_elapsed
        if progress_delta < 6.0 or time_delta < 3.0:
            return None

        overall_rate = progress_delta / time_delta
        if overall_rate <= 0.0:
            return None

        overall_total = last_elapsed + max(0.0, 100.0 - last_progress) / overall_rate
        recent_total = None

        recent_markers = markers[-min(4, len(markers)) :]
        if len(recent_markers) >= 2:
            recent_elapsed_delta = recent_markers[-1][0] - recent_markers[0][0]
            recent_progress_delta = recent_markers[-1][1] - recent_markers[0][1]
            if recent_progress_delta >= 4.0 and recent_elapsed_delta >= 2.0:
                recent_rate = recent_progress_delta / recent_elapsed_delta
                if recent_rate > 0.0:
                    recent_total = recent_markers[-1][0] + max(0.0, 100.0 - recent_markers[-1][1]) / recent_rate

        live_total = overall_total if recent_total is None else ((overall_total * 0.62) + (recent_total * 0.38))
        stall_seconds = max(0.0, elapsed - last_elapsed - 3.0)
        if stall_seconds > 0.0:
            live_total += stall_seconds * 0.45

        return max(elapsed + 1.0, live_total)

    def _estimate_total_seconds(self, elapsed: float) -> float | None:
        estimates: list[tuple[float, float]] = []
        last_progress = self.progress_markers[-1][1] if self.progress_markers else 0.0

        if self.history_predicted_total_seconds is not None and self.history_predicted_total_seconds > elapsed:
            if last_progress >= 36.0:
                history_weight = 0.35
            elif last_progress >= 20.0:
                history_weight = 0.52
            elif last_progress >= 8.0:
                history_weight = 0.66
            else:
                history_weight = 0.82
            if self.eta_prediction_source == "heuristic":
                history_weight *= 0.72
            estimates.append((history_weight, self.history_predicted_total_seconds))

        live_total = self._estimate_total_from_progress_markers(elapsed)
        if live_total is not None and live_total > elapsed:
            if last_progress < 15.0:
                live_weight = 0.38
            elif last_progress < 28.0:
                live_weight = 0.58
            elif last_progress < 50.0:
                live_weight = 0.84
            else:
                live_weight = 1.0
            estimates.append((live_weight, live_total))

        if not estimates:
            return None

        estimated_total = sum(weight * total for weight, total in estimates) / sum(weight for weight, _total in estimates)
        if self.smoothed_total_seconds is None:
            self.smoothed_total_seconds = estimated_total
        else:
            difference = abs(estimated_total - self.smoothed_total_seconds)
            alpha = 0.12 if difference < 18.0 else 0.24
            if estimated_total < self.smoothed_total_seconds:
                alpha = max(alpha, 0.18)
            self.smoothed_total_seconds = ((1.0 - alpha) * self.smoothed_total_seconds) + (alpha * estimated_total)

        self.smoothed_total_seconds = max(elapsed + 1.0, self.smoothed_total_seconds)
        return self.smoothed_total_seconds

    def _resolve_blender_executable(self) -> Path | None:
        resolved = detect_blender_executable(self.blender_exe_var.get().strip() or None)
        if resolved is None:
            return None
        normalized = str(resolved)
        if self.blender_exe_var.get().strip() != normalized:
            self.blender_exe_var.set(normalized)
            self._save_app_settings()
        return resolved

    def refresh_blender_summary(self):
        resolved = self._resolve_blender_executable()
        if resolved is not None:
            self.blender_status_var.set(f"Blender ready: {resolved}")
            self.refresh_result_summary()
            return

        raw = self.blender_exe_var.get().strip()
        if raw:
            self.blender_status_var.set("Blender path is saved, but the file is missing now.")
        else:
            self.blender_status_var.set("Blender not found yet. Use Auto Detect or pick blender.exe once.")
        self.refresh_result_summary()

    def refresh_result_summary(self):
        blender_state = self.blender_status_var.get().strip() or "Blender bridge status is waiting."
        if self.last_output_path and self.last_output_path.exists():
            output_path = str(self.last_output_path)
            if len(output_path) > 120:
                output_path = "..." + output_path[-117:]
            self.result_summary_var.set(
                f"Latest result: {self.last_output_path.name}\n"
                f"{output_path}\n"
                f"{blender_state}"
            )
            return

        self.result_summary_var.set(
            "No mesh generated yet.\n"
            "Your latest Desktop export will appear here after the first finished build.\n"
            f"{blender_state}"
        )

    def _bind_live_updates(self):
        for variable in (
            self.mentor_model_var,
            self.mentor_reasoning_var,
            self.mentor_use_web_search_var,
            self.mentor_auto_save_var,
            self.mentor_auto_run_var,
            self.mentor_auto_apply_var,
        ):
            variable.trace_add("write", lambda *_args: self.refresh_mentor_summary())

    def _configure_scroll_region(self, _event=None):
        self._schedule_scroll_region_refresh()

    def _schedule_scroll_region_refresh(self):
        if self.scroll_canvas is None:
            return
        if self._scroll_region_after_id is not None:
            try:
                self.root.after_cancel(self._scroll_region_after_id)
            except Exception:
                pass
        self._scroll_region_after_id = self.root.after(24, self._refresh_scroll_region_now)

    def _refresh_scroll_region_now(self):
        self._scroll_region_after_id = None
        if self.scroll_canvas is None:
            return
        bbox = self.scroll_canvas.bbox("all")
        if bbox:
            self.scroll_canvas.configure(scrollregion=bbox)

    def _resize_scroll_content(self, event):
        if self.scroll_canvas is not None and self.canvas_window is not None:
            new_width = int(event.width)
            if new_width != self._last_canvas_width:
                self._last_canvas_width = new_width
                self.scroll_canvas.itemconfigure(self.canvas_window, width=new_width)
                self._schedule_scroll_region_refresh()

    def _bind_mousewheel(self):
        if self._mousewheel_bound:
            return
        self._mousewheel_bound = True
        self.root.bind_all("<ButtonPress-1>", self._remember_scroll_target_from_event, add="+")
        self.root.bind_all("<ButtonPress-2>", self._remember_scroll_target_from_event, add="+")
        self.root.bind_all("<ButtonPress-3>", self._remember_scroll_target_from_event, add="+")
        self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _managed_windows(self) -> tuple[tk.Toplevel | tk.Tk, ...]:
        windows: list[tk.Toplevel | tk.Tk] = [self.root]
        for window in (self.advanced_window, self.plugins_window):
            if window is not None and window.winfo_exists():
                windows.append(window)
        return tuple(windows)

    def _is_managed_window(self, window: tk.Misc | None) -> bool:
        if window is None:
            return False
        return any(window == managed for managed in self._managed_windows())

    def _resolve_event_toplevel(self, event=None, widget: tk.Misc | None = None):
        target = widget if widget is not None else getattr(event, "widget", None)
        try:
            return target.winfo_toplevel() if target is not None else None
        except Exception:
            return None

    def _window_key(self, window: tk.Misc | None) -> str:
        if window is None:
            return ""
        try:
            return str(window)
        except Exception:
            return ""

    def _register_scroll_root(self, window: tk.Misc | None, target: tk.Misc | None):
        key = self._window_key(window)
        if not key:
            return
        if target is None:
            self._window_scroll_roots.pop(key, None)
            self._scroll_focus_targets.pop(key, None)
            return
        self._window_scroll_roots[key] = target
        self._scroll_focus_targets.setdefault(key, target)

    def _forget_scroll_targets_for_window(self, window: tk.Misc | None):
        key = self._window_key(window)
        if not key:
            return
        self._window_scroll_roots.pop(key, None)
        self._scroll_focus_targets.pop(key, None)

    def _resolve_default_scroll_target(self, top_level: tk.Misc | None):
        key = self._window_key(top_level)
        if key and key in self._window_scroll_roots:
            return self._window_scroll_roots.get(key)
        if top_level == self.root:
            return self.scroll_canvas
        return None

    def _remember_scroll_target(self, top_level: tk.Misc | None, target: tk.Misc | None):
        key = self._window_key(top_level)
        if not key:
            return
        if target is None:
            target = self._resolve_default_scroll_target(top_level)
        if target is None:
            return
        self._scroll_focus_targets[key] = target

    def _current_scroll_target_for_window(self, top_level: tk.Misc | None):
        key = self._window_key(top_level)
        if not key:
            return None
        target = self._scroll_focus_targets.get(key)
        if target is not None:
            try:
                if target.winfo_exists():
                    return target
            except Exception:
                pass
        fallback = self._resolve_default_scroll_target(top_level)
        if fallback is not None:
            self._scroll_focus_targets[key] = fallback
        return fallback

    def _remember_scroll_target_from_event(self, event=None):
        widget = getattr(event, "widget", None)
        top_level = self._resolve_event_toplevel(event, widget)
        if not self._is_managed_window(top_level):
            return
        target = self._resolve_scroll_target(widget, top_level=top_level)
        self._remember_scroll_target(top_level, target)

    def _window_is_foreground(self, window: tk.Misc | None) -> bool:
        if window is None or not self._is_managed_window(window):
            return False

        if os.name == "nt":
            try:
                foreground = int(ctypes.windll.user32.GetForegroundWindow())
                return foreground != 0 and foreground == int(window.winfo_id())
            except Exception:
                pass

        try:
            focus_widget = window.focus_displayof()
        except Exception:
            focus_widget = None

        if focus_widget is None:
            return False

        try:
            return focus_widget.winfo_toplevel() == window
        except Exception:
            return False

    def _mousewheel_delta(self, event) -> int:
        if getattr(event, "delta", 0):
            raw = int(-event.delta / 120)
            if raw != 0:
                return raw
            return -1 if event.delta > 0 else 1
        if getattr(event, "num", None) == 5:
            return 1
        if getattr(event, "num", None) == 4:
            return -1
        return 0

    def _walk_widget_parents(self, widget: tk.Widget | None):
        current = widget
        seen: set[str] = set()
        while current is not None:
            widget_id = str(current)
            if widget_id in seen:
                break
            seen.add(widget_id)
            yield current
            try:
                parent_name = current.winfo_parent()
            except Exception:
                break
            if not parent_name:
                break
            try:
                current = current.nametowidget(parent_name)
            except Exception:
                break

    def _walk_widget_tree(self, widget: tk.Misc | None):
        if widget is None:
            return
        yield widget
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            yield from self._walk_widget_tree(child)

    def _should_override_widget_wheel(self, widget: tk.Misc) -> bool:
        return isinstance(widget, (tk.Text, tk.Listbox, tk.Scale, tk.Spinbox, ttk.Combobox))

    def _bind_controlled_mousewheel_widget(self, widget: tk.Misc):
        widget_id = str(widget)
        if widget_id in self._wheel_override_widgets:
            return
        self._wheel_override_widgets.add(widget_id)
        widget.bind("<MouseWheel>", self._on_controlled_widget_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_controlled_widget_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_controlled_widget_mousewheel, add="+")

    def _bind_controlled_mousewheel_tree(self, widget: tk.Misc | None):
        for current in self._walk_widget_tree(widget):
            if self._should_override_widget_wheel(current):
                self._bind_controlled_mousewheel_widget(current)

    def _on_controlled_widget_mousewheel(self, event):
        self._on_mousewheel(event)
        return "break"

    def _resolve_scroll_target(self, widget: tk.Widget | None, *, top_level: tk.Misc | None = None):
        canvas_target = None
        generic_target = None
        for current in self._walk_widget_parents(widget):
            if isinstance(current, (tk.Text, tk.Listbox)):
                return current
            if isinstance(current, tk.Canvas) and canvas_target is None:
                canvas_target = current
                continue
            if generic_target is None and hasattr(current, "yview_scroll") and callable(getattr(current, "yview_scroll")):
                generic_target = current
        if top_level is None:
            top_level = self._resolve_event_toplevel(widget=widget)
        return canvas_target or generic_target or self._resolve_default_scroll_target(top_level)

    def _on_mousewheel(self, event):
        if self.scroll_canvas is None:
            return

        widget = getattr(event, "widget", None)
        top_level = self._resolve_event_toplevel(event, widget)

        if not self._is_managed_window(top_level):
            return

        delta = self._mousewheel_delta(event)
        if delta:
            target = self._current_scroll_target_for_window(top_level)
            if target is None:
                target = self._resolve_scroll_target(widget, top_level=top_level) or self._resolve_default_scroll_target(top_level)
                self._remember_scroll_target(top_level, target)
            try:
                target.yview_scroll(delta, "units")
            except Exception:
                try:
                    fallback = self._resolve_default_scroll_target(top_level)
                    if fallback is not None:
                        fallback.yview_scroll(delta, "units")
                except Exception:
                    pass

    def _boost_scroll_performance(self):
        if self._scroll_restore_after_id is not None:
            try:
                self.root.after_cancel(self._scroll_restore_after_id)
            except Exception:
                pass
        if not self._scroll_perf_active:
            self._scroll_perf_active = True
            self._apply_opacity()
        self._scroll_restore_after_id = self.root.after(180, self._restore_scroll_performance)

    def _restore_scroll_performance(self):
        self._scroll_restore_after_id = None
        if self._scroll_perf_active:
            self._scroll_perf_active = False
            self._apply_opacity()

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback):
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self._write_log(formatted)
        try:
            messagebox.showerror(
                "3DVisual Mesh Error",
                f"The app hit an error.\n\n{exc_value}\n\nLog:\n{LOG_FILE}",
                parent=self.root,
            )
        except tk.TclError:
            pass

    def _style_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLORS["card"])
        style.configure("TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI", 12, "bold"))
        style.configure("Hero.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI", 23, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Small.TButton", font=("Segoe UI", 9))
        style.configure(
            "TCheckbutton",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Segoe UI", 9),
        )
        style.map(
            "TCheckbutton",
            background=[("active", COLORS["card"])],
            foreground=[("active", COLORS["text"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["card_alt"],
            background=COLORS["card_soft"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLORS["card_alt"])],
            background=[("readonly", COLORS["card_soft"])],
            foreground=[("readonly", COLORS["text"])],
            selectbackground=[("readonly", COLORS["accent_soft"])],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "TProgressbar",
            troughcolor=COLORS["card_alt"],
            background=COLORS["accent"],
            bordercolor=COLORS["card_alt"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
        )
        style.configure("TNotebook", background=COLORS["card"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=COLORS["card_soft"],
            foreground=COLORS["muted"],
            padding=(12, 6),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["card_alt"]), ("active", COLORS["card_soft"])],
            foreground=[("selected", COLORS["text"]), ("active", COLORS["text"])],
        )

    def _make_card(self, parent, *, padx: int = 16, pady: int = 16) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=COLORS["card"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            bd=0,
            padx=padx,
            pady=pady,
        )

    def _create_help_badge(self, parent, tooltip_text: str):
        badge = tk.Canvas(
            parent,
            width=26,
            height=26,
            bg=COLORS["card"],
            highlightthickness=0,
            bd=0,
            cursor="question_arrow",
        )
        badge.create_oval(2, 2, 24, 24, fill=COLORS["accent_soft"], outline=COLORS["accent"], width=1)
        badge.create_text(13, 13, text="!", fill=COLORS["text"], font=("Segoe UI", 10, "bold"))
        self.hover_tips.append(HoverTip(badge, tooltip_text))
        return badge

    def _add_section_header(
        self,
        parent,
        title: str,
        *,
        tooltip_text: str | None = None,
    ):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text=title, style="CardTitle.TLabel").pack(side="left")
        if tooltip_text:
            badge = self._create_help_badge(header, tooltip_text)
            badge.pack(side="left", padx=(8, 0))
        return header

    def _apply_opacity(self, _event=None):
        requested_alpha = max(0.4, min(1.0, self.window_opacity_var.get() / 100.0))
        alpha = 1.0 if self._force_opaque_windows else requested_alpha
        self._requested_alpha = alpha
        live_alpha = 1.0 if (self._scroll_perf_active or self._force_opaque_windows) else alpha
        try:
            self.root.attributes("-alpha", live_alpha)
        except tk.TclError:
            return

        for window in (self.advanced_window, self.plugins_window):
            if window is not None and window.winfo_exists():
                try:
                    window.attributes("-alpha", live_alpha)
                except tk.TclError:
                    pass

    def _build_ui(self):
        self._style_ui()

        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.scroll_canvas = tk.Canvas(
            self.root,
            bg=COLORS["root"],
            highlightthickness=0,
            bd=0,
        )
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self._on_scrollbar)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=scrollbar.set)
        self._register_scroll_root(self.root, self.scroll_canvas)

        shell = tk.Frame(self.scroll_canvas, bg=COLORS["root"], padx=18, pady=18)
        self.canvas_window = self.scroll_canvas.create_window((0, 0), window=shell, anchor="nw")
        shell.bind("<Configure>", self._configure_scroll_region)
        self.scroll_canvas.bind("<Configure>", self._resize_scroll_content)
        self._bind_mousewheel()

        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        header_card = self._make_card(shell, padx=18, pady=16)
        header_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header_card.grid_columnconfigure(1, weight=1)

        if self.header_icon_photo is not None:
            tk.Label(header_card, image=self.header_icon_photo, bg=COLORS["card"]).grid(
                row=0,
                column=0,
                rowspan=3,
                sticky="w",
                padx=(0, 14),
            )

        ttk.Label(header_card, text=APP_NAME, style="Hero.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header_card, text=APP_SUBTITLE, style="Subtitle.TLabel").grid(row=1, column=1, sticky="w", pady=(2, 0))

        header_meta = tk.Frame(header_card, bg=COLORS["card"])
        header_meta.grid(row=2, column=1, sticky="w", pady=(12, 0))
        tk.Label(
            header_meta,
            textvariable=self.selection_count_var,
            bg=COLORS["accent_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=5,
        ).pack(side="left")
        tk.Label(
            header_meta,
            textvariable=self.reference_guard_var,
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=5,
        ).pack(side="left", padx=(8, 0))

        header_actions = ttk.Frame(header_card)
        header_actions.grid(row=0, column=2, rowspan=3, sticky="e")
        header_help = self._create_help_badge(
            header_actions,
            "Choose clean images, set size and quality, then click Start 3D Mesh.",
        )
        header_help.pack(side="left", padx=(0, 10))
        self.mentor_badge_label = tk.Label(
            header_actions,
            textvariable=self.mentor_badge_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=5,
            relief="flat",
            bd=0,
            cursor="hand2",
        )
        self.mentor_badge_label.pack(side="left", padx=(0, 10))
        self.mentor_badge_label.bind("<Button-1>", self.on_mentor_badge_click)
        self.hover_tips.append(
            HoverTip(
                self.mentor_badge_label,
                "Mentor Off = no API key yet. Mentor Ready = teacher can run. Mentor Running = analyzing now. Mentor Applied = current advice matches these images. Mentor Stale = images or notes changed and Mentor should be run again. Click the badge to jump to the right place.",
            )
        )
        ttk.Button(header_actions, text="Advanced", style="Small.TButton", command=self.open_advanced_window).pack(side="left", padx=(0, 8))
        ttk.Button(header_actions, text="Plugins", style="Small.TButton", command=self.open_plugins_window).pack(side="left", padx=(0, 8))
        ttk.Button(header_actions, text="Desktop", style="Small.TButton", command=self.open_desktop_folder).pack(side="left")

        body = tk.Frame(shell, bg=COLORS["root"])
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(2, weight=1)

        left_top = self._make_card(body)
        left_top.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))
        self._add_section_header(
            left_top,
            "References",
            tooltip_text="Drop up to 4 main views plus 6 optional detail crops. Similar zoom and simple backgrounds work best.",
        )

        self.drop_frame = tk.Frame(
            left_top,
            bg=COLORS["drop"],
            highlightthickness=2,
            highlightbackground=COLORS["drop_border"],
            highlightcolor=COLORS["accent"],
            bd=0,
            height=178,
            cursor="hand2",
        )
        self.drop_frame.pack(fill="x")
        self.drop_frame.pack_propagate(False)

        drop_title = tk.Label(
            self.drop_frame,
            text="Drop Images Here",
            bg=COLORS["drop"],
            fg=COLORS["text"],
            font=("Segoe UI", 20, "bold"),
        )
        drop_title.pack(pady=(36, 6))

        drop_subtitle = tk.Label(
            self.drop_frame,
            text="or click to choose files",
            bg=COLORS["drop"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
        )
        drop_subtitle.pack()

        drop_tip = tk.Label(
            self.drop_frame,
            text="Front + side views work best. Use Detail Crop plus body-part focus for hands, feet, torso, cape, or other weak parts.",
            bg=COLORS["drop"],
            fg=COLORS["accent"],
            font=("Segoe UI", 10),
        )
        drop_tip.pack(pady=(10, 0))

        for widget in (self.drop_frame, drop_title, drop_subtitle, drop_tip):
            widget.bind("<Button-1>", lambda _event: self.select_files())
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)

        actions = ttk.Frame(left_top)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Choose Images", command=self.select_files).pack(side="left")
        ttk.Button(actions, text="Split 2x2 Sheet", command=self.split_ortho_sheet).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Load Dog Test", command=self.load_dog_test).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Clear", command=self.clear_images).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.selection_count_var, style="Muted.TLabel").pack(side="right")

        left_bottom = self._make_card(body)
        left_bottom.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        self._add_section_header(
            left_bottom,
            "Selected Images",
            tooltip_text="Set each image to Auto, Front, Left, Back, Right, or Ignore. Detail Crop rows also let you tag a body-part focus.",
        )

        basket_card = tk.Frame(
            left_bottom,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=10,
        )
        basket_card.pack(fill="x", pady=(0, 12))

        basket_top = tk.Frame(basket_card, bg=COLORS["card_soft"])
        basket_top.pack(fill="x")

        self.reference_guard_badge = tk.Label(
            basket_top,
            textvariable=self.reference_guard_var,
            bg=COLORS["accent_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        self.reference_guard_badge.pack(side="left")

        ttk.Button(basket_top, text="Search Missing", style="Small.TButton", command=self.open_missing_view_search).pack(
            side="right"
        )
        ttk.Button(basket_top, text="Auto Label", style="Small.TButton", command=self.auto_label_reference_views).pack(
            side="right", padx=(0, 8)
        )

        tk.Label(
            basket_card,
            textvariable=self.reference_guard_note_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=520,
            anchor="w",
        ).pack(fill="x", pady=(10, 8))

        tk.Label(
            basket_card,
            textvariable=self.reference_slots_var,
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            justify="left",
            anchor="w",
        ).pack(fill="x")

        self.rows_frame = ttk.Frame(left_bottom)
        self.rows_frame.pack(fill="x", pady=(0, 12))
        self.empty_label = ttk.Label(self.rows_frame, text="No images selected yet.", style="Muted.TLabel")
        self.empty_label.pack(anchor="w")

        ttk.Separator(left_bottom, orient="horizontal").pack(fill="x", pady=(0, 12))

        self._add_section_header(
            left_bottom,
            "Status",
            tooltip_text="Shows the active job stage, output path, and errors.",
        )

        status_wrap = tk.Frame(left_bottom, bg=COLORS["card"])
        status_wrap.pack(fill="both", expand=True)

        self.status_box = tk.Text(
            status_wrap,
            height=10,
            wrap="word",
            font=("Consolas", 10),
            bg="#0c1118",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            padx=10,
            pady=10,
        )
        self.status_box.pack(side="left", fill="both", expand=True)
        status_scroll = ttk.Scrollbar(status_wrap, orient="vertical", command=self.status_box.yview)
        status_scroll.pack(side="right", fill="y")
        self.status_box.configure(yscrollcommand=status_scroll.set)
        self.set_status("Add images, then click Start 3D Mesh.")

        right_top = self._make_card(body)
        right_top.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        self._add_section_header(
            right_top,
            "Build Settings",
            tooltip_text="Main choices stay here. Extra controls live in Advanced.",
        )

        ttk.Label(
            right_top,
            text="Engine: Local Hunyuan on Windows + AMD.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        settings_grid = tk.Frame(right_top, bg=COLORS["card"])
        settings_grid.pack(fill="x")
        settings_grid.grid_columnconfigure(0, weight=1)
        settings_grid.grid_columnconfigure(1, weight=1)
        settings_grid.grid_columnconfigure(2, weight=1)

        ttk.Label(settings_grid, text="Output Name").grid(row=0, column=0, sticky="w")
        self.output_entry = tk.Entry(
            settings_grid,
            textvariable=self.output_name_var,
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        self.output_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 10), ipady=4)

        ttk.Label(settings_grid, text="Quality").grid(row=0, column=1, sticky="w")
        quality_box = ttk.Combobox(
            settings_grid,
            textvariable=self.quality_var,
            values=list(QUALITY_PRESETS.keys()),
            state="readonly",
            width=18,
        )
        quality_box.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 10))
        quality_box.bind("<<ComboboxSelected>>", self.on_quality_change)

        ttk.Label(settings_grid, text=f"Scans ({MIN_SAMPLE_COUNT}-{MAX_SAMPLE_COUNT})").grid(row=0, column=2, sticky="w")
        sample_box = ttk.Combobox(
            settings_grid,
            textvariable=self.sample_count_var,
            values=[str(value) for value in range(MIN_SAMPLE_COUNT, MAX_SAMPLE_COUNT + 1)],
            state="readonly",
            width=8,
        )
        sample_box.grid(row=1, column=2, sticky="ew", pady=(2, 10))
        sample_box.bind("<<ComboboxSelected>>", lambda _event: self.on_sample_count_change())

        ttk.Label(settings_grid, text="Asset Goal").grid(row=2, column=0, sticky="w")
        goal_box = ttk.Combobox(
            settings_grid,
            textvariable=self.asset_goal_var,
            values=list(ASSET_GOAL_PRESETS.keys()),
            state="readonly",
            width=22,
        )
        goal_box.grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(2, 10))
        goal_box.bind("<<ComboboxSelected>>", self.on_asset_goal_change)

        ttk.Label(settings_grid, text="Mesh Style").grid(row=2, column=1, sticky="w")
        style_box = ttk.Combobox(
            settings_grid,
            textvariable=self.mesh_style_var,
            values=list(MESH_STYLE_PRESETS.keys()),
            state="readonly",
            width=18,
        )
        style_box.grid(row=3, column=1, sticky="ew", padx=(0, 10), pady=(2, 10))
        style_box.bind("<<ComboboxSelected>>", self.on_mesh_style_change)

        ttk.Label(settings_grid, text="Smart Estimate").grid(row=4, column=0, sticky="w")
        tk.Label(
            settings_grid,
            textvariable=self.detail_level_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=260,
        ).grid(row=5, column=0, columnspan=3, sticky="nw", pady=(4, 0))

        ttk.Label(settings_grid, text="Target Triangles").grid(row=6, column=0, sticky="w", pady=(12, 0))
        triangle_controls = tk.Frame(settings_grid, bg=COLORS["card"])
        triangle_controls.grid(row=7, column=0, columnspan=2, sticky="ew", padx=(0, 10), pady=(2, 0))
        triangle_controls.grid_columnconfigure(0, weight=1)

        self.main_triangle_entry = tk.Entry(
            triangle_controls,
            textvariable=self.max_triangles_var,
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        self.main_triangle_entry.grid(row=0, column=0, sticky="ew", ipady=4)
        self.main_triangle_entry.bind("<KeyRelease>", self._on_main_triangle_changed)
        self.main_triangle_entry.bind("<FocusOut>", self._on_main_triangle_changed)

        ttk.Button(triangle_controls, text="Auto", style="Small.TButton", command=self.use_auto_triangle_budget).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(triangle_controls, text="Off", style="Small.TButton", command=self.disable_triangle_budget).grid(row=0, column=2, padx=(8, 0))

        tk.Label(
            settings_grid,
            textvariable=self.triangle_mode_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=150,
        ).grid(row=7, column=2, sticky="nw", pady=(4, 0))

        summary_card = tk.Frame(
            right_top,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=12,
        )
        summary_card.pack(fill="x", pady=(8, 10))
        ttk.Label(summary_card, text="Target Triangles", style="Muted.TLabel").pack(anchor="w")
        tk.Label(
            summary_card,
            textvariable=self.triangle_summary_var,
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            summary_card,
            textvariable=self.summary_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
        ).pack(anchor="w", pady=(4, 0))

        notes = ttk.Frame(right_top)
        notes.pack(fill="x")
        ttk.Label(notes, textvariable=self.quality_note_var, style="Muted.TLabel", wraplength=340, justify="left").pack(anchor="w")
        ttk.Label(notes, textvariable=self.asset_goal_note_var, style="Muted.TLabel", wraplength=340, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(notes, textvariable=self.mesh_style_note_var, style="Muted.TLabel", wraplength=340, justify="left").pack(anchor="w", pady=(6, 0))

        system_card = tk.Frame(
            right_top,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=12,
        )
        system_card.pack(fill="x", pady=(10, 0))
        tk.Label(system_card, text="System Snapshot", bg=COLORS["card_soft"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(system_card, textvariable=self.system_cpu_var, bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Segoe UI", 9), justify="left", wraplength=330).pack(anchor="w", pady=(6, 0))
        tk.Label(system_card, textvariable=self.system_gpu_var, bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Segoe UI", 9), justify="left", wraplength=330).pack(anchor="w", pady=(4, 0))
        tk.Label(system_card, textvariable=self.system_live_var, bg=COLORS["card_soft"], fg=COLORS["text"], font=("Segoe UI", 9), justify="left", wraplength=330).pack(anchor="w", pady=(6, 0))
        tk.Label(system_card, textvariable=self.system_note_var, bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Segoe UI", 8), justify="left", wraplength=330).pack(anchor="w", pady=(6, 0))

        output_card = self._make_card(body)
        output_card.grid(row=1, column=1, sticky="ew", pady=(0, 10))
        self._add_section_header(
            output_card,
            "Output + Tools",
            tooltip_text="Your latest Desktop export appears here. Blender cleanup and retopo stay nearby instead of living in the footer.",
        )

        tk.Label(
            output_card,
            textvariable=self.result_summary_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
            anchor="w",
        ).pack(fill="x")

        output_actions = ttk.Frame(output_card)
        output_actions.pack(fill="x", pady=(12, 0))
        self.open_result_button = ttk.Button(output_actions, text="Open Result", command=self.open_result, state="disabled")
        self.open_result_button.pack(side="left")
        self.open_blender_cleanup_button = ttk.Button(
            output_actions,
            text="Blender Cleanup",
            command=self.open_in_blender_cleanup,
            state="disabled",
        )
        self.open_blender_cleanup_button.pack(side="left", padx=(8, 0))
        self.open_blender_retopo_button = ttk.Button(
            output_actions,
            text="Blender Retopo",
            command=self.open_in_blender_retopo,
            state="disabled",
        )
        self.open_blender_retopo_button.pack(side="left", padx=(8, 0))
        ttk.Button(output_actions, text="Desktop Folder", style="Small.TButton", command=self.open_desktop_folder).pack(
            side="right"
        )

        right_bottom = self._make_card(body)
        right_bottom.grid(row=2, column=1, sticky="nsew")
        self._add_section_header(
            right_bottom,
            "Preview + Assist",
            tooltip_text="Preview shows the image or mesh result. AI Assist lets you add subject notes and open targeted web searches.",
        )

        notebook = ttk.Notebook(right_bottom)
        notebook.pack(fill="both", expand=True)
        self.preview_assist_notebook = notebook

        preview_tab = tk.Frame(notebook, bg=COLORS["card"])
        assist_tab = tk.Frame(notebook, bg=COLORS["card"])
        self.assist_tab = assist_tab
        notebook.add(preview_tab, text="Preview")
        notebook.add(assist_tab, text="AI Assist")

        preview_card = tk.Frame(
            preview_tab,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=12,
        )
        preview_card.pack(fill="both", expand=True)

        self.preview_image_label = tk.Label(
            preview_card,
            text="No image",
            bg=COLORS["card_alt"],
            fg=COLORS["muted"],
            width=34,
            height=12,
            relief="flat",
        )
        self.preview_image_label.pack(fill="both", expand=True)
        self.preview_image_label.bind("<Configure>", self._schedule_preview_refresh)
        self.preview_image_label.bind("<ButtonPress-1>", self._on_preview_press)
        self.preview_image_label.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_image_label.bind("<ButtonRelease-1>", self._on_preview_release)
        self.preview_image_label.bind("<Double-Button-1>", self._on_preview_reset_view)

        tk.Label(
            preview_card,
            textvariable=self.preview_title_var,
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(10, 2))
        tk.Label(
            preview_card,
            textvariable=self.preview_note_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
            anchor="w",
        ).pack(fill="x")

        assist_shell = tk.Frame(assist_tab, bg=COLORS["card"], padx=2, pady=2)
        assist_shell.pack(fill="both", expand=True)
        assist_shell.grid_columnconfigure(0, weight=1)
        assist_shell.grid_columnconfigure(1, weight=1)

        ttk.Label(assist_shell, text="Subject Type").grid(row=0, column=0, sticky="w")
        assist_type_box = ttk.Combobox(
            assist_shell,
            textvariable=self.assist_subject_type_var,
            values=ASSIST_SUBJECT_TYPES,
            state="readonly",
            width=20,
        )
        assist_type_box.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 10))
        assist_type_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_assist_summary())

        ttk.Label(assist_shell, text="Known Model / Name").grid(row=0, column=1, sticky="w")
        assist_model_entry = tk.Entry(
            assist_shell,
            textvariable=self.assist_model_var,
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        assist_model_entry.grid(row=1, column=1, sticky="ew", pady=(2, 10), ipady=4)
        assist_model_entry.bind("<KeyRelease>", lambda _event: self.refresh_assist_summary())

        ttk.Label(assist_shell, text="Describe Important Details").grid(row=2, column=0, columnspan=2, sticky="w")
        self.assist_notes_box = tk.Text(
            assist_shell,
            height=7,
            wrap="word",
            font=("Segoe UI", 9),
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            padx=8,
            pady=8,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        self.assist_notes_box.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.assist_notes_box.bind("<KeyRelease>", lambda _event: self.refresh_assist_summary())

        assist_actions = ttk.Frame(assist_shell)
        assist_actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Button(assist_actions, text="Apply Smart Hints", command=self.apply_assist_hints).pack(side="left")
        ttk.Button(assist_actions, text="Open Web Search", command=self.open_assist_search).pack(side="left", padx=(8, 0))
        ttk.Button(assist_actions, text="Clear Notes", command=self.clear_assist_notes).pack(side="left", padx=(8, 0))

        assist_card = tk.Frame(
            assist_shell,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=10,
        )
        assist_card.grid(row=5, column=0, columnspan=2, sticky="nsew")
        tk.Label(
            assist_card,
            text="Local Workflow",
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            assist_card,
            textvariable=self.assist_summary_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
        ).pack(anchor="w")

        tk.Frame(assist_card, bg=COLORS["border"], height=1).pack(fill="x", pady=(10, 10))
        tk.Label(
            assist_card,
            text="Weak Part Analyzer",
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            assist_card,
            textvariable=self.weak_part_summary_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
        ).pack(anchor="w")

        mentor_actions = ttk.Frame(assist_shell)
        mentor_actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        self.run_mentor_button = ttk.Button(
            mentor_actions,
            text="Run 3DVisual Mesh Mentor",
            command=self.run_mentor,
        )
        self.run_mentor_button.pack(side="left")
        self.apply_mentor_button = ttk.Button(
            mentor_actions,
            text="Apply Mentor Hints",
            command=self.apply_mentor_hints,
            state="disabled",
        )
        self.apply_mentor_button.pack(side="left", padx=(8, 0))
        self.open_mentor_case_button = ttk.Button(
            mentor_actions,
            text="Open Mentor Case",
            command=self.open_mentor_case,
            state="disabled",
        )
        self.open_mentor_case_button.pack(side="left", padx=(8, 0))

        mentor_card = tk.Frame(
            assist_shell,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=10,
        )
        mentor_card.grid(row=7, column=0, columnspan=2, sticky="nsew")
        tk.Label(
            mentor_card,
            text="3DVisual Mesh Mentor",
            bg=COLORS["card_soft"],
            fg=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            mentor_card,
            textvariable=self.mentor_summary_var,
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
        ).pack(anchor="w")

        footer = self._make_card(shell, padx=18, pady=14)
        footer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1)

        ttk.Label(
            footer,
            text="Dark theme on. Progress stays in the footer; result actions now live in their own card so the main flow feels cleaner.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w")

        footer_actions = ttk.Frame(footer)
        footer_actions.grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(footer_actions, mode="determinate", length=210, maximum=100)
        self.progress.pack(side="left", padx=(0, 10))
        ttk.Label(footer_actions, textvariable=self.progress_percent_var, width=5, anchor="e").pack(side="left", padx=(0, 10))
        ttk.Label(footer_actions, textvariable=self.progress_eta_var, style="Muted.TLabel", width=24, anchor="e").pack(side="left", padx=(0, 12))
        self.start_button = ttk.Button(footer_actions, text="Start 3D Mesh", style="Primary.TButton", command=self.start_generation, width=18)
        self.start_button.pack(side="left")

        self._bind_controlled_mousewheel_tree(self.root)
        self.refresh_assist_summary()
        self._update_preview()
        self.refresh_result_summary()
        self.update_action_state()

    def _on_scrollbar(self, *args):
        if self.scroll_canvas is None:
            return
        self.scroll_canvas.yview(*args)

    def open_advanced_window(self):
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            self.advanced_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title(f"{APP_NAME} - Advanced")
        window.transient(self.root)
        window.resizable(True, True)
        window.configure(bg=COLORS["root"])
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        width = min(860, max(720, screen_w - 260))
        height = min(860, max(620, screen_h - 220))
        x = max(24, min(self.root.winfo_rootx() + 50, screen_w - width - 30))
        y = max(24, min(self.root.winfo_rooty() + 40, screen_h - height - 50))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(700, 560)

        try:
            if ICON_ICO_PATH.exists():
                window.iconbitmap(default=str(ICON_ICO_PATH))
        except tk.TclError:
            pass

        self.advanced_window = window
        outer = tk.Frame(window, bg=COLORS["root"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            outer,
            bg=COLORS["root"],
            highlightthickness=0,
            bd=0,
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        self._register_scroll_root(window, canvas)
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=16)
        scrollbar.pack(side="right", fill="y", padx=(8, 16), pady=16)

        shell_host = tk.Frame(canvas, bg=COLORS["root"])
        shell_window = canvas.create_window((0, 0), window=shell_host, anchor="nw")

        def refresh_advanced_scroll(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_advanced_shell(_event=None):
            canvas.itemconfigure(shell_window, width=max(1, canvas.winfo_width()))
            refresh_advanced_scroll()

        canvas.bind("<Configure>", fit_advanced_shell)
        shell_host.bind("<Configure>", refresh_advanced_scroll)

        shell = self._make_card(shell_host, padx=16, pady=16)
        shell.pack(fill="both", expand=True)

        self._add_section_header(
            shell,
            "Advanced",
            tooltip_text="Extra controls live here so the main screen stays simpler.",
        )

        grid = tk.Frame(shell, bg=COLORS["card"])
        grid.pack(fill="x")
        grid.grid_columnconfigure(1, weight=1)

        ttk.Label(grid, text="Cleanup").grid(row=0, column=0, sticky="w", pady=(0, 8))
        cleanup_box = ttk.Combobox(
            grid,
            textvariable=self.cleanup_var,
            values=CLEANUP_OPTIONS,
            state="readonly",
            width=22,
        )
        cleanup_box.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        cleanup_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_advanced_summary())

        ttk.Checkbutton(grid, text="Remove Background", variable=self.remove_bg_var, command=self.refresh_advanced_summary).grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Checkbutton(grid, text="Keep Raw Copy", variable=self.keep_raw_copy_var, command=self.refresh_advanced_summary).grid(row=1, column=1, sticky="w", pady=(0, 8))

        ttk.Checkbutton(grid, text="Use Max Triangles", variable=self.limit_triangles_var, command=self.on_triangle_toggle).grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.max_triangles_spin = tk.Spinbox(
            grid,
            from_=MIN_TRIANGLE_BUDGET,
            to=MAX_TRIANGLE_BUDGET,
            increment=TRIANGLE_BUDGET_STEP,
            textvariable=self.max_triangles_var,
            command=self._mark_triangle_budget_manual,
            width=14,
            state="normal" if self.limit_triangles_var.get() else "disabled",
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            buttonbackground=COLORS["card_soft"],
        )
        self.max_triangles_spin.grid(row=2, column=1, sticky="w", pady=(0, 8))
        self.max_triangles_spin.bind("<KeyRelease>", self._mark_triangle_budget_manual)
        self.max_triangles_spin.bind("<FocusOut>", self._mark_triangle_budget_manual)

        ttk.Separator(shell, orient="horizontal").pack(fill="x", pady=(12, 12))

        guard_box = tk.Frame(shell, bg=COLORS["card"])
        guard_box.pack(fill="x")
        guard_box.grid_columnconfigure(1, weight=1)

        ttk.Label(guard_box, text="Resource Guard", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            guard_box,
            text="Use slower safe retries when RAM or VRAM gets tight",
            variable=self.memory_guard_var,
            command=self.refresh_advanced_summary,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 8))

        ttk.Label(guard_box, text="Soft RAM Limit (%)").grid(row=2, column=0, sticky="w", pady=(0, 6))
        ram_scale = tk.Scale(
            guard_box,
            from_=MIN_RESOURCE_LIMIT_PERCENT,
            to=MAX_RESOURCE_LIMIT_PERCENT,
            orient="horizontal",
            variable=self.soft_ram_limit_var,
            command=lambda _value: self.refresh_advanced_summary(),
            bg=COLORS["card"],
            fg=COLORS["text"],
            troughcolor=COLORS["card_alt"],
            highlightthickness=0,
            bd=0,
            activebackground=COLORS["accent"],
        )
        ram_scale.grid(row=2, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(guard_box, text="Soft VRAM Limit (%)").grid(row=3, column=0, sticky="w", pady=(0, 6))
        vram_scale = tk.Scale(
            guard_box,
            from_=MIN_RESOURCE_LIMIT_PERCENT,
            to=MAX_RESOURCE_LIMIT_PERCENT,
            orient="horizontal",
            variable=self.soft_vram_limit_var,
            command=lambda _value: self.refresh_advanced_summary(),
            bg=COLORS["card"],
            fg=COLORS["text"],
            troughcolor=COLORS["card_alt"],
            highlightthickness=0,
            bd=0,
            activebackground=COLORS["accent"],
        )
        vram_scale.grid(row=3, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(
            guard_box,
            text="These are soft safety targets, not hard caps. The app responds by using smaller chunk sizes and safer retries before failing.",
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 4))

        ttk.Separator(shell, orient="horizontal").pack(fill="x", pady=(12, 12))

        blender_box = tk.Frame(shell, bg=COLORS["card"])
        blender_box.pack(fill="x")
        blender_box.grid_columnconfigure(1, weight=1)

        ttk.Label(blender_box, text="Blender Bridge", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            blender_box,
            text="One click can open your latest mesh in Blender and run the built-in expert cleanup pass automatically. Use this when the local AI mesh needs better cleanup before final game topology work.",
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))

        ttk.Label(blender_box, text="Blender Executable").grid(row=2, column=0, sticky="w", pady=(0, 6))
        blender_path_entry = tk.Entry(
            blender_box,
            textvariable=self.blender_exe_var,
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        blender_path_entry.grid(row=2, column=1, sticky="ew", pady=(0, 6), ipady=4)
        blender_path_entry.bind("<FocusOut>", lambda _event: self.on_blender_path_changed())

        blender_actions = ttk.Frame(blender_box)
        blender_actions.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Button(blender_actions, text="Browse Blender", command=self.browse_blender_executable).pack(side="left")
        ttk.Button(blender_actions, text="Auto Detect", command=self.auto_detect_blender_executable).pack(side="left", padx=(8, 0))
        ttk.Button(blender_actions, text="Open Blender Cleanup", command=self.open_in_blender_cleanup).pack(side="left", padx=(8, 0))
        ttk.Button(blender_actions, text="Open Blender Retopo", command=self.open_in_blender_retopo).pack(side="left", padx=(8, 0))

        ttk.Label(
            blender_box,
            textvariable=self.blender_status_var,
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        ttk.Separator(shell, orient="horizontal").pack(fill="x", pady=(12, 12))

        mentor_box = tk.Frame(shell, bg=COLORS["card"])
        mentor_box.pack(fill="x")
        mentor_box.grid_columnconfigure(1, weight=1)

        ttk.Label(mentor_box, text="3DVisual Mesh Mentor", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            mentor_box,
            text="Optional cloud teacher. It looks at your references and notes, then returns practical JSON hints you can apply before generation. It can also save mentor cases locally for a future student model.",
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))

        ttk.Label(mentor_box, text="OpenAI API Key").grid(row=2, column=0, sticky="w", pady=(0, 6))
        mentor_key_entry = tk.Entry(
            mentor_box,
            textvariable=self.mentor_api_key_var,
            show="*",
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        mentor_key_entry.grid(row=2, column=1, sticky="ew", pady=(0, 6), ipady=4)

        ttk.Label(mentor_box, text="Mentor Model").grid(row=3, column=0, sticky="w", pady=(0, 6))
        mentor_model_entry = ttk.Combobox(
            mentor_box,
            textvariable=self.mentor_model_var,
            values=MENTOR_MODEL_SUGGESTIONS,
            state="normal",
        )
        mentor_model_entry.grid(row=3, column=1, sticky="ew", pady=(0, 6), ipady=4)
        mentor_model_entry.bind("<<ComboboxSelected>>", lambda _event: self.refresh_mentor_summary())

        mentor_meta = ttk.Frame(mentor_box)
        mentor_meta.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(mentor_meta, text="Timeout (s)").pack(side="left")
        mentor_timeout_entry = tk.Entry(
            mentor_meta,
            textvariable=self.mentor_timeout_var,
            width=8,
            bg=COLORS["card_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        mentor_timeout_entry.pack(side="left", padx=(8, 18), ipady=4)
        ttk.Label(mentor_meta, text="Reasoning").pack(side="left")
        mentor_reasoning_box = ttk.Combobox(
            mentor_meta,
            textvariable=self.mentor_reasoning_var,
            values=MENTOR_REASONING_OPTIONS,
            state="readonly",
            width=9,
        )
        mentor_reasoning_box.pack(side="left", padx=(8, 18))
        mentor_reasoning_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_mentor_summary())

        mentor_flags = ttk.Frame(mentor_box)
        mentor_flags.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Checkbutton(
            mentor_flags,
            text="Allow Web Search",
            variable=self.mentor_use_web_search_var,
        ).pack(side="left")
        ttk.Checkbutton(
            mentor_flags,
            text="Auto-save mentor cases",
            variable=self.mentor_auto_save_var,
        ).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            mentor_flags,
            text="Auto-run before Generate",
            variable=self.mentor_auto_run_var,
        ).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            mentor_flags,
            text="Auto-apply mentor hints",
            variable=self.mentor_auto_apply_var,
        ).pack(side="left", padx=(12, 0))

        ttk.Label(
            mentor_box,
            text="Tip: the API key can also come from OPENAI_API_KEY. Best practical teacher mode is gpt-5.2 with high or xhigh reasoning. If you want cheaper mentor runs, switch the model to gpt-4o-mini. If your screen is small, this window now scrolls.",
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=6, column=0, columnspan=2, sticky="w")

        mentor_actions = ttk.Frame(mentor_box)
        mentor_actions.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(mentor_actions, text="Use Best AI Preset", command=self.apply_best_mentor_preset).pack(side="left")
        ttk.Button(mentor_actions, text="Open Mentor Cases", command=self.open_mentor_cases_folder).pack(side="left", padx=(8, 0))

        ttk.Label(grid, text="Window Opacity").grid(row=3, column=0, sticky="w", pady=(8, 4))
        opacity_scale = tk.Scale(
            grid,
            from_=40,
            to=100,
            orient="horizontal",
            variable=self.window_opacity_var,
            command=self._apply_opacity,
            bg=COLORS["card"],
            fg=COLORS["text"],
            troughcolor=COLORS["card_alt"],
            highlightthickness=0,
            bd=0,
            activebackground=COLORS["accent"],
        )
        if self._force_opaque_windows:
            opacity_scale.configure(state="disabled")
        opacity_scale.grid(row=3, column=1, sticky="ew", pady=(8, 4))
        opacity_note = (
            "Windows stable mode keeps the app fully opaque to avoid redraw glitches in the main window."
            if self._force_opaque_windows
            else "More transparent on the left, more solid on the right."
        )
        ttk.Label(grid, text=opacity_note, style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(
            shell,
            text="Triangle estimate uses asset goal + mesh style + image detail + reference coverage.",
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        ttk.Label(shell, text="Quick shortcuts", style="CardTitle.TLabel").pack(anchor="w", pady=(14, 8))
        shortcuts = ttk.Frame(shell)
        shortcuts.pack(fill="x")
        ttk.Button(shortcuts, text="Open App Folder", command=self.open_app_folder).pack(side="left")
        ttk.Button(shortcuts, text="Open UI Code", command=self.open_ui_code).pack(side="left", padx=(8, 0))
        ttk.Button(shortcuts, text="Open Log", command=self.open_log_file).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(14, 0))

        def close_advanced():
            self._forget_scroll_targets_for_window(window)
            self.advanced_window = None
            self.max_triangles_spin = None
            window.destroy()

        ttk.Button(actions, text="Close", command=close_advanced).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", close_advanced)
        self._bind_controlled_mousewheel_tree(window)
        self._apply_opacity()
        self.refresh_advanced_summary()

    def open_plugins_window(self):
        if self.plugins_window is not None and self.plugins_window.winfo_exists():
            self.plugins_window.lift()
            self.plugins_window.focus_force()
            return

        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        ensure_plugin_template(PLUGIN_TEMPLATE_PATH)

        window = tk.Toplevel(self.root)
        window.title(f"{APP_NAME} - Plugins")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(bg=COLORS["root"])
        window.geometry("+%d+%d" % (self.root.winfo_rootx() + 110, self.root.winfo_rooty() + 110))

        try:
            if ICON_ICO_PATH.exists():
                window.iconbitmap(default=str(ICON_ICO_PATH))
        except tk.TclError:
            pass

        self.plugins_window = window
        shell = self._make_card(window, padx=16, pady=16)
        shell.pack(fill="both", expand=True, padx=16, pady=16)

        self._add_section_header(
            shell,
            "Plugins",
            tooltip_text="Drop plugin .py files into the plugins folder. They load on app start and can be refreshed from here.",
        )

        info = tk.Label(
            shell,
            text="Drop a .py file into the plugins folder, then click Reload Plugins. A starter example file is created for you automatically. Blender add-on files are also bundled separately below.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
        )
        info.pack(anchor="w", pady=(0, 10))

        blender_card = tk.Frame(
            shell,
            bg=COLORS["card_soft"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            padx=12,
            pady=10,
        )
        blender_card.pack(fill="x", pady=4)
        tk.Label(blender_card, text="Blender Add-on", bg=COLORS["card_soft"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(blender_card, text="Built in", bg=COLORS["card_soft"], fg=COLORS["accent"], font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
        tk.Label(
            blender_card,
            text="Use this when you want Blender-side cleanup, triangle audit, stricter decimation, or the newer Blender Retopo flow after the AI mesh is generated.",
            bg=COLORS["card_soft"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        if not self.loaded_plugins:
            empty = tk.Frame(
                shell,
                bg=COLORS["card_soft"],
                highlightthickness=1,
                highlightbackground=COLORS["border"],
                padx=12,
                pady=10,
            )
            empty.pack(fill="x", pady=4)
            tk.Label(empty, text="No custom plugins loaded yet.", bg=COLORS["card_soft"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(empty, text="Use the template file in the plugin folder as your starting point.", bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))

        for plugin in self.loaded_plugins:
            card = tk.Frame(
                shell,
                bg=COLORS["card_soft"],
                highlightthickness=1,
                highlightbackground=COLORS["border"],
                padx=12,
                pady=10,
            )
            card.pack(fill="x", pady=4)
            state_color = COLORS["accent"] if plugin.status.lower().startswith("loaded") else COLORS["danger"]
            tk.Label(card, text=plugin.name, bg=COLORS["card_soft"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(card, text=plugin.status, bg=COLORS["card_soft"], fg=state_color, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
            tk.Label(card, text=plugin.description, bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))
            tk.Label(card, text=str(plugin.path), bg=COLORS["card_soft"], fg=COLORS["muted"], font=("Consolas", 8), wraplength=390, justify="left").pack(anchor="w", pady=(4, 0))
            if plugin.error:
                tk.Label(card, text=plugin.error.splitlines()[-1], bg=COLORS["card_soft"], fg=COLORS["danger"], font=("Segoe UI", 8), wraplength=390, justify="left").pack(anchor="w", pady=(4, 0))

        shortcuts = ttk.Frame(shell)
        shortcuts.pack(fill="x", pady=(12, 0))
        ttk.Button(shortcuts, text="Reload Plugins", command=self.reload_plugins_and_refresh_window).pack(side="left")
        ttk.Button(shortcuts, text="Open Template", command=self.open_plugin_template).pack(side="left", padx=(8, 0))
        ttk.Button(shortcuts, text="Open Plugin Folder", command=self.open_plugins_folder).pack(side="left", padx=(8, 0))
        ttk.Button(shortcuts, text="Open Blender Add-on", command=self.open_blender_addon_folder).pack(side="left", padx=(8, 0))
        ttk.Button(shortcuts, text="Open Add-on ZIP", command=self.open_blender_addon_zip).pack(side="left", padx=(8, 0))
        ttk.Button(shortcuts, text="Open App Folder", command=self.open_app_folder).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(14, 0))

        def close_plugins():
            self._forget_scroll_targets_for_window(window)
            self.plugins_window = None
            window.destroy()

        ttk.Button(actions, text="Close", command=close_plugins).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", close_plugins)
        self._bind_controlled_mousewheel_tree(window)
        self._apply_opacity()

    def open_app_folder(self):
        os.startfile(APP_ROOT)

    def open_ui_code(self):
        os.startfile(UI_CODE_PATH)

    def open_log_file(self):
        if not LOG_FILE.exists():
            self._write_log("Log file created.")
        os.startfile(LOG_FILE)

    def open_plugins_folder(self):
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        ensure_plugin_template(PLUGIN_TEMPLATE_PATH)
        os.startfile(PLUGINS_DIR)

    def open_plugin_template(self):
        ensure_plugin_template(PLUGIN_TEMPLATE_PATH)
        os.startfile(PLUGIN_TEMPLATE_PATH)

    def open_blender_addon_folder(self):
        BLENDER_ADDON_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(BLENDER_ADDON_DIR)

    def open_blender_addon_zip(self):
        if BLENDER_ADDON_ZIP.exists():
            os.startfile(BLENDER_ADDON_ZIP)
        else:
            self.append_status(f"Blender add-on zip not found yet: {BLENDER_ADDON_ZIP}")

    def on_blender_path_changed(self):
        self._save_app_settings()
        self.refresh_blender_summary()

    def browse_blender_executable(self) -> Path | None:
        selected = filedialog.askopenfilename(
            title="Choose blender.exe",
            filetypes=[("Blender", "blender.exe"), ("Executable", "*.exe"), ("All files", "*.*")],
        )
        if not selected:
            return None
        selected_path = Path(selected)
        self.blender_exe_var.set(str(selected_path))
        self._save_app_settings()
        self.refresh_blender_summary()
        self.append_status(f"Blender executable set to: {selected_path}")
        return selected_path

    def auto_detect_blender_executable(self) -> Path | None:
        resolved = detect_blender_executable()
        if resolved is None:
            self.blender_status_var.set("Blender auto-detect failed. Pick blender.exe manually.")
            self.append_status("Blender auto-detect did not find an install. Pick blender.exe manually in Advanced.")
            return None
        self.blender_exe_var.set(str(resolved))
        self._save_app_settings()
        self.refresh_blender_summary()
        self.append_status(f"Blender detected: {resolved}")
        return resolved

    def _prepare_blender_launch(self) -> tuple[Path, Path] | None:
        if self.last_output_path is None or not self.last_output_path.exists():
            messagebox.showwarning("No result", "Generate a mesh first so Blender has something to open.", parent=self.root)
            return None

        blender_executable = self._resolve_blender_executable()
        if blender_executable is None:
            self.append_status("Blender was not found automatically. Pick blender.exe once in Advanced.")
            chosen = self.browse_blender_executable()
            if chosen is None:
                messagebox.showwarning("Blender not set", "Choose blender.exe once in Advanced, then try again.", parent=self.root)
                return None
            blender_executable = self._resolve_blender_executable()
            if blender_executable is None:
                messagebox.showwarning("Blender not set", "That Blender path does not look valid. Pick blender.exe and try again.", parent=self.root)
                return None
        return blender_executable, self.last_output_path

    def _resolve_blender_triangle_target(self) -> int:
        if self.limit_triangles_var.get():
            try:
                triangle_target = int(self.max_triangles_var.get())
            except (tk.TclError, ValueError):
                triangle_target = QUALITY_PRESETS[self.quality_var.get()].simplify_target_faces
        else:
            recommended, _ = self.recommend_triangle_budget()
            triangle_target = recommended or QUALITY_PRESETS[self.quality_var.get()].simplify_target_faces
        return max(MIN_TRIANGLE_BUDGET, min(MAX_TRIANGLE_BUDGET, int(triangle_target)))

    def _build_blender_retopo_options(self, mesh_path: Path) -> BlenderBridgeOptions:
        triangle_target = self._resolve_blender_triangle_target()
        mesh_style = self.mesh_style_var.get()
        quad_ratio = {
            "Low Poly": 0.32,
            "Stylized": 0.40,
            "Normal / Realistic": 0.50,
            "Hero Realistic": 0.60,
            "Dense / Showcase": 0.72,
        }.get(mesh_style, 0.50)

        profile = build_subject_profile(
            self.assist_subject_type_var.get(),
            self.assist_model_var.get().strip(),
            self.get_assist_notes(),
        )
        if profile.is_vehicle:
            quad_ratio += 0.04
        elif profile.is_organic:
            quad_ratio = max(0.30, quad_ratio - 0.05)

        quadriflow_faces = int(round((triangle_target * quad_ratio) / 250.0) * 250)
        quadriflow_faces = max(2000, min(120000, quadriflow_faces))

        notes_lower = self.get_assist_notes().lower()
        asymmetry_markers = ("asym", "asymmetric", "modified", "damaged", "broken", "one-sided")
        use_symmetry = (
            (profile.is_vehicle or profile.is_transparent)
            and not any(marker in notes_lower for marker in asymmetry_markers)
        )

        preserve_sharp = profile.is_vehicle or profile.is_hard_surface or profile.is_transparent
        auto_smooth_angle = 52.0 if preserve_sharp else 38.0

        return BlenderBridgeOptions(
            mesh_path=mesh_path,
            mode="retopo",
            quadriflow_target_faces=quadriflow_faces,
            quadriflow_preserve_sharp=preserve_sharp,
            quadriflow_preserve_boundary=True,
            quadriflow_use_symmetry=use_symmetry,
            quadriflow_seed=0,
            merge_distance=0.0005,
            island_min_faces=28 if preserve_sharp else 20,
            island_ratio=0.006 if preserve_sharp else 0.004,
            auto_smooth_angle_deg=auto_smooth_angle,
            use_weighted_normals=preserve_sharp,
            keep_source_copy=True,
        )

    def open_in_blender_cleanup(self):
        prepared = self._prepare_blender_launch()
        if prepared is None:
            return
        blender_executable, mesh_path = prepared

        try:
            script_path = launch_blender_cleanup(blender_executable, mesh_path)
        except Exception as exc:
            self._write_log("Blender cleanup launch failed:\n" + traceback.format_exc())
            messagebox.showerror("Blender launch failed", str(exc), parent=self.root)
            return

        self.append_status(
            f"Opened Blender cleanup session for {mesh_path.name}.\n"
            f"Blender: {blender_executable}\n"
            f"Bridge script: {script_path}"
        )
        self.root.bell()

    def open_in_blender_retopo(self):
        prepared = self._prepare_blender_launch()
        if prepared is None:
            return
        blender_executable, mesh_path = prepared
        options = self._build_blender_retopo_options(mesh_path)

        try:
            script_path = launch_blender_retopo(blender_executable, options)
        except Exception as exc:
            self._write_log("Blender retopo launch failed:\n" + traceback.format_exc())
            messagebox.showerror("Blender retopo failed", str(exc), parent=self.root)
            return

        triangle_target = self._resolve_blender_triangle_target()
        self.append_status(
            f"Opened Blender retopo session for {mesh_path.name}.\n"
            f"Triangle goal: {triangle_target:,} | QuadriFlow target: {options.quadriflow_target_faces:,} faces\n"
            f"Preserve sharp: {'On' if options.quadriflow_preserve_sharp else 'Off'} | "
            f"Symmetry: {'On' if options.quadriflow_use_symmetry else 'Off'}\n"
            f"Blender: {blender_executable}\n"
            f"Bridge script: {script_path}"
        )
        self.root.bell()

    def refresh_plugins(self, *, log_message: bool = True):
        ensure_plugin_template(PLUGIN_TEMPLATE_PATH)
        previous_paths = {plugin.path for plugin in self.loaded_plugins}
        self.loaded_plugins = load_plugins(self, PLUGINS_DIR)

        if log_message:
            loaded_count = sum(1 for plugin in self.loaded_plugins if plugin.status.lower().startswith("loaded"))
            if self.loaded_plugins:
                self.append_status(f"Plugins refreshed: {loaded_count} loaded, {len(self.loaded_plugins)} found.")
            else:
                self.append_status("Plugins refreshed. No custom plugins found yet.")
        else:
            new_paths = [plugin.path for plugin in self.loaded_plugins if plugin.path not in previous_paths]
            if new_paths:
                self.append_status(f"Detected {len(new_paths)} new plugin file(s).")

    def reload_plugins_and_refresh_window(self):
        self.refresh_plugins(log_message=True)
        if self.plugins_window is not None and self.plugins_window.winfo_exists():
            self.plugins_window.destroy()
            self.plugins_window = None
        self.open_plugins_window()

    def update_selection_count(self):
        primary_images, detail_images = split_reference_images(self.selected_images)
        focused_detail_images = sum(1 for item in detail_images if normalize_detail_target(item.detail_target) != "Auto")
        self.selection_count_var.set(
            f"{len(primary_images)} main + {len(detail_images)} detail ({focused_detail_images} tagged) / {MAX_REFERENCE_IMAGES} total"
        )

    def _mark_triangle_budget_manual(self, _event=None):
        if self.asset_goal_var.get() != "Custom":
            self.auto_triangle_budget = False
        self.refresh_advanced_summary()

    def estimate_image_complexity(self) -> tuple[float, str]:
        if not self.selected_images:
            return 1.0, "waiting for image"

        primary_images, detail_images = split_reference_images(self.selected_images)
        source_images = primary_images if primary_images else detail_images
        samples: list[float] = []
        for item in source_images[:max(MAX_PRIMARY_REFERENCES, MAX_DETAIL_REFERENCES)]:
            try:
                with Image.open(item.path) as source:
                    grayscale = source.convert("L")
                    grayscale.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    contrast = ImageStat.Stat(grayscale).stddev[0]
                    edges = grayscale.filter(ImageFilter.FIND_EDGES)
                    edge_mean = ImageStat.Stat(edges).mean[0]
                    texture = grayscale.filter(ImageFilter.DETAIL)
                    texture_std = ImageStat.Stat(texture).stddev[0]
                    detail_signal = min(
                        1.0,
                        ((contrast / 78.0) * 0.42)
                        + ((edge_mean / 40.0) * 0.34)
                        + ((texture_std / 55.0) * 0.24),
                    )
                    samples.append(0.84 + (detail_signal * 0.52))
            except Exception:
                continue

        if not samples:
            return 1.0, "normal"

        score = sum(samples) / len(samples)
        if score < 0.94:
            return score, "simple"
        if score < 1.10:
            return score, "medium"
        return score, "detailed"

    def _update_preview(self):
        if self.preview_image_label is None:
            return

        if not self.selected_images:
            self.last_preview_path = None
            self.preview_guides = ()
            self._clear_preview_mesh_state()
            self.preview_source_path = None
            self.preview_reject_blank = False
            self.preview_photo = None
            self.preview_image_label.configure(image="", text="No image", compound="center")
            self.preview_title_var.set("No preview yet")
            self.preview_note_var.set("Add up to 4 main views and 6 optional detail crops. Tag detail crops by body part when you can.")
            self.detail_level_var.set("Visual detail: waiting for image")
            return

        primary_images, detail_images = split_reference_images(self.selected_images)
        first = self._select_preview_item(primary_images, detail_images)
        self.last_preview_path = None
        self._clear_preview_mesh_state()
        preview_guide_labels = self._configure_preview_guides(first)
        try:
            self._load_preview_file(first.path)
        except Exception:
            self.preview_guides = ()
            self.preview_source_path = None
            self.preview_reject_blank = False
            self.preview_photo = None
            self.preview_image_label.configure(image="", text="Preview failed", compound="center")
            self.preview_title_var.set(first.path.name)
            self.preview_note_var.set("The image could not be previewed, but it is still selected.")
            detail_scale, detail_label = self.estimate_image_complexity()
            self.detail_level_var.set(f"Visual detail: {detail_label.title()} ({detail_scale:.2f}x)")
            return

        detail_scale, detail_label = self.estimate_image_complexity()
        self.preview_title_var.set(first.path.name)
        primary_images, detail_images = split_reference_images(self.selected_images)
        detail_focus: list[str] = []
        for item in detail_images[:4]:
            detail_target = normalize_detail_target(item.detail_target)
            if detail_target != "Auto" and detail_target not in detail_focus:
                detail_focus.append(detail_target)
        if detail_focus:
            detail_focus_note = f" Focus: {', '.join(detail_focus)}."
        else:
            detail_focus_note = ""
        if preview_guide_labels:
            preview_guide_note = (
                f" Suggested crop guides: {', '.join(preview_guide_labels)}. "
                "Red = missing, gold = generic, blue = watch."
            )
        else:
            preview_guide_note = ""
        self.preview_note_var.set(
            f"{len(primary_images)} main view(s) and {len(detail_images)} detail crop(s) selected. "
            f"This is the setup preview. After generation this switches to the mesh result."
            f"{detail_focus_note}{preview_guide_note}"
        )
        self.detail_level_var.set(f"Visual detail: {detail_label.title()} ({detail_scale:.2f}x)")

    def _image_looks_blank(self, image: Image.Image) -> bool:
        stat = ImageStat.Stat(image.convert("RGB"))
        if max(stat.stddev) < 1.5:
            return True
        extrema = stat.extrema
        return max(high - low for low, high in extrema) < 4

    def _resolved_view_for_item(self, item: SelectedImage) -> str:
        value = (item.view_value or "Auto").strip()
        lowered = value.lower()
        if not value or lowered == "ignore":
            return "Ignore"
        if is_detail_view_value(value):
            return DETAIL_VIEW_OPTION
        if lowered == "auto":
            guessed = guess_view_from_name(item.path)
            if guessed:
                return guessed.capitalize()
            return "Auto"
        return value.capitalize()

    def _select_preview_item(
        self,
        primary_images: list[SelectedImage],
        detail_images: list[SelectedImage],
    ) -> SelectedImage:
        if primary_images:
            ranked: list[tuple[int, int, SelectedImage]] = []
            for index, item in enumerate(primary_images):
                resolved_view = self._resolved_view_for_item(item)
                priority = {
                    "Front": 0,
                    "Auto": 1,
                    "Left": 2,
                    "Right": 2,
                    "Back": 3,
                }.get(resolved_view, 4)
                ranked.append((priority, index, item))
            ranked.sort(key=lambda row: (row[0], row[1]))
            return ranked[0][2]
        if detail_images:
            return detail_images[0]
        return self.selected_images[0]

    def _estimate_subject_bounds(self, image: Image.Image) -> tuple[float, float, float, float]:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        if width <= 0 or height <= 0:
            return (0.14, 0.08, 0.86, 0.96)

        alpha = rgba.getchannel("A")
        bbox = None
        try:
            alpha_min, alpha_max = alpha.getextrema()
        except Exception:
            alpha_min, alpha_max = (255, 255)

        if alpha_min < 250 and alpha_max > 10:
            alpha_mask = alpha.point(lambda value: 255 if value > 18 else 0)
            bbox = alpha_mask.getbbox()

        if bbox is None:
            rgb = rgba.convert("RGB")
            border = max(3, min(width, height) // 40)
            border_samples = [
                rgb.crop((0, 0, width, border)),
                rgb.crop((0, height - border, width, height)),
                rgb.crop((0, 0, border, height)),
                rgb.crop((width - border, 0, width, height)),
            ]
            means = [ImageStat.Stat(sample).mean for sample in border_samples if sample.size[0] > 0 and sample.size[1] > 0]
            if means:
                bg_color = tuple(
                    int(round(sum(sample[channel] for sample in means) / len(means)))
                    for channel in range(3)
                )
            else:
                bg_color = (245, 245, 245)

            bg_image = Image.new("RGB", rgb.size, bg_color)
            diff = ImageChops.difference(rgb, bg_image).convert("L")
            blur_radius = max(1, min(width, height) // 180)
            diff = diff.filter(ImageFilter.GaussianBlur(blur_radius))
            threshold = 18 if max(bg_color) > 150 else 28
            mask = diff.point(lambda value: 255 if value > threshold else 0)
            bbox = mask.getbbox()

        if bbox is None:
            return (0.14, 0.08, 0.86, 0.96)

        left, top, right, bottom = bbox
        if (right - left) < max(20, width // 6) or (bottom - top) < max(20, height // 6):
            return (0.14, 0.08, 0.86, 0.96)

        pad_x = max(8, int((right - left) * 0.06))
        pad_y = max(8, int((bottom - top) * 0.05))
        left = max(0, left - pad_x)
        top = max(0, top - pad_y)
        right = min(width, right + pad_x)
        bottom = min(height, bottom + pad_y)
        return (
            left / width,
            top / height,
            right / width,
            bottom / height,
        )

    def _guide_color_for_status(self, status: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        normalized = (status or "").strip().lower()
        if normalized == "missing":
            return (255, 120, 120, 86), (255, 134, 134, 255)
        if normalized == "generic":
            return (255, 201, 92, 82), (255, 210, 122, 255)
        return (102, 183, 255, 74), (102, 183, 255, 255)

    def _scale_local_box(
        self,
        subject_bounds: tuple[float, float, float, float],
        local_bounds: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        left, top, right, bottom = subject_bounds
        box_left, box_top, box_right, box_bottom = local_bounds
        width = max(0.08, right - left)
        height = max(0.08, bottom - top)
        return (
            max(0.0, min(1.0, left + (width * box_left))),
            max(0.0, min(1.0, top + (height * box_top))),
            max(0.0, min(1.0, left + (width * box_right))),
            max(0.0, min(1.0, top + (height * box_bottom))),
        )

    def _build_guides_for_part(
        self,
        part: str,
        status: str,
        subject_bounds: tuple[float, float, float, float],
        resolved_view: str,
    ) -> list[PreviewGuide]:
        view = resolved_view if resolved_view in {"Front", "Back", "Left", "Right"} else "Front"

        def make(label: str, box: tuple[float, float, float, float]) -> PreviewGuide:
            return PreviewGuide(label=label, bounds=self._scale_local_box(subject_bounds, box), status=status)

        local_boxes: list[tuple[str, tuple[float, float, float, float]]] = []

        if part == "Face":
            local_boxes = [("Face", (0.35, 0.03, 0.65, 0.24))]
        elif part == "Head / Helmet":
            local_boxes = [("Head / Helmet", (0.28, 0.01, 0.72, 0.26))]
        elif part == "Torso / Chest":
            local_boxes = [("Torso / Chest", (0.24, 0.24, 0.76, 0.55))]
        elif part == "Shoulder":
            local_boxes = [
                ("Shoulder", (0.10, 0.18, 0.34, 0.38)),
                ("Shoulder", (0.66, 0.18, 0.90, 0.38)),
            ]
        elif part == "Arm":
            if view == "Left":
                local_boxes = [("Arm", (0.00, 0.28, 0.28, 0.62))]
            elif view == "Right":
                local_boxes = [("Arm", (0.72, 0.28, 1.00, 0.62))]
            else:
                local_boxes = [
                    ("Arm", (0.00, 0.28, 0.23, 0.62)),
                    ("Arm", (0.77, 0.28, 1.00, 0.62)),
                ]
        elif part == "Hand":
            if view == "Left":
                local_boxes = [("Hand", (0.00, 0.44, 0.22, 0.67))]
            elif view == "Right":
                local_boxes = [("Hand", (0.78, 0.44, 1.00, 0.67))]
            else:
                local_boxes = [
                    ("Hand", (0.00, 0.44, 0.20, 0.68)),
                    ("Hand", (0.80, 0.44, 1.00, 0.68)),
                ]
        elif part == "Waist / Belt":
            local_boxes = [("Waist / Belt", (0.30, 0.53, 0.70, 0.69))]
        elif part == "Leg":
            local_boxes = [
                ("Leg", (0.26, 0.62, 0.46, 0.92)),
                ("Leg", (0.54, 0.62, 0.74, 0.92)),
            ]
        elif part == "Foot / Shoe":
            local_boxes = [
                ("Foot / Shoe", (0.20, 0.84, 0.44, 1.00)),
                ("Foot / Shoe", (0.56, 0.84, 0.80, 1.00)),
            ]
        elif part == "Cape / Cloth":
            if view == "Back":
                local_boxes = [("Cape / Cloth", (0.18, 0.20, 0.82, 0.98))]
            elif view == "Left":
                local_boxes = [("Cape / Cloth", (0.60, 0.18, 1.00, 0.98))]
            elif view == "Right":
                local_boxes = [("Cape / Cloth", (0.00, 0.18, 0.40, 0.98))]
            else:
                local_boxes = [("Cape / Cloth", (0.10, 0.22, 0.90, 0.98))]
        elif part == "Back Detail":
            if view == "Back":
                local_boxes = [("Back Detail", (0.22, 0.18, 0.78, 0.84))]
            elif view == "Left":
                local_boxes = [("Back Detail", (0.56, 0.22, 0.94, 0.82))]
            elif view == "Right":
                local_boxes = [("Back Detail", (0.06, 0.22, 0.44, 0.82))]
            else:
                local_boxes = [("Back Detail", (0.18, 0.18, 0.82, 0.84))]
        elif part == "Weapon / Accessory":
            if view == "Left":
                local_boxes = [("Weapon / Accessory", (0.00, 0.24, 0.24, 0.92))]
            elif view == "Right":
                local_boxes = [("Weapon / Accessory", (0.76, 0.24, 1.00, 0.92))]
            else:
                local_boxes = [("Weapon / Accessory", (0.70, 0.20, 0.98, 0.92))]

        return [make(label, box) for label, box in local_boxes]

    def _configure_preview_guides(self, preview_item: SelectedImage) -> tuple[str, ...]:
        self.preview_guides = ()
        if is_detail_view_value(preview_item.view_value):
            return ()

        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        target_parts = [
            part
            for part in workflow.analysis.weak_parts
            if part.status in {"missing", "generic", "watch"}
        ]
        if not target_parts:
            return ()

        try:
            with Image.open(preview_item.path) as source:
                subject_bounds = self._estimate_subject_bounds(source.convert("RGBA"))
        except Exception:
            subject_bounds = (0.14, 0.08, 0.86, 0.96)

        resolved_view = self._resolved_view_for_item(preview_item)
        guides: list[PreviewGuide] = []
        shown_labels: list[str] = []
        for part in target_parts[:5]:
            part_guides = self._build_guides_for_part(part.part, part.status, subject_bounds, resolved_view)
            if not part_guides:
                continue
            guides.extend(part_guides)
            if part.part not in shown_labels:
                shown_labels.append(part.part)

        self.preview_guides = tuple(guides)
        return tuple(shown_labels)

    def _apply_preview_guides(self, preview: Image.Image) -> Image.Image:
        if not self.preview_guides:
            return preview

        image = preview.convert("RGBA")
        draw = ImageDraw.Draw(image, "RGBA")
        width, height = image.size
        min_side = max(1, min(width, height))
        line_width = max(2, min_side // 180)
        label_padding_x = max(5, min_side // 85)
        label_padding_y = max(3, min_side // 120)

        for guide in self.preview_guides:
            fill_rgba, outline_rgba = self._guide_color_for_status(guide.status)
            left, top, right, bottom = guide.bounds
            box = (
                int(round(left * width)),
                int(round(top * height)),
                int(round(right * width)),
                int(round(bottom * height)),
            )
            box = (
                max(0, min(width - 1, box[0])),
                max(0, min(height - 1, box[1])),
                max(1, min(width, box[2])),
                max(1, min(height, box[3])),
            )
            if box[2] - box[0] < 14 or box[3] - box[1] < 14:
                continue

            draw.rounded_rectangle(box, radius=max(8, min_side // 35), fill=fill_rgba, outline=outline_rgba, width=line_width)
            try:
                label_bbox = draw.textbbox((0, 0), guide.label)
                label_width = (label_bbox[2] - label_bbox[0]) + (label_padding_x * 2)
                label_height = (label_bbox[3] - label_bbox[1]) + (label_padding_y * 2)
            except AttributeError:
                label_width = int(draw.textlength(guide.label)) + (label_padding_x * 2)
                label_height = max(16, min_side // 18) + (label_padding_y * 2)
            label_x = max(0, min(width - label_width, box[0] + 6))
            label_y = max(0, box[1] - label_height - 6)
            label_box = (
                label_x,
                label_y,
                min(width, label_x + label_width),
                min(height, label_y + label_height),
            )
            draw.rounded_rectangle(label_box, radius=max(6, min_side // 42), fill=outline_rgba)
            draw.text(
                (label_box[0] + label_padding_x, label_box[1] + label_padding_y),
                guide.label,
                fill=COLORS["root"],
            )

        return image

    def _preview_target_size(self) -> tuple[int, int]:
        if self.preview_image_label is None:
            return 420, 320

        width = max(260, self.preview_image_label.winfo_width() - 24)
        height = max(220, self.preview_image_label.winfo_height() - 24)
        return width, height

    def _fit_preview_image(self, preview: Image.Image, *, reject_blank: bool = False) -> Image.Image:
        target_width, target_height = self._preview_target_size()
        original_width, original_height = preview.size
        if original_width <= 0 or original_height <= 0:
            raise ValueError("Preview image has invalid size.")
        if reject_blank and self._image_looks_blank(preview):
            raise ValueError("Preview image is blank.")

        scale = min(target_width / original_width, target_height / original_height)
        if scale <= 0:
            scale = 1.0
        scale = max(0.1, min(scale, 1.75))

        new_size = (
            max(1, int(round(original_width * scale))),
            max(1, int(round(original_height * scale))),
        )
        if new_size != preview.size:
            preview = preview.resize(new_size, Image.Resampling.LANCZOS)
        return preview

    def _prepare_preview_image(self, path: Path, *, reject_blank: bool = False) -> Image.Image:
        with Image.open(path) as source:
            preview = source.convert("RGBA")
        preview = self._fit_preview_image(preview, reject_blank=reject_blank)
        return self._apply_preview_guides(preview)

    def _clear_preview_mesh_state(self):
        self.preview_mesh_path = None
        self.preview_mesh_object = None
        self.preview_drag_origin = None
        self.preview_mesh_yaw = 38.0
        self.preview_mesh_pitch = -24.0
        self._preview_mesh_error_logged = False
        if self._preview_mesh_render_after_id is not None:
            try:
                self.root.after_cancel(self._preview_mesh_render_after_id)
            except Exception:
                pass
            self._preview_mesh_render_after_id = None

    def _ensure_preview_mesh_loaded(self):
        if self.preview_mesh_path is None:
            return None
        if self.preview_mesh_object is not None:
            return self.preview_mesh_object
        self.preview_mesh_object = load_preview_mesh(self.preview_mesh_path)
        return self.preview_mesh_object

    def _schedule_mesh_preview_render(self, delay_ms: int = 40):
        if self.preview_mesh_path is None:
            return
        if self._preview_mesh_render_after_id is not None:
            try:
                self.root.after_cancel(self._preview_mesh_render_after_id)
            except Exception:
                pass
        self._preview_mesh_render_after_id = self.root.after(delay_ms, self._refresh_preview_mesh_view)

    def _refresh_preview_mesh_view(self):
        self._preview_mesh_render_after_id = None
        if self.preview_mesh_path is None or self.preview_image_label is None:
            return
        if self._preview_mesh_rendering:
            self._schedule_mesh_preview_render(60)
            return

        self._preview_mesh_rendering = True
        try:
            mesh = self._ensure_preview_mesh_loaded()
            if mesh is None:
                return
            resolution = max(320, min(720, min(self._preview_target_size())))
            image = render_mesh_preview_image(
                mesh,
                pitch_deg=self.preview_mesh_pitch,
                yaw_deg=self.preview_mesh_yaw,
                resolution=resolution,
                interactive=True,
            )
            if image is None:
                raise ValueError("Mesh preview render returned nothing.")
            fitted = self._fit_preview_image(image)
            self.preview_photo = ImageTk.PhotoImage(fitted)
            self.preview_image_label.configure(image=self.preview_photo, text="", compound="center")
            self._preview_mesh_error_logged = False
        except Exception:
            if not self._preview_mesh_error_logged:
                self._write_log("Interactive preview fallback:\n" + traceback.format_exc())
                self._preview_mesh_error_logged = True
            if self.preview_source_path is not None:
                try:
                    fallback = self._prepare_preview_image(self.preview_source_path, reject_blank=self.preview_reject_blank)
                    self.preview_photo = ImageTk.PhotoImage(fallback)
                    self.preview_image_label.configure(image=self.preview_photo, text="", compound="center")
                    self.preview_note_var.set(
                        "Interactive mesh preview fell back to the static render. "
                        "You can still open the result in Blender for a full view."
                    )
                    return
                except Exception:
                    pass
            self.preview_photo = None
            self.preview_image_label.configure(image="", text="Preview failed", compound="center")
        finally:
            self._preview_mesh_rendering = False

    def _on_preview_press(self, event):
        if self.preview_mesh_path is None:
            self.preview_drag_origin = None
            return
        self.preview_drag_origin = (int(event.x), int(event.y))

    def _on_preview_drag(self, event):
        if self.preview_mesh_path is None or self.preview_drag_origin is None:
            return
        last_x, last_y = self.preview_drag_origin
        dx = int(event.x) - last_x
        dy = int(event.y) - last_y
        self.preview_drag_origin = (int(event.x), int(event.y))
        self.preview_mesh_yaw += dx * 0.55
        self.preview_mesh_pitch = max(-80.0, min(55.0, self.preview_mesh_pitch + (dy * 0.45)))
        self.preview_note_var.set(
            f"Drag to rotate. Double-click to reset. View yaw {self.preview_mesh_yaw:.0f} deg, pitch {self.preview_mesh_pitch:.0f} deg."
        )
        self._schedule_mesh_preview_render()

    def _on_preview_release(self, _event=None):
        self.preview_drag_origin = None

    def _on_preview_reset_view(self, _event=None):
        if self.preview_mesh_path is None:
            return
        self.preview_mesh_yaw = 38.0
        self.preview_mesh_pitch = -24.0
        self.preview_note_var.set("Drag to rotate. Double-click to reset. Mesh preview is interactive.")
        self._schedule_mesh_preview_render()

    def _schedule_preview_refresh(self, _event=None):
        if self.preview_mesh_path is not None and self.preview_image_label is not None:
            self._schedule_mesh_preview_render(60)
            return
        if self.preview_source_path is None or self.preview_image_label is None:
            return
        if self._preview_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._preview_refresh_after_id)
            except Exception:
                pass
        self._preview_refresh_after_id = self.root.after(60, self._refresh_preview_image)

    def _refresh_preview_image(self):
        self._preview_refresh_after_id = None
        if self.preview_source_path is None or self.preview_image_label is None:
            return
        try:
            preview = self._prepare_preview_image(self.preview_source_path, reject_blank=self.preview_reject_blank)
        except Exception:
            return
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_image_label.configure(image=self.preview_photo, text="", compound="center")

    def _load_preview_file(self, path: Path, *, reject_blank: bool = False):
        if self.preview_image_label is None:
            return
        self._clear_preview_mesh_state()
        self.preview_source_path = path
        self.preview_reject_blank = reject_blank
        preview = self._prepare_preview_image(path, reject_blank=reject_blank)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_image_label.configure(image=self.preview_photo, text="", compound="center")
        self.root.after_idle(self._schedule_preview_refresh)

    def _show_result_preview(self, result):
        if self.preview_image_label is None:
            return

        preview_path = getattr(result, "preview_image_path", None)
        self.last_preview_path = preview_path if (preview_path and preview_path.exists()) else None
        self.preview_guides = ()
        if result.output_path and result.output_path.exists():
            try:
                self.preview_source_path = preview_path if (preview_path and preview_path.exists()) else None
                self.preview_reject_blank = False
                self.preview_mesh_path = result.output_path
                self.preview_mesh_object = None
                self.preview_mesh_yaw = 38.0
                self.preview_mesh_pitch = -24.0
                self.preview_title_var.set("Mesh Result Preview")
                self.preview_note_var.set(
                    f"Chosen sample {result.selected_sample_index}/{result.samples_ran}. Final triangles: {result.face_count:,}. "
                    "Drag to rotate. Double-click to reset."
                )
                self._schedule_mesh_preview_render(10)
                return
            except Exception:
                pass

        if preview_path and preview_path.exists():
            try:
                self._load_preview_file(preview_path, reject_blank=True)
                self.preview_title_var.set("Mesh Result Preview")
                self.preview_note_var.set(
                    f"Chosen sample {result.selected_sample_index}/{result.samples_ran}. Final triangles: {result.face_count:,}."
                )
                return
            except Exception:
                pass

        self.preview_photo = None
        self._clear_preview_mesh_state()
        self.preview_source_path = None
        self.preview_reject_blank = False
        self.preview_image_label.configure(image="", text="Preview not available", compound="center")
        self.preview_title_var.set("Mesh Result")
        self.preview_note_var.set("The mesh finished and was saved, but the preview image could not be rendered.")

    def get_assist_notes(self) -> str:
        if self.assist_notes_box is None:
            return ""
        return self.assist_notes_box.get("1.0", "end").strip()

    def build_mentor_context(self) -> MentorContext:
        if not self.selected_images:
            raise ValueError("Add at least one reference image before running 3DVisual Mesh Mentor.")

        try:
            sample_count = int(self.sample_count_var.get())
        except (tk.TclError, ValueError):
            sample_count = MIN_SAMPLE_COUNT

        detail_scale, detail_label = self.estimate_image_complexity()
        triangle_target = None
        if self.limit_triangles_var.get():
            try:
                triangle_target = int(self.max_triangles_var.get())
            except (tk.TclError, ValueError):
                triangle_target = None

        return MentorContext(
            selected_images=tuple(self.selected_images),
            subject_type=self.assist_subject_type_var.get(),
            subject_name=self.assist_model_var.get().strip(),
            subject_notes=self.get_assist_notes(),
            backend_name=self.backend_var.get(),
            quality_name=self.quality_var.get(),
            cleanup_mode=self.cleanup_var.get(),
            sample_count=sample_count,
            asset_goal=self.asset_goal_var.get(),
            mesh_style=self.mesh_style_var.get(),
            max_triangles=triangle_target,
            detail_label=detail_label,
            detail_scale=detail_scale,
        )

    def build_mentor_settings(self) -> MentorSettings:
        api_key = self.mentor_api_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Add your OpenAI API key in Advanced or set OPENAI_API_KEY before running 3DVisual Mesh Mentor.")

        model_name = self.mentor_model_var.get().strip() or DEFAULT_MENTOR_MODEL
        reasoning_effort = (self.mentor_reasoning_var.get().strip().lower() or DEFAULT_MENTOR_REASONING_EFFORT)
        if reasoning_effort not in MENTOR_REASONING_OPTIONS:
            raise ValueError("Mentor reasoning must be one of: " + ", ".join(MENTOR_REASONING_OPTIONS) + ".")
        if model_name.lower().startswith("gpt-5.1") and reasoning_effort == "xhigh":
            raise ValueError("gpt-5.1 does not support xhigh reasoning. Use high or switch to gpt-5.2.")
        try:
            timeout_seconds = int(self.mentor_timeout_var.get().strip())
        except ValueError as exc:
            raise ValueError("Mentor timeout must be a whole number of seconds.") from exc
        if timeout_seconds < 15 or timeout_seconds > 300:
            raise ValueError("Mentor timeout must stay between 15 and 300 seconds.")

        return MentorSettings(
            api_key=api_key,
            model=model_name,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            use_web_search=self.mentor_use_web_search_var.get(),
            auto_save_case=self.mentor_auto_save_var.get(),
        )

    def refresh_mentor_summary(self):
        has_key = bool(self.mentor_api_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip())
        stale = self.mentor_advice_is_stale()
        model_name = self.mentor_model_var.get().strip() or DEFAULT_MENTOR_MODEL
        reasoning_effort = self.mentor_reasoning_var.get().strip().lower() or DEFAULT_MENTOR_REASONING_EFFORT
        best_mode_active = (
            model_name.strip().lower() == BEST_MENTOR_MODEL.lower()
            and reasoning_effort == BEST_MENTOR_REASONING_EFFORT
            and self.mentor_use_web_search_var.get()
            and self.mentor_auto_run_var.get()
            and self.mentor_auto_apply_var.get()
        )
        ready_line = (
            f"Teacher: {model_name} | reasoning {reasoning_effort} | "
            f"{'web search on' if self.mentor_use_web_search_var.get() else 'web search off'}"
        )
        if best_mode_active:
            ready_line += " | Best AI preset active"

        if self.mentor_running:
            self._set_mentor_badge("Mentor Running", fg=COLORS["warning"], bg=COLORS["warning_soft"])
            self.mentor_summary_var.set(
                "3DVisual Mesh Mentor is analyzing your references now.\n\n"
                "It will return geometry risks, search terms, a triangle target, and practical build hints."
            )
        elif self.last_mentor_advice is not None:
            if stale:
                self._set_mentor_badge("Mentor Stale", fg=COLORS["warning"], bg=COLORS["warning_soft"])
            else:
                self._set_mentor_badge("Mentor Applied", fg=COLORS["success"], bg=COLORS["success_soft"])
            self.mentor_summary_var.set(summarize_mentor_advice(self.last_mentor_advice, stale=stale))
        elif has_key:
            self._set_mentor_badge("Mentor Ready", fg=COLORS["accent"], bg=COLORS["accent_soft"])
            self.mentor_summary_var.set(
                "3DVisual Mesh Mentor is ready.\n\n"
                f"{ready_line}\n\n"
                "Click Run 3DVisual Mesh Mentor to have the cloud teacher review your images, notes, and current settings."
            )
        else:
            self._set_mentor_badge("Mentor Off", fg=COLORS["muted"], bg=COLORS["card_soft"])
            self.mentor_summary_var.set(
                "3DVisual Mesh Mentor is optional.\n\n"
                "Add your OpenAI API key in Advanced, then click Run 3DVisual Mesh Mentor."
            )

        if self.run_mentor_button is not None:
            self.run_mentor_button.configure(
                state="disabled" if self.mentor_running else "normal",
                text="Mentor Running..." if self.mentor_running else "Run 3DVisual Mesh Mentor",
            )
        if self.apply_mentor_button is not None:
            self.apply_mentor_button.configure(
                state="normal" if (self.last_mentor_advice is not None and not stale and not self.mentor_running) else "disabled"
            )
        if self.open_mentor_case_button is not None:
            self.open_mentor_case_button.configure(
                state="normal" if (self.last_mentor_case_path is not None and self.last_mentor_case_path.exists()) else "disabled"
            )

    def mentor_advice_is_stale(self) -> bool:
        if self.last_mentor_advice is None:
            return True
        try:
            return self.last_mentor_signature != build_mentor_signature(self.build_mentor_context())
        except Exception:
            return True

    def on_mentor_badge_click(self, _event=None):
        has_key = bool(self.mentor_api_key_var.get().strip() or os.environ.get("OPENAI_API_KEY", "").strip())
        if has_key and self.preview_assist_notebook is not None and self.assist_tab is not None:
            try:
                self.preview_assist_notebook.select(self.assist_tab)
                if self.assist_notes_box is not None:
                    self.assist_notes_box.focus_set()
                self.append_status("Mentor badge opened the AI Assist tab.")
                return
            except Exception:
                pass

        self.open_advanced_window()
        self.append_status("Mentor badge opened Advanced so you can configure the cloud teacher.")

    def apply_best_mentor_preset(self):
        self.mentor_model_var.set(BEST_MENTOR_MODEL)
        self.mentor_reasoning_var.set(BEST_MENTOR_REASONING_EFFORT)
        self.mentor_timeout_var.set(str(BEST_MENTOR_TIMEOUT_SECONDS))
        self.mentor_use_web_search_var.set(True)
        self.mentor_auto_save_var.set(True)
        self.mentor_auto_run_var.set(True)
        self.mentor_auto_apply_var.set(True)
        self.refresh_mentor_summary()
        self.append_status(
            f"Best AI preset applied: {BEST_MENTOR_MODEL} | reasoning {BEST_MENTOR_REASONING_EFFORT} | "
            "web search on | auto-run on."
        )

    def _set_mentor_badge(self, text: str, *, fg: str, bg: str):
        self.mentor_badge_var.set(text)
        if self.mentor_badge_label is not None:
            self.mentor_badge_label.configure(text=text, fg=fg, bg=bg)

    def refresh_assist_summary(self):
        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        summary = describe_three_role_workflow(workflow)
        summary += (
            "\n\nSmart Hints can adjust preprocessing, settings, and reference search focus. "
            "They do not retrain Hunyuan or make the local model truly browse and learn by itself."
        )
        self.assist_summary_var.set(summary)
        weak_lines = [workflow.analysis.weak_part_note]
        if workflow.analysis.weak_parts:
            for item in workflow.analysis.weak_parts[:6]:
                weak_lines.append(f"- {item.part}: {item.status} | {item.note}")
        self.weak_part_summary_var.set("\n".join(weak_lines))
        self.refresh_mentor_summary()
        self.refresh_reference_basket()
        self.update_action_state()

    def refresh_reference_basket(self):
        guard = build_direction_guard(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        self.reference_guard_var.set(f"Direction Guard: {guard.badge_text}")
        self.reference_guard_note_var.set(guard.note)
        self.reference_slots_var.set("\n".join(guard.slot_lines))

        if self.reference_guard_badge is None or not self.reference_guard_badge.winfo_exists():
            return

        if guard.status == "block":
            bg = COLORS["danger_soft"]
            fg = COLORS["danger"]
        elif guard.status == "warn":
            bg = COLORS["warning_soft"]
            fg = COLORS["warning"]
        else:
            bg = COLORS["success_soft"]
            fg = COLORS["success"]

        self.reference_guard_badge.configure(bg=bg, fg=fg)

    def auto_label_reference_views(self):
        changed = 0
        for item in self.selected_images:
            if (item.view_value or "").strip().lower() != "auto":
                continue
            if guess_detail_crop_from_name(item.path):
                item.view_value = DETAIL_VIEW_OPTION
                guessed_target = guess_detail_target_from_name(item.path)
                if guessed_target:
                    item.detail_target = guessed_target
                changed += 1
                continue
            guessed = guess_view_from_name(item.path)
            if guessed:
                item.view_value = guessed.capitalize()
                changed += 1

        self.refresh_rows()
        self.update_selection_count()
        self._update_preview()
        self.refresh_assist_summary()
        if changed:
            self.append_status(f"Reference Basket auto-labeled {changed} image(s) from file names.")
        else:
            self.append_status("Reference Basket found no filename hints to auto-label.")

    def open_missing_view_search(self):
        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        guard = build_direction_guard(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )

        if guard.missing_views:
            for view in guard.missing_views[:3]:
                query = f"{workflow.reference.search_terms} {view.lower()} view reference"
                webbrowser.open_new_tab(f"https://www.google.com/search?q={quote_plus(query)}")
            self.append_status("Reference Basket opened searches for missing views: " + ", ".join(guard.missing_views))
            return

        webbrowser.open_new_tab(
            f"https://www.google.com/search?q={quote_plus(workflow.reference.search_terms + ' reference')}"
        )
        self.append_status("Reference Basket already has the main views. Opened a general reference search instead.")

    def build_assist_search_terms(self) -> str:
        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        return workflow.reference.search_terms or "object reference"

    def apply_assist_hints(self):
        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        analysis = workflow.analysis

        self.quality_var.set(analysis.recommended_quality)
        self.sample_count_var.set(str(analysis.recommended_samples))
        self.mesh_style_var.set(analysis.recommended_mesh_style)
        self.asset_goal_var.set(analysis.recommended_asset_goal)
        self.cleanup_var.set(analysis.recommended_cleanup)
        self.remove_bg_var.set(analysis.recommended_remove_background)

        self.on_quality_change()
        self.on_asset_goal_change(log_message=False)
        self.on_mesh_style_change()
        self.refresh_assist_summary()
        self.append_status(
            f"Three-role AI workflow applied smart hints for: {analysis.profile.label} "
            f"using {workflow.mesh.preferred_model} guidance."
        )

    def open_assist_search(self):
        workflow = build_three_role_workflow(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        for query in workflow.reference.queries:
            webbrowser.open_new_tab(f"https://www.google.com/search?q={quote_plus(query)}")
        self.append_status(f"Reference AI opened searches for: {workflow.reference.search_terms}")

    def clear_assist_notes(self):
        self.assist_subject_type_var.set("Auto")
        self.assist_model_var.set("")
        if self.assist_notes_box is not None:
            self.assist_notes_box.delete("1.0", "end")
        self.refresh_assist_summary()
        self.append_status("AI Assist notes cleared.")

    def _launch_mentor_request(self, context: MentorContext, settings: MentorSettings, *, auto_for_generate: bool):
        if self.mentor_running:
            if auto_for_generate:
                self.pending_start_after_mentor = True
                self.append_status("3DVisual Mesh Mentor is already running. Generation will continue when the mentor finishes.")
            return

        self.pending_start_after_mentor = auto_for_generate
        self.mentor_running = True
        self.refresh_mentor_summary()
        self.append_status(
            f"3DVisual Mesh Mentor started: {settings.model} | reasoning {settings.reasoning_effort} | "
            f"{'web search on' if settings.use_web_search else 'web search off'}"
        )
        if auto_for_generate:
            self.append_status("Auto-run is on. Mentor will review the job before mesh generation starts.")
        self.worker_queue.put(("status", "3DVisual Mesh Mentor is reviewing your references and notes..."))
        worker = threading.Thread(
            target=self._mentor_worker,
            args=(context, settings, build_mentor_signature(context)),
            daemon=True,
        )
        worker.start()

    def run_mentor(self):
        try:
            context = self.build_mentor_context()
            settings = self.build_mentor_settings()
        except ValueError as exc:
            messagebox.showwarning("Mentor setup", str(exc), parent=self.root)
            return
        self._launch_mentor_request(context, settings, auto_for_generate=False)

    def _mentor_worker(self, context: MentorContext, settings: MentorSettings, signature: str):
        try:
            advice = request_mentor_advice(context, settings)
            case_path = save_mentor_case(context, advice) if settings.auto_save_case else None
            self.worker_queue.put(("mentor_done", advice, case_path, signature))
        except Exception:
            self.worker_queue.put(("mentor_error", traceback.format_exc()))

    def apply_mentor_hints(self, *, skip_validation: bool = False):
        if self.last_mentor_advice is None:
            messagebox.showinfo("Mentor hints", "Run 3DVisual Mesh Mentor first.", parent=self.root)
            return

        stale = self.mentor_advice_is_stale()
        if stale and not skip_validation:
            messagebox.showwarning(
                "Mentor hints",
                "The current mentor advice is stale because the images or notes changed. Run Mentor again.",
                parent=self.root,
            )
            return

        advice = self.last_mentor_advice
        if advice.subject_type in ASSIST_SUBJECT_TYPES:
            self.assist_subject_type_var.set(advice.subject_type)
        if advice.subject_name_guess and not self.assist_model_var.get().strip():
            self.assist_model_var.set(advice.subject_name_guess)

        self.quality_var.set(advice.recommended_quality)
        self.sample_count_var.set(str(advice.recommended_samples))
        self.asset_goal_var.set(advice.recommended_asset_goal)
        self.mesh_style_var.set(advice.recommended_mesh_style)
        self.cleanup_var.set(advice.recommended_cleanup)
        self.remove_bg_var.set(advice.recommended_remove_background)

        self.on_quality_change()
        self.on_asset_goal_change(log_message=False)
        self.on_mesh_style_change()
        self.limit_triangles_var.set(True)
        self.auto_triangle_budget = False
        self.max_triangles_var.set(advice.triangle_target)
        self.refresh_advanced_summary()
        self.refresh_assist_summary()
        self.append_status(
            f"3DVisual Mesh Mentor applied: {advice.recommended_quality} | "
            f"{advice.recommended_samples} scan stage(s) | {advice.triangle_target:,} triangles."
        )
        if advice.geometry_risks:
            self.append_status("Mentor risks: " + "; ".join(advice.geometry_risks[:4]))

    def open_mentor_case(self):
        if self.last_mentor_case_path and self.last_mentor_case_path.exists():
            os.startfile(self.last_mentor_case_path)
        else:
            self.append_status("No mentor case file is available yet.")

    def open_mentor_cases_folder(self):
        MENTOR_CASES_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(MENTOR_CASES_DIR)

    def _play_finish_sound(self):
        try:
            if winsound is not None:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                self.root.bell()
        except Exception:
            pass

    def _request_system_snapshot(self):
        if self._system_snapshot_running:
            return
        self._system_snapshot_running = True
        worker = threading.Thread(target=self._system_snapshot_worker, daemon=True)
        worker.start()

    def _system_snapshot_worker(self):
        try:
            snapshot = self.system_monitor.snapshot()
            self.worker_queue.put(("system", snapshot))
        except Exception as exc:
            self.worker_queue.put(("system_error", str(exc)))

    def _reset_progress_if_idle(self):
        if not self.is_running:
            self._reset_progress()

    def update_action_state(self):
        result_ready = bool(self.last_output_path and self.last_output_path.exists())
        self.refresh_result_summary()
        if self.open_result_button is not None:
            self.open_result_button.configure(state="normal" if (result_ready and not self.is_running) else "disabled")
        if self.open_blender_cleanup_button is not None:
            self.open_blender_cleanup_button.configure(state="normal" if (result_ready and not self.is_running) else "disabled")
        if self.open_blender_retopo_button is not None:
            self.open_blender_retopo_button.configure(state="normal" if (result_ready and not self.is_running) else "disabled")

        if self.is_running:
            self.start_button.configure(state="disabled", text="Start 3D Mesh")
            return

        if not self.selected_images:
            self.start_button.configure(state="disabled", text="Start 3D Mesh")
            return

        guard = build_direction_guard(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        if guard.allow_generation:
            self.start_button.configure(state="normal", text="Start 3D Mesh")
        else:
            self.start_button.configure(state="disabled", text="Add Missing Views")

    def _format_duration(self, total_seconds: float) -> str:
        total_seconds = max(0, int(total_seconds))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _update_eta_label(self):
        if self.is_running and self.generation_started_at is not None:
            elapsed = max(0.0, time.monotonic() - self.generation_started_at)
            self.last_elapsed_seconds = elapsed
            elapsed_text = self._format_duration(elapsed)
            estimated_total = self._estimate_total_seconds(elapsed)
            if self.current_progress >= 99.5 or self.target_progress >= 100.0:
                self.progress_eta_var.set(f"Time {elapsed_text} | ETA finalizing")
            elif estimated_total is not None:
                remaining = max(0.0, estimated_total - elapsed)
                self.progress_eta_var.set(f"Time {elapsed_text} | ETA {self._format_duration(remaining)}")
            else:
                self.progress_eta_var.set(f"Time {elapsed_text} | ETA estimating")
            return

        if self.current_progress >= 100.0:
            if self.last_elapsed_seconds > 0:
                self.progress_eta_var.set(f"Done in {self._format_duration(self.last_elapsed_seconds)}")
            else:
                self.progress_eta_var.set("Done")
        else:
            self.progress_eta_var.set("ETA --:--")

    def _refresh_progress_display(self):
        shown = max(0.0, min(100.0, self.current_progress))
        self.progress.configure(value=shown)
        self.progress_percent_var.set(f"{int(round(shown))}%")
        self._update_eta_label()

    def _set_progress_target(self, value: float):
        value = max(0.0, min(100.0, float(value)))
        if value < self.target_progress and self.is_running:
            return
        if self.is_running and value > self.target_progress + 0.2:
            self._record_progress_marker(value)
        self.target_progress = value

    def _reset_progress(self):
        self.current_progress = 0.0
        self.target_progress = 0.0
        self.generation_started_at = None
        self.last_elapsed_seconds = 0.0
        self.progress_markers = []
        self.smoothed_total_seconds = None
        self.history_predicted_total_seconds = None
        self.eta_prediction_source = "none"
        self.active_eta_profile = None
        self._refresh_progress_display()

    def _animate_progress(self):
        next_delay = 120
        if self.current_progress < self.target_progress:
            gap = self.target_progress - self.current_progress
            step = max(0.35, min(2.2, gap / 8.0))
            self.current_progress = min(self.target_progress, self.current_progress + step)
            self._refresh_progress_display()
        elif self.is_running:
            self._update_eta_label()
        elif not self.is_running and self.current_progress > self.target_progress:
            self.current_progress = self.target_progress
            self._refresh_progress_display()
        elif not self.is_running:
            next_delay = 260
        self.root.after(next_delay, self._animate_progress)

    def set_status(self, text: str):
        self.status_box.configure(state="normal")
        self.status_box.delete("1.0", "end")
        self.status_box.insert("1.0", text)
        self.status_box.configure(state="disabled")
        self.status_box.see("end")

    def append_status(self, text: str):
        self.status_box.configure(state="normal")
        current = self.status_box.get("1.0", "end-1c").strip()
        if current:
            self.status_box.insert("end", "\n")
        self.status_box.insert("end", text)
        total_lines = int(float(self.status_box.index("end-1c").split(".")[0]))
        max_lines = 320
        if total_lines > max_lines:
            trim_to = total_lines - max_lines
            self.status_box.delete("1.0", f"{trim_to + 1}.0")
        self.status_box.configure(state="disabled")
        self.status_box.see("end")

    def refresh_advanced_summary(self):
        detail_scale, detail_label = self.estimate_image_complexity()
        recommended, _ = self.recommend_triangle_budget()
        try:
            current_triangle_value = int(self.max_triangles_var.get())
        except (tk.TclError, ValueError):
            current_triangle_value = QUALITY_PRESETS[self.quality_var.get()].simplify_target_faces

        if self.limit_triangles_var.get():
            triangle_text = f"{current_triangle_value:,}"
        elif recommended is not None:
            triangle_text = f"{recommended:,}"
        else:
            triangle_text = "Manual"

        if not self.limit_triangles_var.get():
            self.triangle_mode_var.set("Mode: Cap Off")
        elif self.auto_triangle_budget:
            self.triangle_mode_var.set("Mode: Auto")
        else:
            self.triangle_mode_var.set("Mode: Manual")

        self.triangle_summary_var.set(triangle_text)
        self.summary_var.set(
            "Engine: Local Hunyuan\n"
            f"Visual: {detail_label.title()} ({detail_scale:.2f}x) | Scans: {self.sample_count_var.get()} | Cleanup: {self.cleanup_var.get()}\n"
            f"Memory guard: {'On' if self.memory_guard_var.get() else 'Off'} | Soft RAM {self.soft_ram_limit_var.get()}% | Soft VRAM {self.soft_vram_limit_var.get()}%\n"
            "Estimate uses asset goal + mesh style + image detail + reference coverage. Higher scan counts now sweep from broader shape checks into tighter detail passes."
        )

        if self.max_triangles_spin is not None and self.max_triangles_spin.winfo_exists():
            self.max_triangles_spin.configure(state="normal" if self.limit_triangles_var.get() else "disabled")

    def on_quality_change(self, _event=None):
        preset = QUALITY_PRESETS[self.quality_var.get()]
        if not self.limit_triangles_var.get() and self.asset_goal_var.get() == "Custom":
            self.max_triangles_var.set(preset.simplify_target_faces)
        self.refresh_advanced_summary()
        self.append_status(f"Quality set to: {self.quality_var.get()}")

    def on_sample_count_change(self):
        self.refresh_advanced_summary()
        self.append_status(f"Layered scan count set to: {self.sample_count_var.get()} stage(s).")

    def _on_main_triangle_changed(self, _event=None):
        self.limit_triangles_var.set(True)
        self.auto_triangle_budget = False
        self.refresh_advanced_summary()

    def use_auto_triangle_budget(self):
        self.limit_triangles_var.set(True)
        recommended, _reason = self.recommend_triangle_budget()
        if recommended is not None:
            self.auto_triangle_budget = True
            self.max_triangles_var.set(recommended)
        else:
            self.auto_triangle_budget = False
            self.max_triangles_var.set(QUALITY_PRESETS[self.quality_var.get()].simplify_target_faces)
        self.refresh_advanced_summary()
        self.append_status(f"Triangle target switched to auto: {int(self.max_triangles_var.get()):,}")

    def disable_triangle_budget(self):
        self.limit_triangles_var.set(False)
        self.auto_triangle_budget = False
        self.refresh_advanced_summary()
        self.append_status("Triangle cap turned off.")

    def recommend_triangle_budget(self) -> tuple[int | None, str]:
        goal_preset = ASSET_GOAL_PRESETS[self.asset_goal_var.get()]
        style_preset = MESH_STYLE_PRESETS[self.mesh_style_var.get()]

        if goal_preset.suggested_triangles is None:
            return None, "Manual"

        detail_scale, detail_label = self.estimate_image_complexity()
        view_scale = min(1.20, 1.0 + (max(0, len(self.selected_images) - 1) * 0.05))
        quality_scale = {
            "Fast": 0.92,
            "Balanced": 1.00,
            "High": 1.10,
            "Max Detail": 1.22,
        }.get(self.quality_var.get(), 1.0)
        profile = build_subject_profile(
            self.assist_subject_type_var.get(),
            self.assist_model_var.get().strip(),
            self.get_assist_notes(),
        )
        if profile.is_vehicle:
            subject_scale = 1.18
        elif profile.is_organic:
            subject_scale = 1.12
        elif profile.is_hard_surface:
            subject_scale = 1.06
        elif profile.is_transparent:
            subject_scale = 0.90
        else:
            subject_scale = 1.0
        raw_target = int(
            goal_preset.suggested_triangles
            * style_preset.triangle_multiplier
            * detail_scale
            * view_scale
            * quality_scale
            * subject_scale
        )
        stepped = int(round(raw_target / TRIANGLE_BUDGET_STEP) * TRIANGLE_BUDGET_STEP)
        stepped = max(MIN_TRIANGLE_BUDGET, min(MAX_TRIANGLE_BUDGET, stepped))
        reason = f"{goal_preset.range_text} base | {detail_label} detail | {len(self.selected_images)} ref(s) | {self.quality_var.get()} quality"
        return stepped, reason

    def sync_recommended_triangle_budget(self, *, log_message: bool = True):
        goal_preset = ASSET_GOAL_PRESETS[self.asset_goal_var.get()]
        style_preset = MESH_STYLE_PRESETS[self.mesh_style_var.get()]
        target, range_text = self.recommend_triangle_budget()

        self.asset_goal_note_var.set(goal_preset.note)
        self.mesh_style_note_var.set(style_preset.note)
        self.quality_note_var.set(QUALITY_PRESETS[self.quality_var.get()].note)

        if target is None:
            self.auto_triangle_budget = False
            self.refresh_advanced_summary()
            return

        self.auto_triangle_budget = True
        self.limit_triangles_var.set(True)
        self.max_triangles_var.set(target)
        if self.cleanup_var.get() == "Off":
            self.cleanup_var.set("Clean")
        self.refresh_advanced_summary()

        if log_message:
            self.append_status(
                f"Recommended triangles: {target:,} for {goal_preset.label} + {style_preset.label} ({range_text})."
            )

    def on_asset_goal_change(self, _event=None, *, log_message: bool = True):
        preset = ASSET_GOAL_PRESETS[self.asset_goal_var.get()]
        if preset.suggested_triangles is None:
            self.auto_triangle_budget = False
            self.asset_goal_note_var.set(preset.note)
            self.mesh_style_note_var.set(MESH_STYLE_PRESETS[self.mesh_style_var.get()].note)
            self.quality_note_var.set(QUALITY_PRESETS[self.quality_var.get()].note)
            self.refresh_advanced_summary()
            if log_message:
                self.append_status("Asset goal set to Custom.")
            return
        self.sync_recommended_triangle_budget(log_message=log_message)

    def on_mesh_style_change(self, _event=None):
        if self.asset_goal_var.get() == "Custom":
            self.auto_triangle_budget = False
            style_preset = MESH_STYLE_PRESETS[self.mesh_style_var.get()]
            self.mesh_style_note_var.set(style_preset.note)
            self.quality_note_var.set(QUALITY_PRESETS[self.quality_var.get()].note)
            self.refresh_advanced_summary()
            self.append_status(f"Mesh style set to {style_preset.label}.")
            return
        self.sync_recommended_triangle_budget(log_message=True)

    def on_triangle_toggle(self):
        if self.limit_triangles_var.get():
            if self.asset_goal_var.get() != "Custom":
                self.sync_recommended_triangle_budget(log_message=False)
            else:
                self.auto_triangle_budget = False
                self.refresh_advanced_summary()
            try:
                shown_triangles = int(self.max_triangles_var.get())
            except (tk.TclError, ValueError):
                shown_triangles = QUALITY_PRESETS[self.quality_var.get()].simplify_target_faces
            self.append_status(f"Max triangle budget enabled: {shown_triangles:,}")
        else:
            self.auto_triangle_budget = False
            self.refresh_advanced_summary()
            self.append_status("Triangle budget disabled.")

    def collect_generation_options(self) -> GenerationOptions:
        max_triangles = None
        if self.limit_triangles_var.get():
            try:
                max_triangles = int(self.max_triangles_var.get())
            except (tk.TclError, ValueError):
                raise ValueError("Max Triangles must be a whole number.")
            if not (MIN_TRIANGLE_BUDGET <= max_triangles <= MAX_TRIANGLE_BUDGET):
                raise ValueError(
                    f"Max Triangles must stay between {MIN_TRIANGLE_BUDGET:,} and {MAX_TRIANGLE_BUDGET:,}."
                )

        try:
            sample_count = int(self.sample_count_var.get())
        except (tk.TclError, ValueError):
            raise ValueError(f"Samples must be between {MIN_SAMPLE_COUNT} and {MAX_SAMPLE_COUNT}.")
        if not (MIN_SAMPLE_COUNT <= sample_count <= MAX_SAMPLE_COUNT):
            raise ValueError(f"Samples must stay between {MIN_SAMPLE_COUNT} and {MAX_SAMPLE_COUNT}.")

        try:
            soft_ram_limit = int(self.soft_ram_limit_var.get())
            soft_vram_limit = int(self.soft_vram_limit_var.get())
        except (tk.TclError, ValueError):
            raise ValueError("Soft RAM and VRAM limits must be whole percentages.")

        if not (MIN_RESOURCE_LIMIT_PERCENT <= soft_ram_limit <= MAX_RESOURCE_LIMIT_PERCENT):
            raise ValueError(
                f"Soft RAM Limit must stay between {MIN_RESOURCE_LIMIT_PERCENT}% and {MAX_RESOURCE_LIMIT_PERCENT}%."
            )
        if not (MIN_RESOURCE_LIMIT_PERCENT <= soft_vram_limit <= MAX_RESOURCE_LIMIT_PERCENT):
            raise ValueError(
                f"Soft VRAM Limit must stay between {MIN_RESOURCE_LIMIT_PERCENT}% and {MAX_RESOURCE_LIMIT_PERCENT}%."
            )

        return GenerationOptions(
            output_name=self.output_name_var.get() or "3dvisual_mesh",
            backend_name=self.backend_var.get(),
            quality_name=self.quality_var.get(),
            cleanup_mode=self.cleanup_var.get(),
            remove_background=self.remove_bg_var.get(),
            keep_raw_copy=self.keep_raw_copy_var.get(),
            max_triangles=max_triangles,
            sample_count=sample_count,
            memory_guard=self.memory_guard_var.get(),
            soft_ram_limit_percent=soft_ram_limit,
            soft_vram_limit_percent=soft_vram_limit,
            subject_type=self.assist_subject_type_var.get(),
            subject_name=self.assist_model_var.get().strip(),
            subject_notes=self.get_assist_notes(),
        )

    def parse_drop_files(self, data: str) -> list[Path]:
        paths = [Path(item) for item in self.root.tk.splitlist(data)]
        return [path for path in paths if path.suffix.lower() in SUPPORTED_EXTS and path.exists()]

    def on_drop(self, event):
        files = self.parse_drop_files(event.data)
        if not files:
            self.append_status("Drop received, but no supported image files were found.")
            return
        self.add_images(files)

    def select_files(self):
        self.append_status("Opening file picker...")
        file_paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Select reference images",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not file_paths:
            self.append_status("File picker closed with no images selected.")
            return
        self.add_images([Path(path) for path in file_paths])

    def load_dog_test(self):
        if not DOG_TEST_IMAGE.exists():
            messagebox.showwarning("Missing test image", f"Test image not found:\n{DOG_TEST_IMAGE}", parent=self.root)
            return
        self.add_images([DOG_TEST_IMAGE])
        self.append_status(f"Loaded built-in test image: {DOG_TEST_IMAGE.name}")

    def _refresh_after_image_change(self):
        self.refresh_rows()
        self.refresh_assist_summary()
        self.update_selection_count()
        self._update_preview()
        if self.asset_goal_var.get() == "Custom" or not self.auto_triangle_budget:
            self.refresh_advanced_summary()
        else:
            self.sync_recommended_triangle_budget(log_message=False)

    def _replace_selected_images(self, items: list[SelectedImage]):
        self.selected_images = items[:MAX_REFERENCE_IMAGES]
        self._refresh_after_image_change()

    def split_ortho_sheet(self):
        source_path: Path | None = None
        if len(self.selected_images) == 1 and self.selected_images[0].path.exists():
            source_path = self.selected_images[0].path
        else:
            file_path = filedialog.askopenfilename(
                title="Choose 2x2 Ortho Sheet",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
            )
            if not file_path:
                return
            source_path = Path(file_path)

        try:
            result = split_ortho_reference_sheet(source_path)
        except Exception as exc:
            messagebox.showwarning("Sheet split failed", str(exc), parent=self.root)
            self.append_status(f"Ortho Sheet Mode failed: {exc}")
            return

        self._replace_selected_images(list(result.images))
        self.append_status(f"Ortho Sheet Mode loaded: {result.source_path.name}")
        self.append_status(result.note)
        self.append_status(f"Cached split views in: {result.output_dir}")
        self.root.bell()

    def add_images(self, paths: list[Path]):
        existing = {item.path for item in self.selected_images}
        added_names: list[str] = []

        for path in paths:
            if path in existing:
                continue
            if len(self.selected_images) >= MAX_REFERENCE_IMAGES:
                self.append_status(
                    f"Only {MAX_PRIMARY_REFERENCES} main views and {MAX_DETAIL_REFERENCES} detail crops are used in this app."
                )
                break
            guessed = guess_view_from_name(path)
            if guess_detail_crop_from_name(path):
                default_view = DETAIL_VIEW_OPTION
                default_detail_target = guess_detail_target_from_name(path) or "Auto"
            else:
                default_view = guessed.capitalize() if guessed else "Auto"
                default_detail_target = "Auto"
            self.selected_images.append(SelectedImage(path=path, view_value=default_view, detail_target=default_detail_target))
            existing.add(path)
            added_names.append(path.name)

        self._refresh_after_image_change()

        if added_names:
            self.append_status("Added: " + ", ".join(added_names))
            self.append_status("Ready. Click Start 3D Mesh.")
            self.root.bell()
        else:
            self.append_status("No new images were added.")

    def clear_images(self):
        self.selected_images.clear()
        self._refresh_after_image_change()
        self.refresh_advanced_summary()
        self.set_status("Selection cleared.")

    def refresh_rows(self):
        for row in self.row_widgets:
            for widget in row:
                widget.destroy()
        self.row_widgets.clear()

        if not self.selected_images:
            self.empty_label.pack(anchor="w")
            return

        self.empty_label.pack_forget()

        header = ttk.Frame(self.rows_frame)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text="File", style="Muted.TLabel").pack(side="left")
        ttk.Label(header, text="Use As", style="Muted.TLabel").pack(side="right", padx=(0, 172))
        ttk.Label(header, text="Focus", style="Muted.TLabel").pack(side="right", padx=(0, 16))
        ttk.Label(header, text="Hint", style="Muted.TLabel").pack(side="right", padx=(0, 18))
        self.row_widgets.append((header,))

        for item in self.selected_images:
            row = ttk.Frame(self.rows_frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=item.path.name).pack(side="left")

            focus_var = tk.StringVar(value=normalize_detail_target(item.detail_target))
            focus_combo = ttk.Combobox(row, values=DETAIL_TARGET_OPTIONS, state="readonly", width=18, textvariable=focus_var)
            focus_combo.pack(side="right", padx=(8, 0))

            view_var = tk.StringVar(value=item.view_value)
            combo = ttk.Combobox(row, values=VIEW_OPTIONS, state="readonly", width=14, textvariable=view_var)
            combo.pack(side="right", padx=(8, 0))

            def sync_focus_state(selected=item, focus_widget=focus_combo, focus_value=focus_var):
                if is_detail_view_value(selected.view_value):
                    if normalize_detail_target(selected.detail_target) == "Auto":
                        guessed_target = guess_detail_target_from_name(selected.path)
                        if guessed_target:
                            selected.detail_target = guessed_target
                            focus_value.set(guessed_target)
                    focus_widget.configure(state="readonly")
                else:
                    selected.detail_target = "Auto"
                    focus_value.set("Auto")
                    focus_widget.configure(state="disabled")

            def update_view(_event, selected=item, var=view_var):
                selected.view_value = var.get()
                sync_focus_state(selected=selected)
                self.update_selection_count()
                self._update_preview()
                self.refresh_assist_summary()

            combo.bind("<<ComboboxSelected>>", update_view)

            def update_focus(_event, selected=item, var=focus_var):
                selected.detail_target = normalize_detail_target(var.get())
                self.update_selection_count()
                self._update_preview()
                self.refresh_assist_summary()

            focus_combo.bind("<<ComboboxSelected>>", update_focus)

            remove_btn = ttk.Button(row, text="Remove", width=8, command=lambda current=item: self.remove_image(current))
            remove_btn.pack(side="right")

            guessed = guess_view_from_name(item.path)
            guessed_detail_target = guess_detail_target_from_name(item.path)
            if is_detail_view_value(item.view_value):
                hint_text = normalize_detail_target(item.detail_target)
                if hint_text == "Auto":
                    hint_text = guessed_detail_target or "Detail"
            elif guess_detail_crop_from_name(item.path):
                hint_text = guessed_detail_target or "Detail"
            else:
                hint_text = guessed.capitalize() if guessed else "None"
            hint_label = ttk.Label(row, text=hint_text, style="Muted.TLabel")
            hint_label.pack(side="right", padx=(0, 10))

            sync_focus_state()
            self.row_widgets.append((row, combo, focus_combo, remove_btn, hint_label))

    def remove_image(self, item: SelectedImage):
        self.selected_images = [entry for entry in self.selected_images if entry.path != item.path]
        self._refresh_after_image_change()
        self.append_status(f"Removed: {item.path.name}")

    def _start_generation_core(self):
        if self.is_running:
            return
        if not self.selected_images:
            messagebox.showwarning("No images", "Select at least one image first.", parent=self.root)
            return

        primary_images, detail_images = split_reference_images(self.selected_images)
        if not primary_images:
            messagebox.showwarning(
                "Main view missing",
                f"Add at least 1 main image. {DETAIL_VIEW_OPTION} is only extra help for hands, cloth, or weak parts.",
                parent=self.root,
            )
            return
        if len(primary_images) > MAX_PRIMARY_REFERENCES:
            messagebox.showwarning(
                "Too many main views",
                f"Use up to {MAX_PRIMARY_REFERENCES} main views. Move extra closeups to {DETAIL_VIEW_OPTION} or remove them.",
                parent=self.root,
            )
            return
        if len(detail_images) > MAX_DETAIL_REFERENCES:
            messagebox.showwarning(
                "Too many detail crops",
                f"Use up to {MAX_DETAIL_REFERENCES} {DETAIL_VIEW_OPTION.lower()} images for body-part focus such as hands, feet, torso, cape, or other weak parts.",
                parent=self.root,
            )
            return

        direction_guard = build_direction_guard(
            self.selected_images,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )
        if not direction_guard.allow_generation:
            message = direction_guard.note
            if direction_guard.missing_views:
                message += "\n\nMissing views: " + ", ".join(direction_guard.missing_views)
            messagebox.showwarning("Direction Guard", message, parent=self.root)
            self.append_status("Direction Guard blocked the job: " + direction_guard.note)
            return

        try:
            self.pending_options = self.collect_generation_options()
        except ValueError as exc:
            messagebox.showwarning("Invalid settings", str(exc), parent=self.root)
            return

        self.pending_selection = [
            SelectedImage(path=item.path, view_value=item.view_value, detail_target=item.detail_target)
            for item in self.selected_images
        ]
        assist_workflow = build_three_role_workflow(
            self.pending_selection,
            self.assist_subject_type_var.get(),
            self.assist_model_var.get(),
            self.get_assist_notes(),
        )

        self.is_running = True
        self.last_output_path = None
        self.last_preview_path = None
        self._clear_preview_mesh_state()
        self.update_action_state()
        self.generation_started_at = time.monotonic()
        self.last_elapsed_seconds = 0.0
        self.progress_markers = []
        self.smoothed_total_seconds = None
        self.active_eta_profile = self._build_eta_profile(self.pending_selection, self.pending_options)
        self.history_predicted_total_seconds = self._predict_duration_from_history(self.active_eta_profile)
        if self.history_predicted_total_seconds is not None:
            self.eta_prediction_source = "history"
        else:
            self.history_predicted_total_seconds = self._predict_duration_from_profile(self.active_eta_profile)
            self.eta_prediction_source = "heuristic" if self.history_predicted_total_seconds is not None else "none"
        self.current_progress = 0.0
        self.target_progress = 4.0
        self._refresh_progress_display()
        if self.preview_image_label is not None:
            self.preview_photo = None
            self.preview_image_label.configure(image="", text="Generating preview...", compound="center")
        self.preview_title_var.set("Generating Mesh...")
        self.preview_note_var.set("When the job finishes, this area will switch to a result preview render of the mesh.")
        self.set_status(
            "Starting 3D mesh generation...\n\n"
            f"Backend: {self.pending_options.backend_name}\n"
            f"References: {len(primary_images)} main + {len(detail_images)} detail\n"
            f"Layered scans: {self.pending_options.sample_count}\n"
            f"Memory guard: {'On' if self.pending_options.memory_guard else 'Off'}\n"
            f"Soft RAM / VRAM: {self.pending_options.soft_ram_limit_percent}% / {self.pending_options.soft_vram_limit_percent}%\n"
            f"Assist subject: {self.pending_options.subject_type} | {self.pending_options.subject_name or 'No model name'}\n"
            f"Reference AI: {assist_workflow.reference.subject_label}\n"
            f"GPT Mentor risk: {assist_workflow.analysis.risk_level}\n"
            f"{assist_workflow.analysis.coverage_note}\n"
            f"TRELLIS Specialist: {'On' if assist_workflow.specialist.active else 'Optional'} | {assist_workflow.specialist.mode}\n"
            f"Mesh AI target: {assist_workflow.mesh.preferred_model} ({assist_workflow.mesh.pipeline_mode})\n"
            "Output will be written to your Desktop when finished."
        )
        if assist_workflow.analysis.profile.is_vehicle and assist_workflow.analysis.missing_views:
            self.append_status(
                "Vehicle geometry warning: missing directional coverage can place wheels or body parts in the wrong spot. "
                f"Still missing: {', '.join(assist_workflow.analysis.missing_views)}"
            )
        if self.pending_options.sample_count > 1 and len(primary_images) == 1:
            self.append_status("Extra scan stages can reduce obvious distortion, but real front/side/back views still improve shape more than scan count alone.")
        focused_parts: list[str] = []
        for item in detail_images:
            detail_target = normalize_detail_target(item.detail_target)
            if detail_target != "Auto" and detail_target not in focused_parts:
                focused_parts.append(detail_target)
        if focused_parts:
            self.append_status("Detail crop focus: " + ", ".join(focused_parts))
        if assist_workflow.analysis.weak_part_note:
            self.append_status(assist_workflow.analysis.weak_part_note)
        if detail_images:
            self.append_status("Late detail edge guide: on for focused detail crops during stronger scan stages.")

        worker = threading.Thread(target=self._generate_worker, daemon=True)
        worker.start()

    def start_generation(self):
        if self.is_running:
            return

        if self.mentor_auto_run_var.get() and self.selected_images:
            needs_mentor = self.last_mentor_advice is None or self.mentor_advice_is_stale()
            if needs_mentor:
                try:
                    context = self.build_mentor_context()
                    settings = self.build_mentor_settings()
                except ValueError as exc:
                    self.append_status(f"Mentor auto-run skipped: {exc}")
                else:
                    self._launch_mentor_request(context, settings, auto_for_generate=True)
                    return

        self._start_generation_core()

    def _generate_worker(self):
        try:
            options = self.pending_options
            selected_images = self.pending_selection

            if options is None or not selected_images:
                raise RuntimeError("No queued job was found for generation.")

            self.worker_queue.put(("status", f"Quality preset: {options.quality_name}"))
            self.worker_queue.put(("status", f"Backend: {options.backend_name}"))
            self.worker_queue.put(("status", f"Cleanup mode: {options.cleanup_mode}"))
            self.worker_queue.put(("status", f"Layered scans: {options.sample_count}"))
            self.worker_queue.put(("status", f"Memory guard: {'On' if options.memory_guard else 'Off'}"))
            self.worker_queue.put(("status", f"Soft RAM / VRAM: {options.soft_ram_limit_percent}% / {options.soft_vram_limit_percent}%"))
            if options.subject_type != "Auto" or options.subject_name or options.subject_notes:
                self.worker_queue.put(("status", f"AI Assist: {options.subject_type} | {options.subject_name or 'Unnamed subject'}"))
            if options.max_triangles is not None:
                self.worker_queue.put(("status", f"Max triangles: {options.max_triangles:,}"))
            self.worker_queue.put(("status", "Running Hunyuan generation... this can take a while."))

            def progress_update(value: int, message: str):
                self.worker_queue.put(("progress", value, message))

            result = generate_mesh(selected_images, options, progress_callback=progress_update)
            self.worker_queue.put(("done", result))
        except Exception:
            self.worker_queue.put(("error", traceback.format_exc()))

    def _poll_worker_queue(self):
        try:
            while True:
                message = self.worker_queue.get_nowait()
                kind = message[0]

                if kind == "status":
                    self.append_status(message[1])
                elif kind == "progress":
                    self._set_progress_target(message[1])
                    if len(message) > 2 and message[2]:
                        self.append_status(message[2])
                elif kind == "system":
                    snapshot = message[1]
                    cpu_line, gpu_line, live_line = describe_snapshot(snapshot)
                    self.system_cpu_var.set(f"CPU: {cpu_line}")
                    self.system_gpu_var.set(f"GPU: {gpu_line}")
                    self.system_live_var.set(f"Live: {live_line}")
                    self.system_note_var.set(snapshot.note)
                    self._system_snapshot_running = False
                    self.root.after(SYSTEM_REFRESH_MS, self._request_system_snapshot)
                elif kind == "system_error":
                    self.system_cpu_var.set("CPU: read failed")
                    self.system_gpu_var.set("GPU: read failed")
                    self.system_live_var.set(f"Live: {message[1]}")
                    self.system_note_var.set("Hardware read fell back. The app can still generate meshes.")
                    self._system_snapshot_running = False
                    self.root.after(SYSTEM_REFRESH_MS, self._request_system_snapshot)
                elif kind == "mentor_done":
                    advice = message[1]
                    case_path = message[2]
                    signature = message[3]
                    continue_with_generation = self.pending_start_after_mentor
                    self.pending_start_after_mentor = False
                    self.mentor_running = False
                    self.last_mentor_advice = advice
                    self.last_mentor_case_path = case_path
                    self.last_mentor_signature = signature
                    self.refresh_mentor_summary()
                    self.append_status(
                        f"3DVisual Mesh Mentor finished: {advice.recommended_quality} | "
                        f"{advice.recommended_samples} scan stage(s) | {advice.triangle_target:,} triangles."
                    )
                    if advice.search_terms:
                        self.append_status("Mentor search terms: " + " | ".join(advice.search_terms[:3]))
                    if advice.geometry_risks:
                        self.append_status("Mentor geometry risks: " + "; ".join(advice.geometry_risks[:4]))
                    if case_path is not None:
                        self.append_status(f"Mentor case saved: {case_path}")
                    if continue_with_generation:
                        if self.mentor_advice_is_stale():
                            self.append_status("Mentor result became stale before generation. Re-checking current images and notes.")
                            self.root.after(80, self.start_generation)
                        else:
                            if self.mentor_auto_apply_var.get():
                                self.apply_mentor_hints(skip_validation=True)
                            self.append_status("Mentor auto-run finished. Starting 3D mesh generation...")
                            self.root.after(80, self._start_generation_core)
                elif kind == "mentor_error":
                    continue_with_generation = self.pending_start_after_mentor
                    self.pending_start_after_mentor = False
                    self.mentor_running = False
                    self.refresh_mentor_summary()
                    self._write_log(message[1])
                    self.append_status("3DVisual Mesh Mentor failed.")
                    self.append_status(message[1].splitlines()[0])
                    if continue_with_generation:
                        self.append_status("Mentor auto-run failed. Continuing with current generation settings.")
                        self.root.after(80, self._start_generation_core)
                    else:
                        messagebox.showerror("Mentor failed", message[1].splitlines()[0], parent=self.root)
                elif kind == "done":
                    elapsed_seconds = None
                    if self.generation_started_at is not None:
                        elapsed_seconds = max(0.0, time.monotonic() - self.generation_started_at)
                    self.is_running = False
                    self.pending_options = None
                    self.pending_selection = []
                    self.generation_started_at = None
                    self.current_progress = 100.0
                    self.target_progress = 100.0
                    self._refresh_progress_display()
                    if elapsed_seconds is not None:
                        self.last_elapsed_seconds = elapsed_seconds
                        self._remember_completed_run(elapsed_seconds)
                        self.progress_eta_var.set(f"Done in {self._format_duration(elapsed_seconds)}")
                    self.progress_markers = []
                    self.smoothed_total_seconds = None
                    self.history_predicted_total_seconds = None
                    self.eta_prediction_source = "none"
                    self.active_eta_profile = None
                    result = message[1]
                    self.last_output_path = result.output_path
                    self.update_action_state()

                    lines = [
                        "Finished.",
                        "",
                        f"Saved to Desktop:\n{result.output_path}",
                        "",
                        result.used_input_summary,
                        f"Quality: {result.quality_name}",
                        f"Cleanup: {result.cleanup_mode}",
                        f"Assist profile: {result.subject_profile_note}",
                        f"Chosen scan: {result.selected_sample_index}/{result.samples_ran}",
                        f"Triangle target: {f'{result.target_triangles:,}' if result.target_triangles is not None else 'Auto'}",
                        f"Faces: {result.face_count}",
                        f"Vertices: {result.vertex_count}",
                        f"Seed: {result.seed}",
                        f"Runtime: {result.runtime_profile_note}",
                        f"Review: {result.sample_review_note}",
                    ]
                    if result.raw_output_path:
                        lines.insert(4, f"Raw copy:\n{result.raw_output_path}")
                    self.set_status("\n".join(lines))
                    self._show_result_preview(result)
                    self._play_finish_sound()
                elif kind == "error":
                    self.is_running = False
                    self.pending_options = None
                    self.pending_selection = []
                    self.generation_started_at = None
                    self._reset_progress()
                    self.update_action_state()
                    self.set_status("Generation failed.\n\n" + message[1])
                    self._write_log(message[1])
                    messagebox.showerror("Generation failed", message[1].splitlines()[0], parent=self.root)
        except Empty:
            pass

        self.root.after(200, self._poll_worker_queue)

    def open_desktop_folder(self):
        os.startfile(DESKTOP_DIR)

    def open_result(self):
        if self.last_output_path and self.last_output_path.exists():
            os.startfile(self.last_output_path)

    def run(self):
        self.root.mainloop()


def main():
    app = HunyuanMeshApp()
    app.run()


if __name__ == "__main__":
    main()
