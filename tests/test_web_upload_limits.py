import io
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from imgtowebp.web.app import create_app, validate_upload_payload  # noqa: E402
from imgtowebp.core import HEIC_SUPPORTED


class UploadValidationTests(unittest.TestCase):
    def test_validate_upload_payload_rejects_bad_extension(self):
        message = validate_upload_payload(
            filename="file.pdf",
            ext=".pdf",
            data=b"not-an-image",
            mimetype="application/pdf",
        )
        self.assertEqual(message, "Unsupported file type. Only JPG/JPEG/PNG/WEBP are allowed.")

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
    @unittest.skipUnless(HEIC_SUPPORTED, "HEIC/HEIF is not supported in this environment")
    def test_convert_to_heic(self):
        from PIL import Image
        from imgtowebp.core import convert_image
        
        img = Image.new("RGB", (100, 100), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        data = img_bytes.getvalue()
        
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "test.heic"
            res = convert_image(data, out_path, output_format="heic")
            self.assertTrue(res.success)
            self.assertTrue(out_path.exists())
            
            # Verify it's a valid HEIF/HEIC file
            with Image.open(out_path) as img_back:
                self.assertEqual(img_back.size, (100, 100))


if __name__ == "__main__":
    unittest.main()
