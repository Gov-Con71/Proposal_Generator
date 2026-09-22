"""Persistence for drafting trajectories — a replayable per-attempt record of
what happened during one proposal-drafting run.

Owns all reads/writes against `drafting_trajectories`. Kept dependency-free of
FastAPI so both the API layer and the drafting agent (running inside Celery)
can call it. See `app.agent.drafting_agent` for the writer and
`app.api.v1.workspace` for the reader.
"""

import logging
from typing import Optional
from uuid import UUID, uuid4

from psycopg2.extras import Json

from app.core.db import get_connection

logger = logging.getLogger(__name__)


def record_section_trajectory(
    run_id: str,
    proposal_id: UUID,
    section_id: Optional[UUID],
    section_title: str,
    outline_index: int,
    attempts: list[dict],
    stalled: bool,
    final_status: str,
) -> UUID:
    """Inserts one section's full attempt history for a drafting run.

    Called once per section per run, from `_save_section_node` (and from the
    isolated-failure path in `run_drafting` for a section that never reaches
    it) — never per attempt, since `attempts` already carries the whole
    ordered history in one JSONB array.
    """
    trajectory_id = uuid4()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drafting_trajectories
                    (trajectory_id, run_id, proposal_id, section_id, section_title,
                     outline_index, attempts, final_status, stalled, attempt_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, outline_index) DO UPDATE SET
                    attempts=EXCLUDED.attempts, final_status=EXCLUDED.final_status,
                    stalled=EXCLUDED.stalled, attempt_count=EXCLUDED.attempt_count,
                    updated_at=now();
                """,
                (
                    str(trajectory_id),
                    run_id,
                    str(proposal_id),
                    str(section_id) if section_id else None,
                    section_title,
                    outline_index,
                    Json(attempts),
                    final_status,
                    stalled,
                    len(attempts),
                ),
            )
    finally:
        conn.close()
    logger.info(
        "Recorded drafting_trajectory %s for run=%s proposal=%s section='%s' "
        "(%d attempt(s), status=%s)",
        trajectory_id,
        run_id,
        proposal_id,
        section_title,
        len(attempts),
        final_status,
    )
    return trajectory_id


def get_trajectory(proposal_id: UUID, run_id: Optional[UUID] = None) -> Optional[dict]:
    """Returns one run's trajectory (every section, ordered by outline position).

    `run_id` omitted resolves to the most recent run for the proposal. Returns
    None when the proposal has no recorded drafting run at all.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            resolved_run_id = str(run_id) if run_id else None
            if resolved_run_id is None:
                cur.execute(
                    "SELECT run_id FROM drafting_trajectories WHERE proposal_id = %s "
                    "ORDER BY created_at DESC LIMIT 1;",
                    (str(proposal_id),),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                resolved_run_id = str(row[0])

            cur.execute(
                """
                SELECT section_id, section_title, outline_index, final_status,
                       stalled, attempt_count, attempts
                FROM drafting_trajectories
                WHERE proposal_id = %s AND run_id = %s
                ORDER BY outline_index;
                """,
                (str(proposal_id), resolved_run_id),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return {
        "run_id": resolved_run_id,
        "proposal_id": str(proposal_id),
        "sections": [
            {
                "section_id": str(r[0]) if r[0] else None,
                "section_title": r[1],
                "outline_index": r[2],
                "final_status": r[3],
                "stalled": r[4],
                "attempt_count": r[5],
                "attempts": r[6],
            }
            for r in rows
        ],
    }
