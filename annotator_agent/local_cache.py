import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Any


class LocalAgentCache:
    """
    Local SQLite cache for offline resiliency, tracking downloaded images,
    local backups, and retry queues.
    IMPORTANT: This cache is strictly a local client cache and NEVER acts
    as a global authority.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_manifests (
                    assignment_id INTEGER PRIMARY KEY,
                    catalog_version TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    total_count INTEGER NOT NULL,
                    cached_at INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS local_items (
                    assignment_id INTEGER NOT NULL,
                    file_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    local_state TEXT NOT NULL DEFAULT 'PENDING',
                    local_hash TEXT,
                    submitted_at INTEGER,
                    PRIMARY KEY(assignment_id, file_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    file_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            conn.commit()

    def save_manifest(self, manifest: Dict[str, Any]):
        now = int(time.time())
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cached_manifests(assignment_id, catalog_version, lease_generation, total_count, cached_at) VALUES(?,?,?,?,?)",
                (manifest["assignment_id"], manifest["catalog_version"], manifest["lease_generation"], manifest["total_count"], now),
            )
            for item in manifest.get("items", []):
                conn.execute(
                    "INSERT OR REPLACE INTO local_items(assignment_id, file_id, ordinal, relative_path, size, local_state) VALUES(?,?,?,?,?,COALESCE((SELECT local_state FROM local_items WHERE assignment_id=? AND file_id=?),'PENDING'))",
                    (manifest["assignment_id"], item["file_id"], item["ordinal"], item["relative_path"], item["size"], manifest["assignment_id"], item["file_id"]),
                )
            conn.commit()

    def mark_downloaded(self, assignment_id: int, file_id: int, local_hash: str):
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE local_items SET local_state='DOWNLOADED', local_hash=? WHERE assignment_id=? AND file_id=?",
                (local_hash, assignment_id, file_id),
            )
            conn.commit()

    def mark_annotated(self, assignment_id: int, file_id: int):
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE local_items SET local_state='ANNOTATED' WHERE assignment_id=? AND file_id=?",
                (assignment_id, file_id),
            )
            conn.commit()

    def mark_submitted(self, assignment_id: int, file_id: int):
        now = int(time.time())
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE local_items SET local_state='SUBMITTED', submitted_at=? WHERE assignment_id=? AND file_id=?",
                (now, assignment_id, file_id),
            )
            conn.commit()

    def get_pending_download_items(self, assignment_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if limit is not None and limit > 0:
                cursor = conn.execute(
                    "SELECT file_id, ordinal, relative_path, size FROM local_items WHERE assignment_id=? AND local_state='PENDING' ORDER BY ordinal ASC LIMIT ?",
                    (assignment_id, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT file_id, ordinal, relative_path, size FROM local_items WHERE assignment_id=? AND local_state='PENDING' ORDER BY ordinal ASC",
                    (assignment_id,),
                )
            return [
                {"file_id": r[0], "ordinal": r[1], "relative_path": r[2], "size": r[3]}
                for r in cursor.fetchall()
            ]

    def get_assignment_status_summary(self, assignment_id: int) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT local_state, COUNT(*) FROM local_items WHERE assignment_id=? GROUP BY local_state",
                (assignment_id,),
            )
            return {r[0]: r[1] for r in cursor.fetchall()}

    def clear_local_cache(self, assignment_id: Optional[int] = None) -> None:
        """Clear local database records of downloaded/cached images so user can re-download from scratch."""
        with self._get_connection() as conn:
            if assignment_id is not None:
                conn.execute("DELETE FROM local_items WHERE assignment_id=?", (assignment_id,))
                conn.execute("DELETE FROM cached_manifests WHERE assignment_id=?", (assignment_id,))
                conn.execute("DELETE FROM sync_queue WHERE assignment_id=?", (assignment_id,))
            else:
                conn.execute("DELETE FROM local_items")
                conn.execute("DELETE FROM cached_manifests")
                conn.execute("DELETE FROM sync_queue")
            conn.commit()

