"""Repository layer for Rentaliq.

Provides storage abstraction for synthetic datasets (equipment, providers,
contractors, bookings, policies) and persists inquiry evaluation records
using SQLite for thread-safe, transactional, idempotent storage.
"""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.schemas.decision import DecisionResponse
from app.schemas.inquiry import InquiryRequest

logger = logging.getLogger(__name__)


class Repository(ABC):
    """Abstract storage interface for Rentaliq data and evaluations."""

    @abstractmethod
    def get_equipment(
        self,
        equipment_id: Optional[str] = None,
        equipment_type: Optional[str] = None,
        capacity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve equipment records matching criteria."""
        pass

    @abstractmethod
    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve provider profile and business terms."""
        pass

    @abstractmethod
    def get_contractor(self, contractor_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve contractor verification and safety record."""
        pass

    @abstractmethod
    def get_bookings(self, equipment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve confirmed bookings and schedule commitments."""
        pass

    @abstractmethod
    def get_policy(self, provider_id: str = "PROV-001") -> Dict[str, Any]:
        """Retrieve authoritative operational policies."""
        pass

    @abstractmethod
    def get_sample_inquiries(self) -> List[Dict[str, Any]]:
        """Retrieve curated demonstration scenarios."""
        pass

    @abstractmethod
    def save_inquiry_evaluation(
        self,
        response: DecisionResponse,
        request: InquiryRequest,
    ) -> None:
        """Persist or idempotently update an inquiry evaluation audit record."""
        pass

    @abstractmethod
    def get_inquiry_evaluation(self, inquiry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a saved inquiry evaluation by ID."""
        pass

    @abstractmethod
    def list_inquiry_evaluations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List historical inquiry evaluations."""
        pass


class SQLiteRepository(Repository):
    """Thread-safe SQLite repository backed by synthetic JSON master files."""

    def __init__(self, db_path: Optional[Path | str] = None, data_dir: Optional[Path | str] = None):
        self.db_path = str(db_path or settings.sqlite_db_path)
        self.data_dir = Path(data_dir or settings.data_dir)

        # Cache baseline synthetic datasets in memory for fast lookup
        self._equipment: List[Dict[str, Any]] = []
        self._providers: List[Dict[str, Any]] = []
        self._contractors: List[Dict[str, Any]] = []
        self._bookings: List[Dict[str, Any]] = []
        self._policies: Dict[str, Any] = {}
        self._sample_inquiries: List[Dict[str, Any]] = []

        self._load_synthetic_files()
        self._init_sqlite_db()

    def _load_synthetic_files(self) -> None:
        """Load JSON master data files from disk."""
        try:
            eq_path = self.data_dir / "equipment.json"
            if eq_path.exists():
                with open(eq_path, "r", encoding="utf-8") as f:
                    self._equipment = json.load(f)

            prov_path = self.data_dir / "providers.json"
            if prov_path.exists():
                with open(prov_path, "r", encoding="utf-8") as f:
                    self._providers = json.load(f)

            con_path = self.data_dir / "contractors.json"
            if con_path.exists():
                with open(con_path, "r", encoding="utf-8") as f:
                    self._contractors = json.load(f)

            bk_path = self.data_dir / "bookings.json"
            if bk_path.exists():
                with open(bk_path, "r", encoding="utf-8") as f:
                    self._bookings = json.load(f)

            pol_path = self.data_dir / "policies.json"
            if pol_path.exists():
                with open(pol_path, "r", encoding="utf-8") as f:
                    self._policies = json.load(f)

            samples_path = self.data_dir / "sample_inquiries.json"
            if samples_path.exists():
                with open(samples_path, "r", encoding="utf-8") as f:
                    self._sample_inquiries = json.load(f)

            logger.info("Loaded synthetic master records successfully from %s", self.data_dir)
        except Exception as e:
            logger.error("Failed to load synthetic files from %s: %s", self.data_dir, e)
            raise

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection to the SQLite database."""
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite_db(self) -> None:
        """Ensure the evaluations table is initialized."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS inquiry_evaluations (
                    inquiry_id TEXT PRIMARY KEY,
                    contractor_id TEXT,
                    provider_id TEXT,
                    decision TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    qualification_score REAL NOT NULL,
                    confidence_score REAL NOT NULL,
                    execution_mode TEXT NOT NULL,
                    requires_human_approval INTEGER NOT NULL,
                    has_counter_offer INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_inq_created_at ON inquiry_evaluations (created_at DESC);"
            )
            conn.commit()

    def get_equipment(
        self,
        equipment_id: Optional[str] = None,
        equipment_type: Optional[str] = None,
        capacity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve equipment records matching criteria."""
        results = []
        for eq in self._equipment:
            if equipment_id and eq.get("equipment_id") != equipment_id:
                continue
            if equipment_type:
                q_type = equipment_type.lower()
                eq_type = eq.get("equipment_type", "").lower()
                # Support matching mini excavator vs excavator or substring
                if q_type not in eq_type and eq_type not in q_type:
                    continue
            if capacity:
                q_cap = capacity.lower().replace(" ", "").replace("-", "")
                eq_cap = eq.get("capacity", "").lower().replace(" ", "").replace("-", "")
                if q_cap not in eq_cap and eq_cap not in q_cap:
                    continue
            results.append(eq)
        return results

    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve provider profile and business terms."""
        for p in self._providers:
            if p.get("provider_id") == provider_id:
                return p
        return self._providers[0] if self._providers else None

    def get_contractor(self, contractor_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve contractor verification and safety record."""
        for c in self._contractors:
            if c.get("contractor_id") == contractor_id:
                return c
        return None

    def get_bookings(self, equipment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve confirmed bookings and schedule commitments."""
        if equipment_id:
            return [b for b in self._bookings if b.get("equipment_id") == equipment_id]
        return list(self._bookings)

    def get_policy(self, provider_id: str = "PROV-001") -> Dict[str, Any]:
        """Retrieve authoritative operational policies."""
        return self._policies or {
            "provider_id": provider_id,
            "mandatory_fields": ["equipment_type", "start_date", "duration_days"],
            "rental_durations": {"default_min_days": 1},
        }

    def get_sample_inquiries(self) -> List[Dict[str, Any]]:
        """Retrieve curated demonstration scenarios."""
        return list(self._sample_inquiries)

    def save_inquiry_evaluation(
        self,
        response: DecisionResponse,
        request: InquiryRequest,
    ) -> None:
        """Persist or idempotently update an inquiry evaluation audit record.

        Repeated submissions with the same inquiry_id update in-place without duplicates.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        full_payload = {
            "inquiry_id": response.inquiry_id,
            "request": request.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
        }
        payload_str = json.dumps(full_payload, default=str)

        has_counter = 1 if response.counter_offer is not None else 0
        req_approval = 1 if response.requires_human_approval else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO inquiry_evaluations (
                    inquiry_id,
                    contractor_id,
                    provider_id,
                    decision,
                    decision_reason,
                    qualification_score,
                    confidence_score,
                    execution_mode,
                    requires_human_approval,
                    has_counter_offer,
                    payload_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(inquiry_id) DO UPDATE SET
                    contractor_id = excluded.contractor_id,
                    provider_id = excluded.provider_id,
                    decision = excluded.decision,
                    decision_reason = excluded.decision_reason,
                    qualification_score = excluded.qualification_score,
                    confidence_score = excluded.confidence_score,
                    execution_mode = excluded.execution_mode,
                    requires_human_approval = excluded.requires_human_approval,
                    has_counter_offer = excluded.has_counter_offer,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at;
                """,
                (
                    response.inquiry_id,
                    request.contractor_id,
                    request.provider_id,
                    response.decision.value,
                    response.decision_reason,
                    response.qualification_score,
                    response.confidence_score,
                    response.execution_mode.value,
                    req_approval,
                    has_counter,
                    payload_str,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
            logger.info("Persisted inquiry evaluation for %s [decision=%s]", response.inquiry_id, response.decision.value)

    def get_inquiry_evaluation(self, inquiry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a saved inquiry evaluation by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json FROM inquiry_evaluations WHERE inquiry_id = ? LIMIT 1;",
                (inquiry_id,),
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row["payload_json"])
        return None

    def list_inquiry_evaluations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List historical inquiry evaluations."""
        results = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT inquiry_id, contractor_id, provider_id, decision,
                       qualification_score, confidence_score, execution_mode,
                       requires_human_approval, has_counter_offer, created_at, updated_at
                FROM inquiry_evaluations
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            for r in rows:
                results.append(dict(r))
        return results


# Default repository instance
default_repository = SQLiteRepository()
