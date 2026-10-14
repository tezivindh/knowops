"""
Actions module — Pydantic schemas.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Priority = Literal["low", "medium", "high", "urgent"]
TaskStatusName = Literal["draft", "todo", "in_progress", "completed", "cancelled"]


class ChecklistItem(BaseModel):
    text: Text
    done: bool = False


# --- Action payloads ---

class TaskPayload(BaseModel):
    title: Text
    description: str = Field(default="", max_length=10_000)
    priority: Priority = "medium"
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)
    due_date: date | None = None


class EmailPayload(BaseModel):
    subject: Text
    to: list[EmailStr] = Field(default_factory=list, max_length=50)
    body: str = Field(min_length=1, max_length=20_000)


class ProposeActionRequest(BaseModel):
    action_type: Literal["task_create", "email_draft"]
    # Generate the draft from an assistant answer (and its citations)...
    message_id: str | None = Field(default=None, max_length=26)
    # ...and/or from free-text instructions.
    instructions: str | None = Field(default=None, max_length=4000)
    # Or skip generation and supply the payload directly.
    payload: dict[str, Any] | None = None


class UpdateActionRequest(BaseModel):
    payload: dict[str, Any]


class ActionResponse(BaseModel):
    id: str
    organization_id: str
    action_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    proposed_by: str | None
    proposed_by_name: str | None = None
    # The assistant answer this draft was generated from, if any.
    source_message_id: str | None = None
    approved_by: str | None
    source_references: list[dict[str, Any]]
    approved_at: datetime | None
    executed_at: datetime | None
    created_at: datetime


# --- Tasks ---

class CreateTaskRequest(BaseModel):
    title: Text
    description: str | None = Field(default=None, max_length=10_000)
    priority: Priority = "medium"
    status: TaskStatusName = "todo"
    assignee_id: str | None = Field(default=None, max_length=26)
    due_date: date | None = None
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)


class UpdateTaskRequest(BaseModel):
    title: Text | None = None
    description: str | None = Field(default=None, max_length=10_000)
    priority: Priority | None = None
    status: TaskStatusName | None = None
    assignee_id: str | None = Field(default=None, max_length=26)
    due_date: date | None = None
    checklist: list[ChecklistItem] | None = Field(default=None, max_length=50)


class TaskResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: str | None
    status: str
    priority: str
    assignee_id: str | None
    assignee_name: str | None = None
    created_by: str | None
    created_by_name: str | None = None
    due_date: date | None
    checklist: list[ChecklistItem]
    source_references: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
