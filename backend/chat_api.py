"""Protected local chat endpoints. A message never starts or approves work."""

from fastapi import APIRouter, HTTPException

from backend.chat import Chats, saved_results
from backend.contracts.chat import (
    ChatAsk,
    ChatCreate,
    ChatSelect,
    ChatView,
    SavedResult,
    SavedResults,
)


def router(worker: Chats) -> APIRouter:
    result = APIRouter(prefix="/api/chats")

    def refused(error: Exception) -> HTTPException:
        return HTTPException(
            status_code=409,
            detail="Chat request refused. Check the message for secrets, wait for the running "
            "answer, or start a new chat. Saved turns are kept.",
        )

    @result.post("", response_model=ChatView)
    def create(request: ChatCreate) -> ChatView:
        try:
            return worker.new(request)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.get("/saved-results", response_model=SavedResults)
    def results() -> SavedResults:
        return SavedResults(
            results=[
                SavedResult(
                    target_kind=kind,  # ty: ignore[invalid-argument-type]
                    target_id=identifier,
                    label=label,
                )
                for kind, identifier, label in saved_results(worker.settings)
            ]
        )

    @result.get("/{identifier}", response_model=ChatView)
    def read(identifier: str) -> ChatView:
        try:
            return worker.read(identifier)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.post("/{identifier}/ask", response_model=ChatView, status_code=202)
    def ask(identifier: str, request: ChatAsk) -> ChatView:
        try:
            return worker.start(identifier, request)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.post("/{identifier}/select", response_model=ChatView)
    def select(identifier: str, request: ChatSelect) -> ChatView:
        try:
            return worker.select(identifier, request)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    @result.post("/{identifier}/cancel", response_model=ChatView)
    def cancel(identifier: str) -> ChatView:
        try:
            return worker.cancel(identifier)
        except (ValueError, OSError, RuntimeError) as error:
            raise refused(error) from error

    return result
