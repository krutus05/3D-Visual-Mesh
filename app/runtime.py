from __future__ import annotations

import sys

from .config import HUNYUAN_REPO


RUNTIME = {
    "torch": None,
    "BackgroundRemover": None,
    "Pipeline": None,
    "FloaterRemover": None,
    "DegenerateFaceRemover": None,
    "FaceReducer": None,
    "bg_remover": None,
    "single_pipeline": None,
    "mv_pipeline": None,
    "floater": None,
    "degenerate": None,
    "reducer": None,
}


def ensure_runtime():
    if not HUNYUAN_REPO.exists():
        raise RuntimeError(f"Hunyuan repo not found at {HUNYUAN_REPO}")

    if str(HUNYUAN_REPO) not in sys.path:
        sys.path.insert(0, str(HUNYUAN_REPO))

    if RUNTIME["torch"] is None:
        import torch
        from hy3dgen.rembg import BackgroundRemover
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        from hy3dgen.shapegen.postprocessors import (
            DegenerateFaceRemover,
            FaceReducer,
            FloaterRemover,
        )

        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass

        RUNTIME["torch"] = torch
        RUNTIME["BackgroundRemover"] = BackgroundRemover
        RUNTIME["Pipeline"] = Hunyuan3DDiTFlowMatchingPipeline
        RUNTIME["FloaterRemover"] = FloaterRemover
        RUNTIME["DegenerateFaceRemover"] = DegenerateFaceRemover
        RUNTIME["FaceReducer"] = FaceReducer

    return (
        RUNTIME["torch"],
        RUNTIME["BackgroundRemover"],
        RUNTIME["Pipeline"],
        RUNTIME["FloaterRemover"],
        RUNTIME["DegenerateFaceRemover"],
        RUNTIME["FaceReducer"],
    )


def get_bg_remover():
    _, BackgroundRemover, _, _, _, _ = ensure_runtime()
    if RUNTIME["bg_remover"] is None:
        RUNTIME["bg_remover"] = BackgroundRemover()
    return RUNTIME["bg_remover"]


def get_pipeline(multiview: bool, border_ratio: float):
    _, _, Pipeline, _, _, _ = ensure_runtime()

    if multiview:
        if RUNTIME["mv_pipeline"] is None:
            RUNTIME["mv_pipeline"] = Pipeline.from_pretrained(
                "tencent/Hunyuan3D-2mv",
                subfolder="hunyuan3d-dit-v2-mv",
                variant="fp16",
            )
        pipeline = RUNTIME["mv_pipeline"]
    else:
        if RUNTIME["single_pipeline"] is None:
            RUNTIME["single_pipeline"] = Pipeline.from_pretrained(
                "tencent/Hunyuan3D-2",
                subfolder="hunyuan3d-dit-v2-0",
                variant="fp16",
            )
        pipeline = RUNTIME["single_pipeline"]

    pipeline.image_processor.border_ratio = border_ratio
    return pipeline


def get_cleanup_workers():
    _, _, _, FloaterRemover, DegenerateFaceRemover, FaceReducer = ensure_runtime()

    if RUNTIME["floater"] is None:
        RUNTIME["floater"] = FloaterRemover()
    if RUNTIME["degenerate"] is None:
        RUNTIME["degenerate"] = DegenerateFaceRemover()
    if RUNTIME["reducer"] is None:
        RUNTIME["reducer"] = FaceReducer()

    return RUNTIME["floater"], RUNTIME["degenerate"], RUNTIME["reducer"]

