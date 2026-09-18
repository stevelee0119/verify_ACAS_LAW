"""Authorized durable job status, cancellation and immutable-input retries."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import VerificationRun, get_db
from ..identity import actor_id, current_principal, require_project
from ..job_control import JobConflict, JobStore
from ..schemas import RunOut
from ..services import get_runner
from .verification import _run_out

router = APIRouter(tags=["jobs"])


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
