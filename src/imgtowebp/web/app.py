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
from typing import Any, Optional, Union

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from PIL import Image
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

# Handle both direct execution and package import
try:
    from ..core import (
        SUPPORTED_EXTENSIONS,
        DEFAULT_QUALITY,
        convert_image,
        format_bytes,
        HEIC_SUPPORTED,
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
        HEIC_SUPPORTED,
    )

@dataclass
class UploadItemResult:
    original_name: str
    status: str
    message: str
    output_relpath: Optional[str] = None
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


def resolve_output_file(output_dir: Path, relative_path: str) -> Optional[Path]:
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
# Keep a safety margin under Vercel's 4.5MB request payload limit.
UPLOAD_TOTAL_LIMIT_BYTES = 4 * 1024 * 1024
UPLOAD_FILE_LIMIT_BYTES = 4 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
if HEIC_SUPPORTED:
    ALLOWED_MIME_TYPES.update({"image/heic", "image/heif"})
ALLOWED_EXTENSIONS = set(SUPPORTED_EXTENSIONS)
ALLOWED_FORMATS_DISPLAY = "/".join(ext.replace(".", "").upper() for ext in sorted(ALLOWED_EXTENSIONS) if ext)

# Ephemeral Web UI output: each browser session writes under output_dir/_sessions/<id>/.
SESSION_WORKSPACE_KEY = "imgtowebp_ws"
SESSIONS_DIRNAME = "_sessions"
# One-shot conversion payload for PRG: GET / consumes it; refresh hits empty session -> GET /.
SESSION_RESULTS_ONCE_KEY = "imgtowebp_results_once"
SESSION_FORM_ERROR_ONCE_KEY = "imgtowebp_form_error_once"


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


def normalize_mimetype(raw: Optional[str]) -> str:
    return (raw or "").split(";", 1)[0].strip().lower()


def limit_label(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.0f} MB"


def validate_upload_payload(
    *,
    filename: str,
    ext: str,
    data: bytes,
    mimetype: Optional[str],
) -> Optional[str]:
    if not data:
        return "Empty file."
    if len(data) > UPLOAD_FILE_LIMIT_BYTES:
        return f"Single file is too large. Keep each file under {limit_label(UPLOAD_FILE_LIMIT_BYTES)}."
    if ext not in ALLOWED_EXTENSIONS:
        return f"Unsupported file type. Only {ALLOWED_FORMATS_DISPLAY} are allowed."
    normalized_mime = normalize_mimetype(mimetype)
    if normalized_mime and normalized_mime not in ALLOWED_MIME_TYPES:
        return f"Unsupported file type. Please upload a {ALLOWED_FORMATS_DISPLAY} image."
    if not is_decodable_raster_image(data):
        return "Unsupported or unreadable image."
    return None


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
    app.config["MAX_CONTENT_LENGTH"] = UPLOAD_TOTAL_LIMIT_BYTES
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("IMGTOWEBP_SECRET_KEY")
        or secrets.token_hex(32)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    upload_policy: dict[str, Any] = {
        "max_total_bytes": UPLOAD_TOTAL_LIMIT_BYTES,
        "max_file_bytes": UPLOAD_FILE_LIMIT_BYTES,
        "allowed_mime_types": sorted(ALLOWED_MIME_TYPES),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "allowed_formats_label": "/".join(ext.replace(".", "").upper() for ext in sorted(ALLOWED_EXTENSIONS) if ext),
    }

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error: RequestEntityTooLarge):
        session[SESSION_FORM_ERROR_ONCE_KEY] = (
            f"Upload is too large. Keep total upload size under {limit_label(UPLOAD_TOTAL_LIMIT_BYTES)}."
        )
        return redirect(url_for("index"), code=303)

    @app.get("/")
    def index() -> str:
        session.pop(SESSION_RESULTS_ONCE_KEY, None)
        wid = ensure_workspace_session_id()
        clear_session_workspace(output_dir, wid)
        form_error = session.pop(SESSION_FORM_ERROR_ONCE_KEY, None)
        return render_template(
            "index.html",
            results=None,
            summary=None,
            zip_relpaths=[],
            inline_zip_b64=None,
            zip_fallback_only=False,
            form_error=form_error,
            upload_policy=upload_policy,
        )

    @app.post("/upload")
    def upload() -> str:
        files = request.files.getlist("files")
        quality_raw = request.form.get("quality", str(DEFAULT_QUALITY))
        overwrite = request.form.get("overwrite") == "on"
        subdir = safe_subdir(request.form.get("subdir", ""))
        output_format = request.form.get("format", "webp").lower()
        if output_format not in ["webp", "heic"]:
            output_format = "webp"

        try:
            quality = int(quality_raw)
        except ValueError:
            quality = DEFAULT_QUALITY

        quality = max(0, min(100, quality))

        results: list[UploadItemResult] = []
        total_in = 0
        total_out = 0
        total_received = 0
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
            total_received += len(data)
            if total_received > UPLOAD_TOTAL_LIMIT_BYTES:
                session[SESSION_FORM_ERROR_ONCE_KEY] = (
                    f"Upload is too large. Keep total upload size under {limit_label(UPLOAD_TOTAL_LIMIT_BYTES)}."
                )
                return redirect(url_for("index"), code=303)

            validation_error = validate_upload_payload(
                filename=original_name,
                ext=ext,
                data=data,
                mimetype=f.mimetype,
            )
            if validation_error:
                skipped += 1
                results.append(
                    UploadItemResult(
                        original_name,
                        "skipped",
                        validation_error,
                    )
                )
                continue

            out_ext = f".{output_format}"
            out_path = target_dir / f"{stem}{out_ext}"

            res = convert_image(data, out_path, quality=quality, overwrite=overwrite, output_format=output_format)

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
            "output_format": output_format,
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

        inline_zip_b64: Optional[str] = None
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
            form_error=None,
            upload_policy=upload_policy,
        )

    @app.post("/session/discard")
    def discard_session_workspace() -> tuple[str, int]:
        raw = session.get(SESSION_WORKSPACE_KEY)
        if isinstance(raw, str) and _is_safe_workspace_id(raw):
            clear_session_workspace(output_dir, raw)
        return ("", 204)

    @app.get("/preview/<path:relative_path>")
    def preview_file(relative_path: str):
        path = resolve_output_file(output_dir, relative_path)
        if path is None:
            abort(404)
        ext = path.suffix.lower()
        mimetype = "image/heic" if ext in (".heic", ".heif") else "image/webp"
        return send_file(
            path,
            as_attachment=False,
            mimetype=mimetype,
            max_age=300,
        )

    @app.get("/download/<path:relative_path>")
    def download_file(relative_path: str):
        path = resolve_output_file(output_dir, relative_path)
        if path is None:
            abort(404)
        ext = path.suffix.lower()
        mimetype = "image/heic" if ext in (".heic", ".heif") else "image/webp"
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype=mimetype,
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
