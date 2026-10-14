"""
Conversations module — Pydantic schemas.

Request/response models for conversations, messages, and citations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationUpdateRequest(BaseModel):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class ConversationResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class CitationResponse(BaseModel):
    citation_index: int
    document_id: str | None = None
    document_title: str | None = None
    document_version_id: str
    chunk_id: str
    quoted_text: str
    page_number: int | None = None
    section_heading: str | None = None
    relevance_score: str | None = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    model_used: str | None = None
    token_count: int | None = None
    created_at: datetime
    citations: list[CitationResponse] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SendMessageResponse(BaseModel):
    conversation_id: str
    user_message: MessageResponse
    assistant_message: MessageResponse
