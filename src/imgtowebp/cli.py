import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Handle both direct execution and package import
try:
    from .core import (
        SUPPORTED_EXTENSIONS,
        DEFAULT_QUALITY,
        convert_image,
        format_bytes,
    )
except ImportError:
    # If relative import fails, add src directory to path
    current_dir = Path(__file__).parent
    # From src/imgtowebp/cli.py, go up to src/
    src_dir = current_dir.parent
    sys.path.insert(0, str(src_dir))
    from imgtowebp.core import (
        SUPPORTED_EXTENSIONS,
        DEFAULT_QUALITY,
        convert_image,
        format_bytes,
    )

@dataclass
class ConversionStats:
    scanned: int = 0
    eligible: int = 0
    converted: int = 0
    skipped_existing: int = 0
    deleted_originals: int = 0
    failed: int = 0
    total_input_bytes: int = 0
    total_output_bytes: int = 0
    total_deleted_bytes: int = 0

def iter_images(directory: Path, recursive: bool) -> Iterable[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    for path in iterator:
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path

def print_summary(stats: ConversionStats) -> None:
    print("\nSummary:")
    print(f"  Scanned files: {stats.scanned}")
    print(f"  Eligible images: {stats.eligible}")
    print(f"  Converted: {stats.converted}")
    print(f"  Skipped (existing webp): {stats.skipped_existing}")
    print(f"  Deleted originals: {stats.deleted_originals}")
    print(f"  Failed: {stats.failed}")

    if stats.converted > 0:
        before_b = stats.total_input_bytes
        after_b = stats.total_output_bytes
        delta_b = before_b - after_b
        saved_pct = (delta_b / before_b * 100.0) if before_b > 0 else 0.0
        
        print(f"  Total size before (converted): {format_bytes(before_b)}")
        print(f"  Total size after  (webp):      {format_bytes(after_b)}")
        print(f"  Saved: {format_bytes(delta_b)} ({saved_pct:.2f}%)")
    
    if stats.deleted_originals > 0:
        print(f"  Deleted bytes (originals): {format_bytes(stats.total_deleted_bytes)}")

def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Batch convert images to WebP.")
    parser.add_argument("--dir", default=".", help="Target directory (default: current).")
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY, help=f"Quality 0-100 (default: {DEFAULT_QUALITY}).")
    parser.add_argument("--no-recursive", action="store_true", help="Do not scan subdirectories.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .webp files.")
    parser.add_argument("--replace", action="store_true", help="Delete original image after conversion.")
    
    args = parser.parse_args()
    directory = Path(args.dir).resolve()
    
    if not (0 <= args.quality <= 100):
        print("Error: --quality must be between 0 and 100", file=sys.stderr)
        sys.exit(1)

    stats = ConversionStats()
    # Simple scanned count for all files in directory
    stats.scanned = len([f for f in directory.iterdir() if f.is_file()])

    for src_path in iter_images(directory, not args.no_recursive):
        stats.eligible += 1
        dst_path = src_path.with_suffix(".webp")

        res = convert_image(
            src_path,
            dst_path,
            quality=args.quality,
            overwrite=args.overwrite
        )

        if res.success:
            stats.converted += 1
            stats.total_input_bytes += res.input_size
            stats.total_output_bytes += res.output_size
            print(f"Converted: {src_path.name} -> {dst_path.name}")
            
            if args.replace:
                try:
                    src_size = src_path.stat().st_size
                    src_path.unlink()
                    stats.deleted_originals += 1
                    stats.total_deleted_bytes += src_size
                    print(f"Deleted original: {src_path.name}")
                except Exception as e:
                    print(f"Failed to delete {src_path.name}: {e}")
        else:
            if "exists" in res.message:
                stats.skipped_existing += 1
                # If we want to replace even if webp already exists
                if args.replace:
                    try:
                        src_size = src_path.stat().st_size
                        src_path.unlink()
                        stats.deleted_originals += 1
                        stats.total_deleted_bytes += src_size
                        print(f"Deleted original (WebP exists): {src_path.name}")
                    except Exception as e:
                        print(f"Failed to delete {src_path.name}: {e}")
            else:
                stats.failed += 1
                print(f"Failed {src_path.name}: {res.message}")

    print_summary(stats)

if __name__ == "__main__":
    run_cli()
