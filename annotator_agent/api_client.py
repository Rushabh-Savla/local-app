import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import httpx

logger = logging.getLogger(__name__)


class AnnotationServerClient:
    """HTTP client communicating with Central Annotation Platform REST API."""

    def __init__(self, base_url: str = "http://localhost:8000", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=30.0)

    @property
    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, username: str, password: str) -> str:
        """Authenticate with username and password, returns access token."""
        url = f"{self.base_url}/api/v1/auth/login"
        resp = self._client.post(url, json={"username": username, "password": password})
        if resp.status_code != 200:
            raise RuntimeError(f"Login failed: {resp.text}")
        data = resp.json()
        self.token = data["access_token"]
        return self.token

    def get_my_assignments(self) -> List[Dict[str, Any]]:
        """Fetch assignments assigned to currently authenticated user."""
        url = f"{self.base_url}/api/v1/assignments"
        resp = self._client.get(url, headers=self.headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch assignments: {resp.text}")
        return resp.json()

    def get_datasets(self) -> List[Dict[str, Any]]:
        """Fetch registered datasets to show friendly project titles and names."""
        url = f"{self.base_url}/api/v1/datasets"
        try:
            resp = self._client.get(url, headers=self.headers)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def get_nas_status(self) -> Dict[str, Any]:
        """Fetch real-time NAS connectivity status from central server."""
        url = f"{self.base_url}/api/v1/nas/status"
        try:
            resp = self._client.get(url, headers=self.headers, timeout=6.0)
            if resp.status_code == 200:
                return resp.json()
            return {"connected": False, "error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    def get_assignment_manifest(self, assignment_id: int) -> Dict[str, Any]:
        """Fetch manifest of items for an assignment."""
        url = f"{self.base_url}/api/v1/assignments/{assignment_id}/manifest"
        resp = self._client.get(url, headers=self.headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch manifest: {resp.text}")
        return resp.json()

    def download_image(self, assignment_id: int, file_id: int) -> bytes:
        """Download raw image bytes for an assigned image with checksum verification."""
        url = f"{self.base_url}/api/v1/assignments/{assignment_id}/images/{file_id}"
        resp = self._client.get(url, headers=self.headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download image {file_id}: {resp.text}")

        expected_hash = resp.headers.get("X-File-Hash")
        content = resp.content
        if expected_hash:
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"Hash mismatch for image {file_id}: expected {expected_hash}, got {actual_hash}")

        return content

    def download_assignment_bundle(
        self,
        assignment_id: int,
        dest_path: Path,
        limit: Optional[int] = None,
        progress_callback: Optional[Any] = None,
    ) -> Path:
        """Download assignment image batch as a single ZIP archive in 1 HTTP stream."""
        url = f"{self.base_url}/api/v1/assignments/{assignment_id}/bundle"
        if limit is not None and limit > 0:
            url += f"?limit={limit}"
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._client.stream("GET", url, headers=self.headers, timeout=300.0) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to download assignment bundle: HTTP {resp.status_code}")
            total_bytes = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 512):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_bytes > 0:
                        try:
                            progress_callback(downloaded, total_bytes)
                        except Exception:
                            pass
        return dest_path

    def submit_annotation(
        self,
        assignment_id: int,
        file_id: int,
        ownership_generation: int,
        idempotency_key: str,
        content_hash: str,
        annotation_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Submit completed annotation JSON to server."""
        url = f"{self.base_url}/api/v1/submissions"
        payload = {
            "assignment_id": assignment_id,
            "file_id": file_id,
            "ownership_generation": ownership_generation,
            "idempotency_key": idempotency_key,
            "content_hash": content_hash,
            "annotation_json": annotation_json,
        }
        resp = self._client.post(url, headers=self.headers, json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Submission failed for file {file_id}: {resp.text}")
        return resp.json()

    def declare_bulk_background(
        self,
        assignment_id: int,
        file_ids: List[int],
        reason: str = "Intentional negative/background image without annotations",
    ) -> Dict[str, Any]:
        """Declare multiple assigned images as intentional background images in one atomic request."""
        url = f"{self.base_url}/api/v1/submissions/background/bulk"
        payload = {
            "assignment_id": assignment_id,
            "file_ids": file_ids,
            "reason": reason,
        }
        resp = self._client.post(url, headers=self.headers, json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Bulk background declaration failed: {resp.text}")
        return resp.json()

    def declare_background(
        self,
        assignment_id: int,
        file_id: int,
        reason: str = "Intentional negative/background image without annotations",
    ) -> Dict[str, Any]:
        """Declare that an assigned image is an intentional unannotated/background image."""
        url = f"{self.base_url}/api/v1/submissions/background"
        payload = {
            "assignment_id": assignment_id,
            "file_id": file_id,
            "reason": reason,
        }
        resp = self._client.post(url, headers=self.headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Background declaration failed: {resp.text}")
        return resp.json()

    def send_heartbeat(
        self,
        device_identifier: str,
        active_assignment_id: Optional[int] = None,
        progress: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send heartbeat to maintain assignment lease."""
        url = f"{self.base_url}/api/v1/heartbeat"
        payload = {
            "device_identifier": device_identifier,
            "active_assignment_id": active_assignment_id,
            "active_batch_progress": progress,
        }
        resp = self._client.post(url, headers=self.headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Heartbeat failed: {resp.text}")
        return resp.json()

    def submit_completion(self, assignment_id: int) -> Dict[str, Any]:
        """Notify central server that annotator has submitted assignment for completion approval."""
        url = f"{self.base_url}/api/v1/assignments/{assignment_id}/submit-completion"
        resp = self._client.post(url, headers=self.headers)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Submit completion failed: {resp.text}")
        return resp.json()


