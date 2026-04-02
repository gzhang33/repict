import io
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DEFAULT_QUALITY = 80

@dataclass
class ConversionResult:
    success: bool
    message: str
    input_size: int = 0
    output_size: int = 0
    saved_bytes: int = 0

def ensure_webp_compatible_mode(img: Image.Image) -> Image.Image:
    """Ensure the image is in a mode compatible with WebP (RGB or RGBA)."""
    if img.mode in ("RGB", "RGBA"):
        return img
    if "A" in img.getbands():
        return img.convert("RGBA")
    return img.convert("RGB")

def format_bytes(num_bytes: int) -> str:
    """Format bytes into a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"

def convert_image(
    input_data: bytes | Path,
    output_path: Path,
    quality: int = DEFAULT_QUALITY,
    overwrite: bool = False,
) -> ConversionResult:
    """
    Core image conversion logic.
    Supports both file paths and raw bytes as input.
    """
    if output_path.exists() and not overwrite:
        return ConversionResult(False, "Output file already exists and overwrite is disabled.")

    try:
        if isinstance(input_data, Path):
            input_size = input_data.stat().st_size
            img = Image.open(input_data)
        else:
            input_size = len(input_data)
            img = Image.open(io.BytesIO(input_data))

        with img:
            img = ensure_webp_compatible_mode(img)
            img.save(output_path, "WEBP", quality=quality, method=6)

        output_size = output_path.stat().st_size
        saved_bytes = input_size - output_size
        
        return ConversionResult(
            success=True,
            message="Successfully converted",
            input_size=input_size,
            output_size=output_size,
            saved_bytes=saved_bytes
        )
    except Exception as e:
        return ConversionResult(False, f"Error during conversion: {str(e)}")
