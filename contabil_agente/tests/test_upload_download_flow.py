import io
import os
import unittest
from urllib.parse import urlparse

ac = None


class UploadDownloadFlowTests(unittest.TestCase):
    def setUp(self):
        # Skip integration test if Flask isn't installed in the environment
        try:
            import flask  # noqa: F401
            import flask_cors  # noqa: F401
        except Exception:
            self.skipTest("Flask not available in test environment")
        # import agent module lazily to avoid import errors when Flask not present
        global ac
        from contabil_agente import agent_contabil as ac

        self.app = ac.app.test_client()
        # ensure uploads dir exists and is empty for test
        self.upload_dir = ac.Config.UPLOADS_DIR
        os.makedirs(self.upload_dir, exist_ok=True)
        for f in os.listdir(self.upload_dir):
            try:
                os.remove(os.path.join(self.upload_dir, f))
            except Exception:
                pass

    def tearDown(self):
        # clean up uploads created during test
        for f in os.listdir(self.upload_dir):
            try:
                os.remove(os.path.join(self.upload_dir, f))
            except Exception:
                pass

    def test_upload_and_download_local(self):
        # 1) login
        resp = self.app.post(
            "/api/login",
            json={
                "username": os.getenv("ADMIN_USER", "admin"),
                "password": os.getenv("ADMIN_PASS", "changeme"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        token = data["access_token"]

        # 2) upload a small file
        file_content = b"Hello test upload"
        data = {"file": (io.BytesIO(file_content), "report.pdf")}
        upload_resp = self.app.post(
            "/api/upload",
            headers={"Authorization": f"Bearer {token}"},
            data=data,
            content_type="multipart/form-data",
        )
        self.assertEqual(upload_resp.status_code, 200)
        up = upload_resp.get_json()
        self.assertEqual(up["status"], "success")
        up["filename"]
        url = up["url"]

        # 3) download via signed URL
        # client.get expects path only, so extract path+query
        parsed = urlparse(url)
        path = parsed.path
        query = parsed.query
        # Make request to the signed URL
        dl_resp = self.app.get(path + "?" + query)
        self.assertEqual(dl_resp.status_code, 200)
        self.assertEqual(dl_resp.data, file_content)


if __name__ == "__main__":
    unittest.main()
