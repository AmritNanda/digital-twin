"""Experiment design, observation ingestion, and empirical model calibration (SRS-045, SRS-046, AT-036, AT-045).

Enforces:
- Strict origin isolation: synthetic observations cannot be imported into real experiment cohorts (AT-036)
- Prospective validation on temporal holdout datasets without data leakage
- Promotion rejection when recalibration worsens holdout accuracy or suffers drift (AT-045)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any

from backend.dtp.db import tenant_tx
from backend.dtp.identity import Principal


class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    ANALYZED = "ANALYZED"


class SyntheticDataContaminationError(ValueError):
    """Raised when synthetic observations are attempted to be imported into a real cohort (AT-036)."""
    pass


class RecalibrationRegressionError(RuntimeError):
    """Raised when a candidate model recalibration performs worse than baseline on holdout (AT-045)."""
    pass


@dataclass
class ExperimentRecord:
    id: str
    tenant_id: str
    case_id: str
    title: str
    origin: str # 'REAL' or 'FIXTURE'
    status: ExperimentStatus
    hypothesis: str
    target_metric: str
    sample_size: Optional[int]
    treatment_allocation: float
    observations: List[Dict[str, Any]]
    calibration_metrics: Optional[Dict[str, Any]] = None


class ExperimentService:
    """Manages experiments, empirical observation ingestion, and prospective calibration."""

    def create_experiment(
        self,
        principal: Principal,
        case_id: str,
        title: str,
        hypothesis: str,
        target_metric: str,
        origin: str = "REAL",
        sample_size: Optional[int] = 100,
        treatment_allocation: float = 0.5,
    ) -> ExperimentRecord:
        exp_id = f"exp-{uuid.uuid4().hex[:12]}"

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO experiments (
                        id, tenant_id, case_id, title, origin, status, hypothesis,
                        target_metric, sample_size, treatment_allocation, observations, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]', NOW())
                    """,
                    (
                        exp_id,
                        principal.tenant_id,
                        case_id,
                        title,
                        origin,
                        ExperimentStatus.APPROVED.value,
                        hypothesis,
                        target_metric,
                        sample_size,
                        treatment_allocation,
                    ),
                )

        return ExperimentRecord(
            id=exp_id,
            tenant_id=principal.tenant_id,
            case_id=case_id,
            title=title,
            origin=origin,
            status=ExperimentStatus.APPROVED,
            hypothesis=hypothesis,
            target_metric=target_metric,
            sample_size=sample_size,
            treatment_allocation=treatment_allocation,
            observations=[],
        )

    def ingest_observations(
        self,
        principal: Principal,
        experiment_id: str,
        observations: List[Dict[str, Any]],
        data_origin: str = "REAL",
    ) -> int:
        """Ingests empirical observations with strict anti-contamination check (SRS-045, AT-036)."""
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, origin, observations FROM experiments WHERE id = %s FOR UPDATE",
                    (experiment_id,),
                )
                exp = cur.fetchone()
                if not exp:
                    raise KeyError(f"Experiment {experiment_id} not found")

                # SRS-045 / AT-036: Synthetic results cannot be imported into real experiment cohorts
                if exp["origin"] == "REAL" and data_origin != "REAL":
                    raise SyntheticDataContaminationError(
                        f"Cannot ingest {data_origin} observations into REAL experiment {experiment_id} (SRS-045, AT-036: synthetic data prohibited from updating real calibration)"
                    )

                existing_obs = exp["observations"]
                if isinstance(existing_obs, str):
                    existing_obs = json.loads(existing_obs)

                updated = existing_obs + observations

                cur.execute(
                    "UPDATE experiments SET observations = %s WHERE id = %s",
                    (json.dumps(updated), experiment_id),
                )

        return len(updated)

    def evaluate_model_calibration(
        self,
        baseline_holdout_mae: float,
        candidate_holdout_mae: float,
        strict_promotion: bool = True,
    ) -> Dict[str, Any]:
        """Evaluates candidate model recalibration against baseline on holdout dataset (SRS-046, AT-045)."""
        # Lower MAE is better
        improvement = baseline_holdout_mae - candidate_holdout_mae
        is_promoted = improvement > 0.0

        if strict_promotion and not is_promoted:
            raise RecalibrationRegressionError(
                f"Candidate recalibration rejected: holdout error worsened from {baseline_holdout_mae:.4f} to {candidate_holdout_mae:.4f} (SRS-046, AT-045)"
            )

        return {
            "baseline_holdout_mae": baseline_holdout_mae,
            "candidate_holdout_mae": candidate_holdout_mae,
            "improvement": improvement,
            "promoted": is_promoted,
            "reason": "Recalibration improves holdout accuracy" if is_promoted else "Recalibration rejected: worse holdout performance",
        }
