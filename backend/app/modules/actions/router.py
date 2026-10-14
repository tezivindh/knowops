"""
Actions module — API router.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select

from app.dependencies import DbSession
from app.modules.actions.models import ActionRun, Task
from app.modules.actions.schemas import (
    ActionResponse,
    CreateTaskRequest,
    ProposeActionRequest,
    TaskResponse,
    UpdateActionRequest,
    UpdateTaskRequest,
)
from app.modules.actions.service import ActionsService, answer_message_id
from app.modules.audit.models import AuditAction
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.shared.utils import client_ip, request_id_of

router = APIRouter(prefix="/organizations/{org_id}", tags=["actions"])


async def get_service(db: DbSession) -> ActionsService:
    return ActionsService(db)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


async def _names(service: ActionsService, ids: set[str | None]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await service.db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.all())


def _action_response(run: ActionRun, names: dict[str, str]) -> ActionResponse:
    return ActionResponse(
        id=run.id,
        organization_id=run.organization_id,
        action_type=run.action_type.value,
        status=run.status.value,
        payload=_loads(run.payload, {}),
        result=_loads(run.result, {}) or None,
        error_message=run.error_message,
        proposed_by=run.proposed_by,
        proposed_by_name=names.get(run.proposed_by or ""),
        source_message_id=answer_message_id(run),
        approved_by=run.approved_by,
        source_references=_loads(run.source_references, []),
        approved_at=run.approved_at,
        executed_at=run.executed_at,
        created_at=run.created_at,
    )


def _task_response(task: Task, names: dict[str, str]) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        organization_id=task.organization_id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        priority=task.priority.value,
        assignee_id=task.assignee_id,
        assignee_name=names.get(task.assignee_id or ""),
        created_by=task.created_by,
        created_by_name=names.get(task.created_by or ""),
        due_date=task.due_date.date() if task.due_date else None,
        checklist=_loads(task.checklist, []),
        source_references=_loads(task.source_references, []),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def _audit(
    service: ActionsService, request: Request, action: AuditAction,
    user_id: str, org_id: str, run_id: str,
) -> None:
    await AuditService(service.db).log_event(
        action=action,
        actor_id=user_id,
        organization_id=org_id,
        resource_type="action",
        resource_id=run_id,
        ip_address=client_ip(request),
        request_id=request_id_of(request),
    )


# --- Action runs ---


@router.get("/actions", response_model=list[ActionResponse])
async def list_actions(
    org_id: str,
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> list[ActionResponse]:
    """Proposed and completed actions (admins see everyone's)."""
    runs = await service.list_runs(org_id, current_user.id, status_filter)
    names = await _names(service, {r.proposed_by for r in runs})
    return [_action_response(r, names) for r in runs]


@router.post("/actions", response_model=ActionResponse, status_code=status.HTTP_201_CREATED)
async def propose_action(
    org_id: str,
    request: ProposeActionRequest,
    http_request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> ActionResponse:
    """Draft a task or email (from an answer, instructions, or a given payload).

    Returns 200 with the existing draft if this answer was already drafted.
    """
    run, created = await service.propose(
        org_id,
        current_user.id,
        request.action_type,
        request.message_id,
        request.instructions,
        request.payload,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _action_response(run, await _names(service, {run.proposed_by}))
    await _audit(
        service, http_request, AuditAction.ACTION_PROPOSED, current_user.id, org_id, run.id
    )
    return _action_response(run, {current_user.id: current_user.full_name})


@router.patch("/actions/{run_id}", response_model=ActionResponse)
async def update_action(
    org_id: str,
    run_id: str,
    request: UpdateActionRequest,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> ActionResponse:
    """Edit a proposed action's draft before approving it."""
    run = await service.update_payload(org_id, current_user.id, run_id, request.payload)
    return _action_response(run, await _names(service, {run.proposed_by}))


@router.post("/actions/{run_id}/approve", response_model=ActionResponse)
async def approve_action(
    org_id: str,
    run_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> ActionResponse:
    """Approve and execute a proposed action."""
    run = await service.approve(org_id, current_user.id, run_id)
    await _audit(
        service, http_request, AuditAction.ACTION_APPROVED, current_user.id, org_id, run.id
    )
    return _action_response(run, await _names(service, {run.proposed_by}))


@router.post("/actions/{run_id}/reject", response_model=ActionResponse)
async def reject_action(
    org_id: str,
    run_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> ActionResponse:
    """Reject a proposed action."""
    run = await service.reject(org_id, current_user.id, run_id)
    await _audit(
        service, http_request, AuditAction.ACTION_REJECTED, current_user.id, org_id, run.id
    )
    return _action_response(run, await _names(service, {run.proposed_by}))


# --- Tasks ---


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    org_id: str,
    status_filter: str | None = Query(None, alias="status"),
    assignee: str | None = Query(None, description="'me' or a user id"),
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> list[TaskResponse]:
    tasks = await service.list_tasks(org_id, current_user.id, status_filter, assignee)
    names = await _names(service, {t.assignee_id for t in tasks} | {t.created_by for t in tasks})
    return [_task_response(t, names) for t in tasks]


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    org_id: str,
    request: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> TaskResponse:
    task = await service.create_task(org_id, current_user.id, request.model_dump())
    return _task_response(task, await _names(service, {task.assignee_id, task.created_by}))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    org_id: str,
    task_id: str,
    request: UpdateTaskRequest,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> TaskResponse:
    task = await service.update_task(
        org_id, current_user.id, task_id, request.model_dump(exclude_unset=True)
    )
    return _task_response(task, await _names(service, {task.assignee_id, task.created_by}))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    org_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    service: ActionsService = Depends(get_service),
) -> None:
    await service.delete_task(org_id, current_user.id, task_id)
