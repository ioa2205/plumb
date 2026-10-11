"""URL entry for the existing explicitly approved, owned-only assessment workflow."""

from typing import Literal

from pydantic import field_validator

from backend.contracts.assessment import AssessmentScope, ScopeCreate, Text


class WebsiteScopeCreate(ScopeCreate):
    url: Text
    scope: AssessmentScope
    expected_owner_only: Literal[True]
    expectation_basis: Text

    @field_validator("expected_owner_only", mode="before")
    @classmethod
    def explicit_expectation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("the owner access expectation requires an explicit declaration")
        return value
