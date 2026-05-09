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


class UploadValidationTests(unittest.TestCase):
    def test_validate_upload_payload_rejects_bad_extension(self):
        message = validate_upload_payload(
            filename="file.pdf",
            ext=".pdf",
            data=b"not-an-image",
            mimetype="application/pdf",
        )
        self.assertEqual(message, "Unsupported file type. Only JPG/JPEG/PNG are allowed.")

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


if __name__ == "__main__":
    unittest.main()
