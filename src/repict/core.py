import io
from dataclasses import dataclass
from pathlib import Path
from typing import Union
from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except (ImportError, RuntimeError):
    HEIC_SUPPORTED = False

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
if HEIC_SUPPORTED:
    SUPPORTED_EXTENSIONS.update({".heic", ".heif"})
DEFAULT_QUALITY = 100

@dataclass
class ConversionResult:
    success: bool
    message: str
    input_size: int = 0
    output_size: int = 0
    saved_bytes: int = 0

def ensure_compatible_mode(img: Image.Image, output_format: str = "webp") -> Image.Image:
    """Ensure the image is in a mode compatible with the target output format."""
    # JPEG does not support alpha — strip transparency
    if output_format.lower() in ("jpeg", "jpg"):
        if img.mode == "RGBA":
            # Composite onto white background to preserve appearance
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        if img.mode != "RGB":
            return img.convert("RGB")
        return img
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
    input_data: Union[bytes, Path],
    output_path: Path,
    quality: int = DEFAULT_QUALITY,
    overwrite: bool = False,
    output_format: str = "webp",
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

        fmt = output_format.lower()
        if fmt == "jpg":
            fmt = "jpeg"

        with img:
            converted_img = ensure_compatible_mode(img, output_format=fmt)
            try:
                if fmt in ("heic", "heif"):
                    if not HEIC_SUPPORTED:
                        return ConversionResult(False, "HEIC/HEIF conversion is not supported. Please install pillow-heif.")
                    converted_img.save(output_path, "HEIF", quality=quality)
                elif fmt == "jpeg":
                    converted_img.save(output_path, "JPEG", quality=quality)
                elif fmt == "png":
                    converted_img.save(output_path, "PNG")
                else:
                    converted_img.save(output_path, "WEBP", quality=quality, method=6)
            finally:
                if converted_img is not img:
                    converted_img.close()

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
