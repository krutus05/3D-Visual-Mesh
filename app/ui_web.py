from __future__ import annotations

from pathlib import Path

import gradio as gr

from .config import CLEANUP_OPTIONS, DEFAULT_CLEANUP, DEFAULT_QUALITY, QUALITY_PRESETS
from .generation import GenerationOptions, SelectedImage, generate_mesh


def on_generate(files, output_name: str, quality_name: str, cleanup_mode: str, remove_background: bool, keep_raw_copy: bool):
    if not files:
        raise gr.Error("Drop at least one image first.")

    selected_images = [SelectedImage(path=Path(path)) for path in files if path]
    result = generate_mesh(
        selected_images,
        GenerationOptions(
            output_name=output_name or "3dvisual_mesh",
            quality_name=quality_name,
            cleanup_mode=cleanup_mode,
            remove_background=remove_background,
            keep_raw_copy=keep_raw_copy,
        ),
    )

    lines = [
        f"Saved mesh to:\n{result.output_path}",
        "",
        result.used_input_summary,
        f"Quality: {result.quality_name}",
        f"Cleanup: {result.cleanup_mode}",
        f"Faces: {result.face_count}",
        f"Vertices: {result.vertex_count}",
        f"Seed: {result.seed}",
        f"Note: {result.note}",
    ]
    if result.raw_output_path:
        lines.insert(2, f"Raw copy:\n{result.raw_output_path}")

    return str(result.output_path), str(result.output_path), "\n".join(lines)


with gr.Blocks(title="3DVisual Mesh Web") as demo:
    gr.Markdown(
        """
        # 3DVisual Mesh Web
        Drop one image or up to four views, then click Generate.

        Notes:
        - 1 image uses single-image mode
        - 2-4 images use multiview mode
        - best filenames include `front`, `left`, `back`, `right`
        - 4K inputs are still resized internally, so framing matters more than raw resolution
        - the native desktop app is still the main polished workflow
        """
    )

    files = gr.File(
        label="Drop Reference Images Here",
        file_count="multiple",
        file_types=["image"],
        type="filepath",
    )
    output_name = gr.Textbox(label="Output Name", value="3dvisual_mesh")

    with gr.Row():
        quality_name = gr.Dropdown(label="Quality", choices=list(QUALITY_PRESETS.keys()), value=DEFAULT_QUALITY)
        cleanup_mode = gr.Dropdown(label="Cleanup", choices=CLEANUP_OPTIONS, value=DEFAULT_CLEANUP)

    with gr.Row():
        remove_background = gr.Checkbox(label="Remove Background", value=True)
        keep_raw_copy = gr.Checkbox(label="Keep Raw Copy", value=False)

    generate_button = gr.Button("Generate Mesh", variant="primary")
    preview = gr.Model3D(label="Preview")
    download = gr.File(label="Desktop Output")
    status = gr.Textbox(label="Status", lines=10)

    generate_button.click(
        on_generate,
        inputs=[files, output_name, quality_name, cleanup_mode, remove_background, keep_raw_copy],
        outputs=[preview, download, status],
    )


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7862, inbrowser=True)
