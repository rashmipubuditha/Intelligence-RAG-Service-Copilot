"""Conversation history endpoints."""

from __future__ import annotations

from app.api.deps import ContainerDep, RequireRead, RequireWrite
from app.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
    ErrorResponse,
    MessageResponse,
    Page,
)
from app.core.security import PUBLIC
from fastapi import APIRouter, Query, Response

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse, summary="List conversations")
async def list_conversations(
    container: ContainerDep,
    caller: RequireRead,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ConversationListResponse:
    # Public visitors share one anonymous identity, so listing would show each of them
    # everyone else's questions. A transcript stays reachable by its id, which only the
    # browser that started it holds.
    if caller is PUBLIC:
        return ConversationListResponse(
            conversations=[], page=Page(limit=limit, offset=offset, total=0, returned=0)
        )
    rows = container.chat_service.list_conversations(limit=limit, offset=offset)
    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                message_count=row["message_count"],
            )
            for row in rows
        ],
        page=Page(
            limit=limit,
            offset=offset,
            total=container.conversations.count(),
            returned=len(rows),
        ),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Full transcript with citations and evidence per message",
    responses={404: {"model": ErrorResponse}},
)
async def get_conversation(
    conversation_id: str, container: ContainerDep, caller: RequireRead
) -> ConversationDetailResponse:
    conversation = container.chat_service.get_conversation(conversation_id)
    return ConversationDetailResponse(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        message_count=conversation["message_count"],
        messages=[
            MessageResponse(
                id=message["id"],
                role=message["role"],
                content=message["content"],
                created_at=message["created_at"],
                model=message.get("model"),
                citations=message.get("citations"),
                evidence=message.get("evidence"),
                conflicts=message.get("conflicts"),
                timings=message.get("timings"),
                token_usage=message.get("token_usage"),
                refused=bool(message.get("refused")),
                error=message.get("error"),
            )
            for message in conversation["messages"]
        ],
    )


@router.delete(
    "/{conversation_id}",
    status_code=204,
    summary="Delete a conversation transcript",
    description=(
        "Removes the UI transcript only. The audit log deliberately retains every query and "
        "the context it was answered from — an audit trail a user can erase is not an audit "
        "trail."
    ),
    responses={404: {"model": ErrorResponse}},
)
async def delete_conversation(
    conversation_id: str, container: ContainerDep, caller: RequireWrite
) -> Response:
    container.chat_service.delete_conversation(conversation_id)
    return Response(status_code=204)
