import argparse
import io
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, abort, render_template, request, send_file
from werkzeug.utils import secure_filename

# Handle both direct execution and package import
try:
    from ..core import (
        SUPPORTED_EXTENSIONS,
        DEFAULT_QUALITY,
        convert_image,
        format_bytes,
    )
except ImportError:
    # If relative import fails, add src directory to path
    current_dir = Path(__file__).parent
    # From src/imgtowebp/web/app.py, go up to src/
    src_dir = current_dir.parent.parent
    sys.path.insert(0, str(src_dir))
    from imgtowebp.core import (
        SUPPORTED_EXTENSIONS,
        DEFAULT_QUALITY,
        convert_image,
        format_bytes,
    )

@dataclass
class UploadItemResult:
    original_name: str
    status: str
    message: str
    output_relpath: str | None = None
    input_bytes: int = 0
    output_bytes: int = 0

def safe_subdir(subdir: str) -> Path:
    subdir = (subdir or "").strip()
    if not subdir:
        return Path(".")

    candidate = Path(subdir)
    if candidate.is_absolute():
        return Path(".")

    cleaned_parts: list[str] = []
    for part in candidate.parts:
        if part in ("", ".", ".."):
            continue
        cleaned_parts.append(part)

    return Path(*cleaned_parts) if cleaned_parts else Path(".")


def resolve_output_file(output_dir: Path, relative_path: str) -> Path | None:
    """Return absolute file path if relative_path is safe and file exists under output_dir."""
    if not relative_path or not relative_path.strip():
        return None
    rel = Path(relative_path.strip())
    if rel.is_absolute():
        return None
    if ".." in rel.parts:
        return None
    full = (output_dir / rel).resolve()
    od = output_dir.resolve()
    try:
        full.relative_to(od)
    except ValueError:
        return None
    if not full.is_file():
        return None
    return full


def create_app(output_dir: Path) -> Flask:
    # Use absolute paths for templates and static files
    web_dir = Path(__file__).parent
    app = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            results=None,
            summary=None,
            output_dir=str(output_dir),
            zip_relpaths=[],
        )

    @app.post("/upload")
    def upload() -> str:
        files = request.files.getlist("files")
        quality_raw = request.form.get("quality", str(DEFAULT_QUALITY))
        overwrite = request.form.get("overwrite") == "on"
        subdir = safe_subdir(request.form.get("subdir", ""))

        try:
            quality = int(quality_raw)
        except ValueError:
            quality = DEFAULT_QUALITY

        quality = max(0, min(100, quality))

        results: list[UploadItemResult] = []
        total_in = 0
        total_out = 0
        converted = 0
        skipped = 0
        failed = 0

        target_dir = (output_dir / subdir).resolve()
        # Security check to ensure target is within output_dir
        if output_dir.resolve() not in target_dir.parents and target_dir != output_dir.resolve():
            target_dir = output_dir.resolve()

        target_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            if not f or not f.filename:
                continue

            original_name = f.filename
            safe_name = secure_filename(original_name)
            ext = Path(safe_name).suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                skipped += 1
                results.append(UploadItemResult(original_name, "skipped", "Unsupported file type."))
                continue

            stem = Path(safe_name).stem
            out_path = target_dir / f"{stem}.webp"

            data = f.read()
            if not data:
                skipped += 1
                results.append(UploadItemResult(original_name, "skipped", "Empty file."))
                continue

            res = convert_image(data, out_path, quality=quality, overwrite=overwrite)

            if res.success:
                total_in += res.input_size
                total_out += res.output_size
                converted += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="converted",
                        message="Saved.",
                        output_relpath=out_path.relative_to(output_dir).as_posix(),
                        input_bytes=res.input_size,
                        output_bytes=res.output_size,
                    )
                )
            else:
                if "exists" in res.message:
                    skipped += 1
                    results.append(
                        UploadItemResult(
                            original_name=original_name,
                            status="skipped",
                            message=res.message,
                            output_relpath=out_path.relative_to(output_dir).as_posix(),
                        )
                    )
                else:
                    failed += 1
                    results.append(UploadItemResult(original_name, "failed", res.message))

        saved_bytes = total_in - total_out
        saved_pct = (saved_bytes / total_in * 100.0) if total_in > 0 else 0.0

        summary: dict[str, Any] = {
            "files_received": len(files),
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "total_input": format_bytes(total_in),
            "total_output": format_bytes(total_out),
            "saved": format_bytes(saved_bytes),
            "saved_pct": f"{saved_pct:.2f}%",
            "output_dir": str(output_dir),
            "subdir": str(subdir),
            "overwrite": overwrite,
            "quality": quality,
        }

        zip_relpaths = [
            r.output_relpath
            for r in results
            if r.output_relpath
            and (
                r.status == "converted"
                or (r.status == "skipped" and "exists" in r.message.lower())
            )
        ]

        return render_template(
            "index.html",
            results=results,
            summary=summary,
            output_dir=str(output_dir),
            zip_relpaths=zip_relpaths,
        )

    @app.get("/download/<path:relative_path>")
    def download_file(relative_path: str):
        path = resolve_output_file(output_dir, relative_path)
        if path is None:
            abort(404)
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype="image/webp",
        )

    @app.post("/download-zip")
    def download_zip():
        paths = request.form.getlist("paths")
        if not paths:
            abort(400)
        buffer = io.BytesIO()
        added = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in paths:
                path = resolve_output_file(output_dir, rel.strip())
                if path is None:
                    continue
                arc = Path(rel.strip()).as_posix()
                zf.write(path, arcname=arc)
                added += 1
        if added == 0:
            abort(404)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name="imgtowebp-images.zip",
        )

    return app

def run_web() -> None:
    parser = argparse.ArgumentParser(description="Web UI for WebP conversion.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--output-dir", default="webp_output", help="Output directory.")
    
    args = parser.parse_args()
    app = create_app(Path(args.output_dir).resolve())
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host=args.host, port=args.port, debug=True)

if __name__ == "__main__":
    run_web()
