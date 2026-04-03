import argparse
import base64
import io
import os
import secrets
import shutil
import sys
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from PIL import Image
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


# Inline ZIP in the upload HTML avoids a second HTTP request (needed on serverless
# where /tmp may not exist on a different instance than /upload).
MAX_INLINE_ZIP_BYTES = 4 * 1024 * 1024

# Ephemeral Web UI output: each browser session writes under output_dir/_sessions/<id>/.
SESSION_WORKSPACE_KEY = "imgtowebp_ws"
SESSIONS_DIRNAME = "_sessions"
# One-shot conversion payload for PRG: GET / consumes it; refresh hits empty session -> GET /.
SESSION_RESULTS_ONCE_KEY = "imgtowebp_results_once"


def _is_safe_workspace_id(workspace_id: str) -> bool:
    if not isinstance(workspace_id, str) or len(workspace_id) != 32:
        return False
    return all(c in "0123456789abcdef" for c in workspace_id.lower())


def ensure_workspace_session_id() -> str:
    raw = session.get(SESSION_WORKSPACE_KEY)
    if isinstance(raw, str) and _is_safe_workspace_id(raw):
        wid = raw.lower()
        session[SESSION_WORKSPACE_KEY] = wid
        return wid
    wid = uuid.uuid4().hex
    session[SESSION_WORKSPACE_KEY] = wid
    return wid


def session_workspace_dir(output_dir: Path, workspace_id: str) -> Path:
    return output_dir / SESSIONS_DIRNAME / workspace_id.lower()


def clear_session_workspace(output_dir: Path, workspace_id: str) -> None:
    if not _is_safe_workspace_id(workspace_id):
        return
    root = session_workspace_dir(output_dir, workspace_id)
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def is_path_under(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_zip_bytes(output_dir: Path, relpaths: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in relpaths:
            path = resolve_output_file(output_dir, rel.strip())
            if path is None:
                continue
            zf.write(path, arcname=Path(rel.strip()).as_posix())
    return buffer.getvalue()


def is_decodable_raster_image(data: bytes) -> bool:
    """True if Pillow can decode bytes as a raster image (excludes SVG etc.)."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
        return True
    except Exception:
        return False


def _load_repo_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    load_dotenv(repo_root / ".env")


def create_app(output_dir: Path) -> Flask:
    # Load repo-root .env (gitignored) so FLASK_SECRET_KEY can be set locally without exporting env vars.
    _load_repo_dotenv()

    # Use absolute paths for templates and static files
    web_dir = Path(__file__).parent
    app = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("IMGTOWEBP_SECRET_KEY")
        or secrets.token_hex(32)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> str:
        session.pop(SESSION_RESULTS_ONCE_KEY, None)
        wid = ensure_workspace_session_id()
        clear_session_workspace(output_dir, wid)
        return render_template(
            "index.html",
            results=None,
            summary=None,
            zip_relpaths=[],
            inline_zip_b64=None,
            zip_fallback_only=False,
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

        wid = ensure_workspace_session_id()
        clear_session_workspace(output_dir, wid)
        ws = session_workspace_dir(output_dir, wid)
        ws.mkdir(parents=True, exist_ok=True)

        target_dir = (ws / subdir).resolve()
        if not is_path_under(ws, target_dir):
            target_dir = ws.resolve()

        target_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            if not f or not f.filename:
                continue

            original_name = f.filename
            safe_name = secure_filename(original_name)
            ext = Path(safe_name).suffix.lower()
            stem = Path(safe_name).stem or "image"

            data = f.read()
            if not data:
                skipped += 1
                results.append(UploadItemResult(original_name, "skipped", "Empty file."))
                continue

            if ext not in SUPPORTED_EXTENSIONS and not is_decodable_raster_image(data):
                skipped += 1
                results.append(
                    UploadItemResult(
                        original_name,
                        "skipped",
                        "Unsupported or unreadable image.",
                    )
                )
                continue

            out_path = target_dir / f"{stem}.webp"

            res = convert_image(data, out_path, quality=quality, overwrite=overwrite)

            if res.success:
                total_in += res.input_size
                total_out += res.output_size
                converted += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="converted",
                        message="Ready to download.",
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

        zip_fallback_only_flag = False
        if zip_relpaths:
            zdata = build_zip_bytes(output_dir, zip_relpaths)
            if len(zdata) > MAX_INLINE_ZIP_BYTES:
                zip_fallback_only_flag = True

        session[SESSION_RESULTS_ONCE_KEY] = {
            "results": [asdict(r) for r in results],
            "summary": summary,
            "zip_relpaths": zip_relpaths,
            "zip_fallback_only": zip_fallback_only_flag,
        }
        return redirect(url_for("results"), code=303)

    @app.get("/results")
    def results() -> Any:
        raw = session.pop(SESSION_RESULTS_ONCE_KEY, None)
        if not raw:
            return redirect(url_for("index"), code=302)
        results_list = [UploadItemResult(**item) for item in raw["results"]]
        summary = raw["summary"]
        zip_relpaths = raw["zip_relpaths"]
        zip_fallback_only = bool(raw["zip_fallback_only"])

        inline_zip_b64: str | None = None
        if zip_relpaths and not zip_fallback_only:
            zdata = build_zip_bytes(output_dir, zip_relpaths)
            if len(zdata) <= MAX_INLINE_ZIP_BYTES:
                inline_zip_b64 = base64.b64encode(zdata).decode("ascii")
            else:
                zip_fallback_only = True

        return render_template(
            "index.html",
            results=results_list,
            summary=summary,
            zip_relpaths=zip_relpaths,
            inline_zip_b64=inline_zip_b64,
            zip_fallback_only=zip_fallback_only,
        )

    @app.post("/session/discard")
    def discard_session_workspace() -> tuple[str, int]:
        raw = session.get(SESSION_WORKSPACE_KEY)
        if isinstance(raw, str) and _is_safe_workspace_id(raw):
            clear_session_workspace(output_dir, raw)
        return ("", 204)

    @app.get("/preview/<path:relative_path>")
    def preview_file(relative_path: str):
        """Inline WebP for list thumbnails (not Content-Disposition: attachment)."""
        path = resolve_output_file(output_dir, relative_path)
        if path is None:
            abort(404)
        return send_file(
            path,
            as_attachment=False,
            mimetype="image/webp",
            max_age=300,
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
        zdata = build_zip_bytes(output_dir, paths)
        if not zdata:
            abort(404)
        buffer = io.BytesIO(zdata)
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
