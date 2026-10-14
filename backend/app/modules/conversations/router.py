"""
Conversations module — API router.

Conversation CRUD and the RAG chat endpoint. All routes are scoped to an
organization and enforce membership + per-user conversation ownership.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.dependencies import DbSession
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.schemas import (
    CitationResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.modules.conversations.service import ConversationService
from app.modules.documents.access import visible_versions
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.modules.organizations.service import OrganizationService

router = APIRouter(prefix="/organizations/{org_id}/conversations", tags=["conversations"])


async def get_conversation_service(db: DbSession) -> ConversationService:
    return ConversationService(db)


async def get_org_service(db: DbSession) -> OrganizationService:
    return OrganizationService(db)


# --- Serialization helpers ---


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        organization_id=conversation.organization_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def _build_messages(
    service: ConversationService, messages: list[Message], org_id: str, user_id: str
) -> list[MessageResponse]:
    citation_map = await service.get_citations([m.id for m in messages])
    lookup = await visible_versions(service.db, user_id, org_id)

    responses: list[MessageResponse] = []
    for message in messages:
        citations = []
        inaccessible = any(
            c.document_version_id not in lookup for c in citation_map.get(message.id, [])
        )
        for citation in [] if inaccessible else citation_map.get(message.id, []):
            doc_id, title = lookup.get(citation.document_version_id, (None, None))
            citations.append(
                CitationResponse(
                    citation_index=citation.citation_index,
                    document_id=doc_id,
                    document_title=title,
                    document_version_id=citation.document_version_id,
                    chunk_id=citation.chunk_id,
                    quoted_text=citation.quoted_text,
                    page_number=citation.page_number,
                    section_heading=citation.section_heading,
                    relevance_score=citation.relevance_score,
                )
            )
        responses.append(
            MessageResponse(
                id=message.id,
                role=message.role.value,
                content=(
                    "This answer is unavailable because source access has changed."
                    if inaccessible
                    else message.content
                ),
                model_used=message.model_used,
                token_count=message.token_count,
                created_at=message.created_at,
                citations=citations,
            )
        )
    return responses


# --- Endpoints ---


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    org_id: str,
    request: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    """Create a new conversation thread."""
    await org_service.require_membership(current_user.id, org_id)
    conversation = await service.create_conversation(org_id, current_user.id, request.title)
    return _conversation_response(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    org_id: str,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationResponse]:
    """List the current user's conversations in the organization."""
    await org_service.require_membership(current_user.id, org_id)
    conversations = await service.list_conversations(org_id, current_user.id)
    return [_conversation_response(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    org_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    """Get a conversation with its full message history."""
    await org_service.require_membership(current_user.id, org_id)
    conversation = await service.get_conversation(conversation_id, org_id, current_user.id)
    messages = await service.get_messages(conversation.id)
    return ConversationDetailResponse(
        conversation=_conversation_response(conversation),
        messages=await _build_messages(service, messages, org_id, current_user.id),
    )


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    org_id: str,
    conversation_id: str,
    request: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    """Rename a conversation."""
    await org_service.require_membership(current_user.id, org_id)
    conversation = await service.rename_conversation(
        conversation_id, org_id, current_user.id, request.title
    )
    return _conversation_response(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    org_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    """Delete a conversation and all its messages."""
    await org_service.require_membership(current_user.id, org_id)
    await service.delete_conversation(conversation_id, org_id, current_user.id)


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    org_id: str,
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    service: ConversationService = Depends(get_conversation_service),
) -> SendMessageResponse:
    """Send a message and receive a grounded, cited assistant answer."""
    await org_service.require_membership(current_user.id, org_id)
    user_message, assistant_message = await service.send_message(
        org_id, current_user.id, conversation_id, request.content
    )
    built = await _build_messages(
        service, [user_message, assistant_message], org_id, current_user.id
    )
    return SendMessageResponse(
        conversation_id=conversation_id,
        user_message=built[0],
        assistant_message=built[1],
    )
