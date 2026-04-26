from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
LAUNCHER_SOURCE = REPO_ROOT / "launchers" / "bootstrap_and_run_3dvisual_mesh.ps1"


@dataclass
class FileEntry:
    source: Path
    arcname: str
    size: int
    offset: int = 0
    is_slice: bool = False


@dataclass
class TextEntry:
    arcname: str
    content: str

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))


def iter_files(root: Path) -> list[tuple[Path, str]]:
    results: list[tuple[Path, str]] = []
    if not root.exists():
        return results
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            results.append((path, rel))
    return results


def resolve_hunyuan_source_dir() -> Path:
    candidates = [
        os.environ.get("THREEVISUAL_HUNYUAN_REPO", ""),
        str(REPO_ROOT / "resources" / "vendor" / "Hunyuan3D-2"),
        str(REPO_ROOT / ".vendor" / "Hunyuan3D-2"),
        "G:/Hunyuan3D-2",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(
        "Hunyuan3D-2 source repo was not found. Run the launcher once first or set THREEVISUAL_HUNYUAN_REPO."
    )


def split_file_entry(source: Path, arc_prefix: str, max_chunk_bytes: int) -> list[FileEntry]:
    size = source.stat().st_size
    if size <= max_chunk_bytes:
        return [FileEntry(source=source, arcname=arc_prefix, size=size)]

    parts: list[FileEntry] = []
    total_parts = math.ceil(size / max_chunk_bytes)
    for index in range(total_parts):
        offset = index * max_chunk_bytes
        length = min(max_chunk_bytes, size - offset)
        parts.append(
            FileEntry(
                source=source,
                arcname=f"{arc_prefix}.part{index + 1:03d}",
                size=length,
                offset=offset,
                is_slice=True,
            )
        )
    return parts


def build_entries(gpu: str, version: str, max_chunk_bytes: int) -> list[object]:
    common_root = REPO_ROOT / "resources" / "wheels" / "common"
    gpu_root = REPO_ROOT / "resources" / "wheels" / gpu
    hunyuan_root = resolve_hunyuan_source_dir()

    if not common_root.exists():
        raise FileNotFoundError(f"Missing wheel directory: {common_root}")
    if not gpu_root.exists():
        raise FileNotFoundError(f"Missing wheel directory: {gpu_root}")

    readme = TextEntry(
        arcname="HOTFIX_README.txt",
        content=(
            f"3DVisual Mesh {version} install hotfix for {gpu.upper()}\r\n"
            "\r\n"
            "How to use:\r\n"
            "1. Extract every hotfix zip into the same 3DVisual Mesh folder.\r\n"
            "2. Let the files merge into the existing resources folder.\r\n"
            "3. Double-click Repair Install.exe.\r\n"
            "4. Then double-click Start 3DVisual Mesh.exe again.\r\n"
            "\r\n"
            "This hotfix supplies missing wheel files and an updated launcher that can rebuild split wheel parts automatically.\r\n"
        ),
    )

    entries: list[object] = [readme]
    entries.append(
        FileEntry(
            source=LAUNCHER_SOURCE,
            arcname="resources/launchers/bootstrap_and_run_3dvisual_mesh.ps1",
            size=LAUNCHER_SOURCE.stat().st_size,
        )
    )

    for source, rel in iter_files(hunyuan_root):
        entries.append(
            FileEntry(
                source=source,
                arcname=f"resources/vendor/Hunyuan3D-2/{rel}",
                size=source.stat().st_size,
            )
        )

    for source, rel in iter_files(common_root):
        entries.append(
            FileEntry(
                source=source,
                arcname=f"resources/wheels/common/{rel}",
                size=source.stat().st_size,
            )
        )

    for source, rel in iter_files(gpu_root):
        entries.extend(split_file_entry(source, f"resources/wheels/{gpu}/{rel}", max_chunk_bytes))

    return entries


def pack_entries(entries: list[object], max_zip_bytes: int) -> list[list[object]]:
    parts: list[list[object]] = []
    current: list[object] = []
    current_size = 0

    for entry in entries:
        entry_size = entry.size
        if current and current_size + entry_size > max_zip_bytes:
            parts.append(current)
            current = []
            current_size = 0
        current.append(entry)
        current_size += entry_size

    if current:
        parts.append(current)
    return parts


def write_slice(zip_file: ZipFile, entry: FileEntry) -> None:
    info = ZipInfo(entry.arcname)
    info.compress_type = ZIP_STORED
    with entry.source.open("rb") as handle:
        handle.seek(entry.offset)
        remaining = entry.size
        with zip_file.open(info, "w") as writer:
            while remaining > 0:
                chunk = handle.read(min(8 * 1024 * 1024, remaining))
                if not chunk:
                    break
                writer.write(chunk)
                remaining -= len(chunk)


def build_archives(gpu: str, version: str, max_zip_bytes: int, max_chunk_bytes: int) -> list[Path]:
    entries = build_entries(gpu, version, max_chunk_bytes)
    packed = pack_entries(entries, max_zip_bytes)
    outputs: list[Path] = []

    for idx, part_entries in enumerate(packed, start=1):
        archive_path = DIST_DIR / f"3DVisualMesh_{version}_{gpu.upper()}_Install_Hotfix_Part{idx}.zip"
        if archive_path.exists():
            archive_path.unlink()

        with ZipFile(archive_path, "w", compression=ZIP_STORED, allowZip64=True) as zf:
            for entry in part_entries:
                if isinstance(entry, TextEntry):
                    zf.writestr(entry.arcname, entry.content)
                elif entry.is_slice:
                    write_slice(zf, entry)
                else:
                    zf.write(entry.source, entry.arcname, compress_type=ZIP_STORED)
        outputs.append(archive_path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build release-friendly install hotfix archives.")
    parser.add_argument("--gpu", choices=["amd", "nvidia", "both"], default="both")
    parser.add_argument("--version", default="0.1.1")
    parser.add_argument("--max-zip-gb", type=float, default=1.9)
    parser.add_argument("--max-chunk-gb", type=float, default=1.8)
    args = parser.parse_args()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    max_zip_bytes = int(args.max_zip_gb * (1024 ** 3))
    max_chunk_bytes = int(args.max_chunk_gb * (1024 ** 3))

    gpus = ["amd", "nvidia"] if args.gpu == "both" else [args.gpu]
    for gpu in gpus:
        outputs = build_archives(gpu, args.version, max_zip_bytes, max_chunk_bytes)
        print(f"{gpu.upper()} hotfix archives:")
        for path in outputs:
            size_gb = path.stat().st_size / (1024 ** 3)
            print(f"  {path} ({size_gb:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
