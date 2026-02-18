# routers/tasks.py

import logging
from fastapi import APIRouter, HTTPException, Request

from workers.celery_worker import celery_app

logger = logging.getLogger("DeepRouter.Tasks")

router = APIRouter(prefix="/api/v1", tags=["Tasks"])

# Celery states we surface directly
_TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED"}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    """
    Poll the result of an async Celery task (e.g. a quant analysis job).

    States:
      - PENDING   — task queued but not yet picked up by a worker
      - STARTED   — worker is executing the task
      - SUCCESS   — completed; 'result' contains the full analysis
      - FAILURE   — task raised an exception; 'error' contains the message
      - REVOKED   — task was manually cancelled
    """
    user_id = getattr(request.state, "user_id", "unknown")

    result = celery_app.AsyncResult(task_id)
    state = result.state

    response: dict = {"task_id": task_id, "status": state.lower()}

    if state == "SUCCESS":
        response["result"] = result.get()
        logger.info(f"[Tasks] {user_id} polled task {task_id}: SUCCESS")

    elif state == "FAILURE":
        # Safely serialise the exception — never leak a raw traceback
        exc = result.result
        response["error"] = str(exc) if exc else "Unknown error"
        logger.warning(f"[Tasks] {user_id} polled task {task_id}: FAILURE — {response['error']}")

    elif state == "PENDING":
        response["message"] = "Task is queued and waiting for a worker."

    elif state == "STARTED":
        meta = result.info or {}
        response["message"] = "Worker is processing the task."
        if meta:
            response["progress"] = meta  # Workers can push progress via update_state()

    elif state == "REVOKED":
        response["message"] = "Task was cancelled."

    else:
        # Celery custom states (e.g. RETRY set by self.retry)
        response["message"] = f"Task is in state: {state}"

    return response


@router.delete("/tasks/{task_id}", tags=["Tasks"])
async def cancel_task(task_id: str, request: Request):
    """
    Request cancellation of a running or queued task.
    Note: cancellation of already-running tasks requires workers to honour the SIGTERM.
    """
    user_id = getattr(request.state, "user_id", "unknown")
    result = celery_app.AsyncResult(task_id)

    if result.state in _TERMINAL_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Task is already in terminal state: {result.state.lower()}",
        )

    result.revoke(terminate=True, signal="SIGTERM")
    logger.info(f"[Tasks] {user_id} cancelled task {task_id}")
    return {"task_id": task_id, "status": "cancellation_requested"}
