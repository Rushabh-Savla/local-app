import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from annotator_agent.api_client import AnnotationServerClient
from annotator_agent.local_cache import LocalAgentCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("annotator_agent")


class AnnotatorAgent:
    """Desktop agent running on annotator workstation."""

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        local_root: str = "~/nas_annotation_workspace",
        batch_size: Optional[int] = None,
        xanylabeling_bin: str = "xanylabeling",
    ):
        self.server_url = server_url
        self.root = Path(local_root).expanduser().resolve()
        self.batch_size = batch_size
        self.xanylabeling_bin = xanylabeling_bin

        # Paths
        self.state_dir = self.root / "state"
        self.batches_dir = self.root / "batches"
        self.backups_dir = self.root / "backups"
        self.current_dir = self.root / "current"
        self.token_file = self.state_dir / "agent_token.json"

        self._ensure_paths()
        self.cache = LocalAgentCache(self.state_dir / "agent_cache.db")
        self.client = AnnotationServerClient(base_url=self.server_url)
        self._load_token()

    def _ensure_paths(self):
        for p in (self.state_dir, self.batches_dir, self.backups_dir):
            p.mkdir(parents=True, exist_ok=True)
        if not self.current_dir.exists() and not self.current_dir.is_symlink():
            self.current_dir.mkdir(parents=True, exist_ok=True)

    def _load_token(self):
        self.saved_username = None
        if self.token_file.exists():
            try:
                data = json.loads(self.token_file.read_text(encoding="utf-8"))
                self.client.token = data.get("access_token")
                self.saved_username = data.get("username")
            except Exception:
                pass

    def _save_token(self, token: str, username: str):
        self.saved_username = username
        data = {"access_token": token, "username": username, "updated_at": int(time.time())}
        self.token_file.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def login(self, username: str, password: str):
        """Authenticate with central server."""
        token = self.client.login(username, password)
        self.saved_username = username
        self._save_token(token, username)
        logger.info(f"Successfully authenticated as '{username}' to {self.server_url}.")

    def get_active_assignment(self) -> Optional[Dict[str, Any]]:
        """Find active assignment in READY, IN_PROGRESS, or PREPARING status."""
        assignments = self.client.get_my_assignments()
        for a in assignments:
            if a["status"] in {"READY", "IN_PROGRESS", "PREPARING"}:
                return a
        return None

    def get_nas_status(self) -> Dict[str, Any]:
        """Check real-time NAS connectivity via central server."""
        return self.client.get_nas_status()

    def fetch_batch(
        self,
        assignment_id: int,
        limit: Optional[int] = None,
        progress_callback: Optional[Any] = None,
    ) -> int:
        """Download assigned images from server to local workstation."""
        manifest = self.client.get_assignment_manifest(assignment_id)
        self.cache.save_manifest(manifest)

        # Physical disk check: if any file from manifest is missing locally, ensure it is PENDING
        manifest_items = manifest.get("items", [])
        missing_on_disk_ids = [
            it["file_id"]
            for it in manifest_items
            if not (self.current_dir / it["relative_path"]).exists()
        ]
        if missing_on_disk_ids:
            with self.cache._get_connection() as conn:
                conn.executemany(
                    "UPDATE local_items SET local_state='PENDING' WHERE assignment_id=? AND file_id=? AND local_state != 'SUBMITTED'",
                    [(assignment_id, fid) for fid in missing_on_disk_ids],
                )
                conn.commit()

        effective_limit = limit if limit is not None else (self.batch_size or 2000)

        # 1. High-speed Single-Batch Archive Download (Downloads batch in 1 single stream)
        try:
            import zipfile
            bundle_zip = self.batches_dir / f"assignment_{assignment_id}_bundle.zip"
            logger.info(f"Downloading batch of images (limit: {effective_limit}) in 1 single bundle stream...")

            def on_stream_progress(downloaded_b, total_b):
                if progress_callback and total_b > 0:
                    pct = int(downloaded_b / total_b * 100)
                    progress_callback(pct, 100)

            self.client.download_assignment_bundle(assignment_id, bundle_zip, limit=effective_limit, progress_callback=on_stream_progress)

            # Extract all images at once into local current_dir
            self.current_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(bundle_zip, "r") as zf:
                zf.extractall(self.current_dir)

            found_count = 0
            with self.cache._get_connection() as conn:
                for it in manifest_items:
                    target_file = self.current_dir / it["relative_path"]
                    if not target_file.exists():
                        flat_candidate = self.current_dir / Path(it["relative_path"]).name
                        if flat_candidate.exists():
                            target_file = flat_candidate
                    if target_file.exists():
                        found_count += 1
                        fhash = hashlib.sha256(target_file.read_bytes()).hexdigest()
                        conn.execute(
                            "UPDATE local_items SET local_state='DOWNLOADED', local_hash=? WHERE assignment_id=? AND file_id=?",
                            (fhash, assignment_id, it["file_id"]),
                        )
                conn.commit()

            bundle_zip.unlink(missing_ok=True)

            if found_count > 0:
                if progress_callback:
                    progress_callback(found_count, found_count)
                logger.info(f"Single batch download complete: {found_count} images saved to {self.current_dir}.")
                return found_count
            else:
                logger.warning(f"Bundle contained {found_count} images; falling back to individual download.")

        except Exception as exc:
            logger.warning(f"Single-batch bundle transfer fell back to parallel fetch: {exc}")

        # 2. Fallback: item-by-item download
        pending_items = self.cache.get_pending_download_items(assignment_id, limit=effective_limit)
        if not pending_items:
            logger.info("No pending items to download for active assignment.")
            return 0

        total_pending = len(pending_items)
        logger.info(f"Downloading batch of {total_pending} images...")

        downloaded = 0
        for item in pending_items:
            file_id = item["file_id"]
            rel_path = item["relative_path"]
            target_path = self.current_dir / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            img_bytes = self.client.download_image(assignment_id, file_id)
            target_path.write_bytes(img_bytes)

            file_hash = hashlib.sha256(img_bytes).hexdigest()
            self.cache.mark_downloaded(assignment_id, file_id, file_hash)
            downloaded += 1
            if progress_callback:
                try:
                    progress_callback(downloaded, total_pending)
                except Exception:
                    pass

        logger.info(f"Batch download complete: {downloaded} images saved to {self.current_dir}.")
        return downloaded

    def find_xanylabeling(self) -> Optional[str]:
        """Locate the XAnyLabeling binary across known locations and virtual environments."""
        exe = shutil.which(self.xanylabeling_bin)
        if exe:
            return exe

        candidates = [
            Path.home() / "xanylabeling-venv-new" / "bin" / "xanylabeling",
            Path("/home/easemyai/xanylabeling-venv-new/bin/xanylabeling"),
            Path.home() / ".local" / "bin" / "xanylabeling",
            Path.home() / "miniconda3" / "bin" / "xanylabeling",
            Path.home() / "anaconda3" / "bin" / "xanylabeling",
            Path("/usr/local/bin/xanylabeling"),
            Path("/usr/bin/xanylabeling"),
        ]
        for c in candidates:
            if c.is_file() and os.access(c, os.X_OK):
                return str(c)

        try:
            res = subprocess.run(
                ["bash", "-lc", "source ~/xanylabeling-venv-new/bin/activate 2>/dev/null && which xanylabeling"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            out = res.stdout.strip()
            if res.returncode == 0 and out and os.path.isfile(out):
                return out
        except Exception:
            pass

        return None

    def launch_xanylabeling(self) -> Optional[subprocess.Popen]:
        """Launch XAnyLabeling directly on local batch directory with auto-loading and safety flags."""
        self.current_dir.mkdir(parents=True, exist_ok=True)
        exe = self.find_xanylabeling()

        env = os.environ.copy()
        env["QT_OPENGL"] = "software"
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":1"
        venv_bin = str(Path.home() / "xanylabeling-venv-new" / "bin")
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

        if exe:
            cmd = [
                exe,
                "--filename", str(self.current_dir),
                "--output", str(self.current_dir),
                "--qt-platform", "xcb",
            ]
            logger.info(f"Launching XAnyLabeling directly: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, cwd=str(self.current_dir), env=env)
        else:
            cmd = [
                "bash", "-lc",
                f"source ~/xanylabeling-venv-new/bin/activate 2>/dev/null; "
                f"cd '{self.current_dir}' && "
                f"QT_OPENGL=software xanylabeling --filename '{self.current_dir}' --output '{self.current_dir}' --qt-platform xcb"
            ]
            logger.info(f"Launching XAnyLabeling via login shell: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, cwd=str(self.current_dir), env=env)

        pid_file = self.state_dir / "app.pid"
        try:
            pid_file.write_text(str(proc.pid))
        except Exception:
            pass
        return proc

    def sync_annotations(
        self,
        assignment_id: int,
        ownership_generation: int,
        declare_remaining_as_background: bool = False,
        background_reason: str = "Intentional background/negative image without target objects",
    ) -> Dict[str, Any]:
        """
        Scan local directory for completed annotation JSON files, validate syntax,
        create local backups, submit to central server, and optionally declare
        remaining unannotated batch images as background/negative images.
        """
        manifest = self.client.get_assignment_manifest(assignment_id)
        items_by_path = {item["relative_path"]: item for item in manifest.get("items", [])}

        items_by_stem = {}
        for img_rel_path, item_data in items_by_path.items():
            stem_key = Path(img_rel_path).stem.lower()
            items_by_stem[stem_key] = (img_rel_path, item_data)

        local_json_files = [f for f in self.current_dir.rglob("*.json") if f.is_file()]

        submitted = 0
        errors = 0
        submitted_file_ids = set()

        batch_items = []
        for local_json in local_json_files:
            stem_key = local_json.stem.lower()
            if stem_key not in items_by_stem:
                continue

            img_rel_path, item_data = items_by_stem[stem_key]
            json_rel_path = Path(img_rel_path).with_suffix(".json").as_posix()

            try:
                content_text = local_json.read_text(encoding="utf-8")
                annotation_data = json.loads(content_text)
            except Exception as exc:
                logger.error(f"Failed to read/parse {local_json}: {exc}")
                errors += 1
                continue

            content_bytes = content_text.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Create local backup
            backup_dst = self.backups_dir / json_rel_path
            backup_dst.parent.mkdir(parents=True, exist_ok=True)
            backup_dst.write_bytes(content_bytes)

            # Idempotency key per file submission
            idemp_key = f"sub_{assignment_id}_{item_data['file_id']}_{content_hash[:16]}"
            batch_items.append({
                "file_id": item_data["file_id"],
                "idempotency_key": idemp_key,
                "content_hash": content_hash,
                "annotation_json": annotation_data,
            })

        if batch_items:
            try:
                resp = self.client.submit_annotations_bulk(
                    assignment_id=assignment_id,
                    ownership_generation=ownership_generation,
                    items=batch_items,
                )
                submitted = resp.get("submitted_count", len(batch_items))
                for itm in batch_items:
                    self.cache.mark_submitted(assignment_id, itm["file_id"])
                    submitted_file_ids.add(itm["file_id"])
                logger.info(f"Successfully submitted batch of {submitted} annotations in 1 single HTTP request.")
            except Exception as exc:
                logger.warning(f"Bulk submission fell back to individual submit: {exc}")
                for itm in batch_items:
                    try:
                        self.client.submit_annotation(
                            assignment_id=assignment_id,
                            file_id=itm["file_id"],
                            ownership_generation=ownership_generation,
                            idempotency_key=itm["idempotency_key"],
                            content_hash=itm["content_hash"],
                            annotation_json=itm["annotation_json"],
                        )
                        self.cache.mark_submitted(assignment_id, itm["file_id"])
                        submitted += 1
                        submitted_file_ids.add(itm["file_id"])
                    except Exception as sub_exc:
                        logger.error(f"Fallback submit failed for file {itm['file_id']}: {sub_exc}")
                        errors += 1

        # Optionally declare remaining local batch images as background
        background_count = 0
        if declare_remaining_as_background:
            img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
            local_img_files = [f for f in self.current_dir.rglob("*") if f.is_file() and f.suffix.lower() in img_exts]
            unannotated_file_ids = []
            for img_f in local_img_files:
                stem = img_f.stem.lower()
                if stem in items_by_stem:
                    _, itm_data = items_by_stem[stem]
                    fid = itm_data["file_id"]
                    if fid not in submitted_file_ids:
                        unannotated_file_ids.append(fid)

            if unannotated_file_ids:
                try:
                    logger.info(f"Declaring {len(unannotated_file_ids)} unannotated images as background...")
                    self.client.declare_bulk_background(
                        assignment_id=assignment_id,
                        file_ids=unannotated_file_ids,
                        reason=background_reason,
                    )
                    with self.cache._get_connection() as conn:
                        conn.executemany(
                            "UPDATE local_items SET local_state='SUBMITTED' WHERE assignment_id=? AND file_id=?",
                            [(assignment_id, fid) for fid in unannotated_file_ids],
                        )
                        conn.commit()
                    background_count = len(unannotated_file_ids)
                except Exception as exc:
                    logger.error(f"Failed to declare background images: {exc}")
                    errors += 1

        logger.info(f"Sync complete: {submitted} submitted, {background_count} background declared, {errors} errors.")
        return {
            "submitted": submitted,
            "background": background_count,
            "errors": errors,
            "batch_completed": declare_remaining_as_background or (submitted > 0 and errors == 0 and len(local_json_files) >= len(items_by_stem)),
        }

    def status(self) -> Dict[str, Any]:
        """Check status of agent, active assignment, and local workspace."""
        active = None
        summary = {}
        if self.client.token:
            try:
                active = self.get_active_assignment()
                if active:
                    summary = self.cache.get_assignment_status_summary(active["id"])
            except Exception as exc:
                logger.warning(f"Could not retrieve active assignment: {exc}")

        return {
            "server_url": self.server_url,
            "authenticated": bool(self.client.token),
            "active_assignment": active,
            "local_workspace": str(self.current_dir),
            "batch_summary": summary,
        }


    def clean_workspace(self, assignment_id: Optional[int] = None, clear_cache: bool = True) -> int:
        """Clean the local current workspace directory and optionally clear cached download database records."""
        count = 0
        if self.current_dir.exists():
            for item in self.current_dir.iterdir():
                if item.is_file():
                    item.unlink()
                    count += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    count += 1
        # Clear database records of downloaded items if requested
        if clear_cache:
            self.cache.clear_local_cache(assignment_id=assignment_id)
            logger.info(f"Cleaned {count} items from local workspace ({self.current_dir}) and reset local cache database.")
        else:
            logger.info(f"Cleaned {count} items from local workspace ({self.current_dir}).")
        return count


def main():
    parser = argparse.ArgumentParser(description="Central Annotator Desktop Agent")
    parser.add_argument("--server-url", default=os.getenv("SERVER_URL", "http://localhost:8080"))
    parser.add_argument("--local-root", default=os.getenv("ROOT", "~/nas_annotation_workspace"))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--xanylabeling", default="xanylabeling")

    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login")
    p_login.add_argument("--username", required=True)
    p_login.add_argument("--password", required=True)

    sub.add_parser("status")
    sub.add_parser("fetch")
    sub.add_parser("sync")
    sub.add_parser("launch")
    sub.add_parser("clean")

    args = parser.parse_args()
    agent = AnnotatorAgent(
        server_url=args.server_url,
        local_root=args.local_root,
        batch_size=args.batch_size,
        xanylabeling_bin=args.xanylabeling,
    )

    if args.command == "login":
        agent.login(args.username, args.password)
    elif args.command == "status":
        st = agent.status()
        print(json.dumps(st, indent=2))
    elif args.command == "fetch":
        active = agent.get_active_assignment()
        if not active:
            print("No active assignment found for current user.")
            sys.exit(1)
        count = agent.fetch_batch(active["id"])
        print(f"Downloaded {count} images.")
    elif args.command == "sync":
        active = agent.get_active_assignment()
        if not active:
            print("No active assignment found for current user.")
            sys.exit(1)
        res = agent.sync_annotations(active["id"], active["lease_generation"])
        print(json.dumps(res, indent=2))
    elif args.command == "launch":
        agent.launch_xanylabeling()
    elif args.command == "clean":
        count = agent.clean_workspace()
        print(f"Cleaned {count} items from local workspace.")


if __name__ == "__main__":
    main()

