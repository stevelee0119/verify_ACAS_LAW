"""Authorized durable job status, cancellation and immutable-input retries."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..db import Project, VerificationRun, get_db
from ..identity import actor_id, current_principal, require_project, filter_project_query
from ..job_control import JobConflict, JobStore, TERMINAL
from ..access import project_scoped
from ..schemas import RunOut
from ..services import get_runner
from .verification import _run_out

router = APIRouter(tags=["jobs"])


@router.get("/verification-runs")
@project_scoped
def background_runs(limit: int = Query(default=50, ge=1, le=100), session: Session = Depends(get_db)):
    active = VerificationRun.state.not_in(TERMINAL)
    active_count = session.scalar(filter_project_query(select(func.count(VerificationRun.id)), session,
                                                       VerificationRun.project_id).where(active)) or 0
    query = filter_project_query(select(VerificationRun, Project.name).join(Project), session,
                                 VerificationRun.project_id).where(or_(
        active, VerificationRun.finished_at >= datetime.utcnow() - timedelta(days=1)))
    rows = session.execute(query.order_by(case((active, 0), else_=1),
                                          VerificationRun.started_at.desc(), VerificationRun.id).limit(limit)).all()
    return {"active_count": active_count, "runs": [{
        "id": run.id, "project_id": run.project_id, "project_name": name,
        "state": run.state, "progress": run.progress or 0,
        "stage_message": run.stage_message or "", "started_at": run.started_at,
        "finished_at": run.finished_at,
    } for run, name in rows]}


def project_id_for_run(session: Session, run_id: str) -> str:
    run = session.get(VerificationRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run.project_id


def resolve_job_project(run_id: str, request: Request, session: Session = Depends(get_db)):
    minimum = "VIEWER" if request.method == "GET" else "MEMBER"
    return require_project(session, project_id_for_run(session, run_id), minimum,
                           principal=current_principal(request))


@router.get("/verification-runs/{run_id}/job")
def job_status(run_id: str, project=Depends(resolve_job_project)):
    try:
        return JobStore().status(run_id)
    except KeyError:
        raise HTTPException(404, "Durable job not found") from None


@router.post("/verification-runs/{run_id}/cancel", response_model=RunOut)
def cancel_job(run_id: str, request: Request, project=Depends(resolve_job_project),
               session: Session = Depends(get_db)):
    try:
        JobStore().cancel(run_id, actor=actor_id(request))
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    session.expire_all()
    return _run_out(session.get(VerificationRun, run_id))


@router.post("/verification-runs/{run_id}/retry", response_model=RunOut, status_code=202)
def retry_job(run_id: str, request: Request, project=Depends(resolve_job_project),
              session: Session = Depends(get_db)):
    try:
        child_id = JobStore().retry(run_id, actor=actor_id(request))
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    get_runner().submit(child_id)
    session.expire_all()
    return _run_out(session.get(VerificationRun, child_id))
