"""Protected local read-only conversation endpoints."""

from fastapi import APIRouter, HTTPException

from backend.contracts.conversation import ConversationAsk, ConversationCreate, ConversationView
from backend.conversation import Conversations


def router(worker: Conversations) -> APIRouter:
    result = APIRouter(prefix="/api/conversations")

    def refused(error: Exception) -> HTTPException:
        return HTTPException(
            status_code=409,
            detail="Conversation refused. Check the selected local evidence, "
            "model readiness and saved turn limit.",
        )

    @result.post("", response_model=ConversationView)
    def create(request: ConversationCreate) -> ConversationView:
        try:
            return worker.new(request)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.get("/{identifier}", response_model=ConversationView)
    def read(identifier: str) -> ConversationView:
        try:
            return worker.read(identifier)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.post("/{identifier}/ask", response_model=ConversationView, status_code=202)
    def ask(identifier: str, request: ConversationAsk) -> ConversationView:
        try:
            return worker.start(identifier, request)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.post("/{identifier}/cancel", response_model=ConversationView)
    def cancel(identifier: str) -> ConversationView:
        try:
            return worker.cancel(identifier)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    return result
