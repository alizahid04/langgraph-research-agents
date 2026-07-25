"""Evidence storage and retrieval tool, backed by the SQL database."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Evidence
from app.schemas import EvidenceItem


def store_evidence(db: Session, run_id: str, task_id: str | None, items: list[EvidenceItem]) -> list[Evidence]:
    """Persist a batch of evidence items for a workflow run."""
    rows: list[Evidence] = []
    for item in items:
        row = Evidence(
            run_id=run_id,
            task_id=task_id,
            source_title=item.source_title,
            source_url=item.source_url,
            snippet=item.snippet,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def retrieve_evidence(db: Session, run_id: str) -> list[Evidence]:
    """Fetch all evidence collected so far for a run."""
    return db.query(Evidence).filter(Evidence.run_id == run_id).order_by(Evidence.created_at).all()
