import io
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from imgtowebp.web.app import create_app, validate_upload_payload, ALLOWED_FORMATS_DISPLAY  # noqa: E402
from imgtowebp.core import HEIC_SUPPORTED


class UploadValidationTests(unittest.TestCase):
    def test_validate_upload_payload_rejects_bad_extension(self):
        message = validate_upload_payload(
            filename="file.pdf",
            ext=".pdf",
            data=b"not-an-image",
            mimetype="application/pdf",
        )
        self.assertEqual(message, f"Unsupported file type. Only {ALLOWED_FORMATS_DISPLAY} are allowed.")

    def test_validate_upload_payload_rejects_large_file(self):
        data = b"a" * (4 * 1024 * 1024 + 1)
        message = validate_upload_payload(
            filename="large.jpg",
            ext=".jpg",
            data=data,
            mimetype="image/jpeg",
        )
        self.assertEqual(message, "Single file is too large. Keep each file under 4 MB.")

    def test_upload_413_redirect_shows_user_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Path(tmp))
            app.config.update(TESTING=True, MAX_CONTENT_LENGTH=128)
            client = app.test_client()

            data = {"files": (io.BytesIO(b"a" * 512), "big.jpg")}
            response = client.post(
                "/upload",
                data=data,
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                b"Upload is too large. Keep total upload size under 4 MB.",
                response.data,
            )

class ConversionTests(unittest.TestCase):
    def _make_rgb_image(self, size=100, color="red"):
        from PIL import Image
        img = Image.new("RGB", (size, size), color=color)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def _make_rgba_image(self, size=100, color=(255, 0, 0, 128)):
        from PIL import Image
        img = Image.new("RGBA", (size, size), color=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _make_png_image(self, size=100):
        from PIL import Image
        img = Image.new("RGB", (size, size), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _make_webp_image(self, size=100):
        from PIL import Image
        img = Image.new("RGB", (size, size), color="green")
        buf = io.BytesIO()
        img.save(buf, format="WEBP")
        return buf.getvalue()

    def test_convert_rgb_to_webp(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.webp"
            res = convert_image(data, out, output_format="webp")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (100, 100))

    def test_convert_rgb_to_jpeg(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpeg"
            res = convert_image(data, out, output_format="jpeg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (100, 100))
                self.assertEqual(img.mode, "RGB")

    def test_convert_jpg_alias_to_jpeg(self):
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpg"
            res = convert_image(data, out, output_format="jpg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())

    def test_convert_rgba_to_jpeg_strips_alpha(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgba_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpeg"
            res = convert_image(data, out, output_format="jpeg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.mode, "RGB")

    def test_convert_rgb_to_png(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.png"
            res = convert_image(data, out, output_format="png")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (100, 100))

    def test_convert_rgba_to_png_preserves_alpha(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgba_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.png"
            res = convert_image(data, out, output_format="png")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.mode, "RGBA")

    def test_convert_png_to_jpeg(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_png_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpeg"
            res = convert_image(data, out, output_format="jpeg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.mode, "RGB")
                self.assertEqual(img.size, (100, 100))

    def test_convert_webp_to_jpeg(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_webp_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpeg"
            res = convert_image(data, out, output_format="jpeg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.mode, "RGB")
                self.assertEqual(img.size, (100, 100))

    def test_convert_webp_to_png(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_webp_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.png"
            res = convert_image(data, out, output_format="png")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (100, 100))

    def test_convert_jpeg_to_png(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.png"
            res = convert_image(data, out, output_format="png")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (100, 100))

    @unittest.skipUnless(HEIC_SUPPORTED, "HEIC/HEIF is not supported in this environment")
    def test_convert_to_heic(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        data = self._make_rgb_image()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "test.heic"
            res = convert_image(data, out_path, output_format="heic")
            self.assertTrue(res.success)
            self.assertTrue(out_path.exists())
            with Image.open(out_path) as img_back:
                self.assertEqual(img_back.size, (100, 100))

    @unittest.skipUnless(HEIC_SUPPORTED, "HEIC/HEIF is not supported in this environment")
    def test_convert_heic_to_jpeg(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        # Create a HEIC image first, then convert to JPEG
        img = Image.new("RGB", (50, 50), color="yellow")
        buf = io.BytesIO()
        img.save(buf, format="HEIF")
        heic_data = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.jpeg"
            res = convert_image(heic_data, out, output_format="jpeg")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())
            with Image.open(out) as img_back:
                self.assertEqual(img_back.mode, "RGB")
                self.assertEqual(img_back.size, (50, 50))

    @unittest.skipUnless(HEIC_SUPPORTED, "HEIC/HEIF is not supported in this environment")
    def test_convert_heic_to_png(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        img = Image.new("RGB", (50, 50), color="cyan")
        buf = io.BytesIO()
        img.save(buf, format="HEIF")
        heic_data = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.png"
            res = convert_image(heic_data, out, output_format="png")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())

    @unittest.skipUnless(HEIC_SUPPORTED, "HEIC/HEIF is not supported in this environment")
    def test_convert_heic_to_webp(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        img = Image.new("RGB", (50, 50), color="magenta")
        buf = io.BytesIO()
        img.save(buf, format="HEIF")
        heic_data = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.webp"
            res = convert_image(heic_data, out, output_format="webp")
            self.assertTrue(res.success, res.message)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
