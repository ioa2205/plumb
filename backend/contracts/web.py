"""Generic authorized-website contracts (ADR-0028); separate from Tandir's and from source proof.

A scope is the reviewer's exact, expiring declaration of what may be visited and
done. Nothing in a prompt, a page or a model answer can add to it. Secrets are
referred to by opaque names and never appear in any contract.
"""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from backend.contracts.assessment import PortableId, ScopeAuthority
from backend.contracts.common import Contract, Id, Sha256
from backend.web_urls import UrlRefused, check_path, parse_origin, path_within

Text = Annotated[str, Field(min_length=1, max_length=1024)]
Line = Annotated[str, Field(min_length=1, max_length=300)]
ActionClass = Literal[
    "read",  # open an approved page or address and look at it
    "sign_in",  # sign in with a supplied test account
    "sign_up",  # create a designated synthetic account
    "submit_form",  # send an approved form that changes data
    "compare",  # read a known synthetic object under two approved accounts
    "report",
]
# Classes whose effect on the website cannot be taken back by Plumb.
STATE_CHANGING: frozenset[str] = frozenset({"sign_up", "submit_form"})
Mode = Literal["owned_fixture", "external"]
Rung = Literal["code", "model", "model_reordered", "user", "stop"]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _path(value: str) -> str:
    try:
        return check_path(value)
    except UrlRefused as error:
        raise ValueError(str(error)) from error


UrlPath = Annotated[str, Field(min_length=1, max_length=512)]


class WebBudget(Contract):
    max_requests: int = Field(default=300, ge=1, le=2000)
    max_seconds: int = Field(default=900, ge=1, le=7200)
    max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    max_model_questions: int = Field(default=24, ge=0, le=60)


class WebTarget(Contract):
    """One approved origin and the path prefixes approved on it. Nothing is inherited."""

    origin: str = Field(min_length=8, max_length=300)
    paths: list[UrlPath] = Field(min_length=1, max_length=40)

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        try:
            return parse_origin(value).origin
        except UrlRefused as error:
            raise ValueError(str(error)) from error

    @field_validator("paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("approved paths must be distinct")
        return [_path(value) for value in values]


class WebAccount(Contract):
    account_id: Id
    role: Line
    label: Line
    username: str = Field(min_length=1, max_length=128)
    # The name under which the runner finds the password. Never the password itself.
    secret_ref: PortableId
    # False: the account does not exist yet and may be created by an approved sign-up.
    provisioned: bool = True
    # Designated synthetic contact details for a sign-up, if the form asks for them.
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=32)


class WebObject(Contract):
    """A known synthetic object. Unknown identifiers are never tried."""

    object_id: Id
    owner_account_id: Id
    kind: Line
    path: UrlPath  # the exact approved address where it is read
    marker: str | None = Field(default=None, min_length=6, max_length=128)
    synthetic: Literal[True] = True

    @field_validator("path")
    @classmethod
    def _checked(cls, value: str) -> str:
        return _path(value)


class OwnerRule(Contract):
    """What the owner says should happen. A declaration, never an observation."""

    rule_id: Id
    statement: Text
    object_id: Id
    allowed_account_ids: list[Id] = Field(min_length=1, max_length=6)
    declared_by: Line
    basis: Text


class LoginConfig(Contract):
    path: UrlPath
    # Post-sign-in checks, made by code. At least one is required.
    success_path: UrlPath | None = None
    success_text: str | None = Field(default=None, min_length=2, max_length=128)

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _path(self.path)
        if self.success_path is not None:
            _path(self.success_path)
        if self.success_path is None and self.success_text is None:
            raise ValueError("sign-in needs an explicit post-sign-in check")
        return self


class SignupConfig(Contract):
    path: UrlPath
    # What creating an account does besides creating it, as approved by the owner.
    approved_side_effects: list[Line] = Field(min_length=1, max_length=8)
    sends_messages: bool  # whether an email or SMS is sent to the designated contact
    success_path: UrlPath | None = None
    success_text: str | None = Field(default=None, min_length=2, max_length=128)

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _path(self.path)
        if self.success_path is not None:
            _path(self.success_path)
        if self.success_path is None and self.success_text is None:
            raise ValueError("sign-up needs an explicit check that the account exists")
        return self


class WebsiteScope(Contract):
    scope_id: PortableId
    website_id: PortableId
    name: Line
    mode: Mode
    targets: list[WebTarget] = Field(min_length=1, max_length=8)
    start_path: UrlPath = "/"
    purpose: Text
    authority: ScopeAuthority
    accounts: list[WebAccount] = Field(default_factory=list, max_length=6)
    objects: list[WebObject] = Field(default_factory=list, max_length=20)
    rules: list[OwnerRule] = Field(default_factory=list, max_length=20)
    allowed_actions: list[ActionClass] = Field(min_length=1, max_length=6)
    login: LoginConfig | None = None
    signup: SignupConfig | None = None
    expires_at: datetime
    budget: WebBudget = Field(default_factory=WebBudget)
    stop_conditions: list[Line] = Field(min_length=1, max_length=12)
    # Contact details the site shows to everyone (a support address), declared by the
    # reviewer so that they are not mistaken for a real person's data.
    public_values: list[Line] = Field(default_factory=list, max_length=20)
    # The reviewer confirmed this exact list of origins and paths, and nothing else.
    confirmed_targets: Literal[True]

    @field_validator("confirmed_targets", mode="before")
    @classmethod
    def _confirmed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("the exact target list needs the reviewer's explicit confirmation")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.expires_at.tzinfo is None or self.expires_at <= self.authority.granted_at:
            raise ValueError("scope expiry must follow its authorization and carry a timezone")
        origins = [target.origin for target in self.targets]
        if len(set(origins)) != len(origins):
            raise ValueError("each approved origin appears once")
        for origin in origins:
            url = parse_origin(origin)
            loopback = url.ip is not None and url.ip.is_loopback
            if self.mode == "owned_fixture" and (
                url.scheme != "http" or str(url.ip) != "127.0.0.1"
            ):
                raise ValueError("an owned fixture is addressed as http://127.0.0.1:<port> only")
            if self.mode == "external" and (url.scheme != "https" or loopback):
                raise ValueError(
                    "an external website is addressed by https and is not this computer"
                )
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("allowed action classes must be distinct")
        accounts = [account.account_id for account in self.accounts]
        refs = [account.secret_ref for account in self.accounts]
        objects = [item.object_id for item in self.objects]
        rules = [rule.rule_id for rule in self.rules]
        if any(len(set(ids)) != len(ids) for ids in (accounts, refs, objects, rules)):
            raise ValueError("account, secret-reference, object and rule names must be unique")
        if any(item.owner_account_id not in accounts for item in self.objects):
            raise ValueError("a synthetic object's owner must be a declared account")
        for rule in self.rules:
            if rule.object_id not in objects or not set(rule.allowed_account_ids) <= set(accounts):
                raise ValueError("an owner rule must name declared objects and accounts")
        _path(self.start_path)
        first = self.targets[0]
        declared = [self.start_path, *[item.path for item in self.objects]]
        for config in (self.login, self.signup):
            if config is not None:
                declared.extend(filter(None, [config.path, config.success_path]))
        if any(not any(path_within(path, prefix) for prefix in first.paths) for path in declared):
            raise ValueError(
                "start, sign-in, sign-up and object addresses must lie inside the first "
                "approved origin's paths"
            )
        if self.accounts and "sign_in" in self.allowed_actions and self.login is None:
            raise ValueError("signing in needs the sign-in page and its post-sign-in check")
        unprovisioned = [account for account in self.accounts if not account.provisioned]
        if unprovisioned and ("sign_up" not in self.allowed_actions or self.signup is None):
            raise ValueError(
                "an account that does not exist yet needs sign-up approved and configured"
            )
        if "compare" in self.allowed_actions and (len(self.accounts) < 2 or not self.objects):
            raise ValueError("comparing needs two declared accounts and a known synthetic object")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))

    @property
    def origin(self) -> str:
        """The primary origin: where the journey starts and its accounts live."""
        return self.targets[0].origin


class ScopeDraft(Contract):
    """What a setup form or wizard collects before the reviewer confirms the scope."""

    scope: WebsiteScope
    confirmed_authority: Literal[True]

    @field_validator("confirmed_authority", mode="before")
    @classmethod
    def _confirmed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("authorization needs the reviewer's explicit confirmation")
        return value


# --- plan and permission ----------------------------------------------------------------------


class PlanStep(Contract):
    step_id: Id
    stage: Literal["discover", "authenticate", "map", "check", "report"]
    action: ActionClass
    account_id: Id | None = None
    object_id: Id | None = None
    summary: Line
    state_changing: bool
    max_requests: int = Field(ge=0, le=2000)


class WebsitePlan(Contract):
    """One bounded plan, shown in plain words and approved once."""

    plan_id: Id
    website_id: PortableId
    scope_sha256: Sha256
    steps: list[PlanStep] = Field(min_length=1, max_length=60)
    budget: WebBudget
    model_questions: int = Field(ge=0, le=60)
    expected_model_seconds: float = Field(ge=0, allow_inf_nan=False)
    unmeasured_question_types: list[str] = Field(default_factory=list, max_length=20)
    not_covered: list[Line] = Field(default_factory=list, max_length=20)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class PlanApproval(Contract):
    plan_sha256: Sha256
    approved_step_ids: list[Id] = Field(min_length=1, max_length=60)
    approved_by: Line
    granted_at: AwareDatetime
    expires_at: AwareDatetime
    reviewed_plan: Literal[True]

    @field_validator("reviewed_plan", mode="before")
    @classmethod
    def _reviewed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("approval needs the explicit reviewed-plan confirmation")
        return value


# --- observations -------------------------------------------------------------------------------


class ObservedField(Contract):
    ref: str = Field(pattern=r"^o[0-9a-f]{8}-f[0-9]{1,3}-i[0-9]{1,3}$")
    name: str = Field(max_length=80)
    label: str = Field(max_length=120)
    input_type: str = Field(max_length=24)
    hint: str = Field(default="", max_length=40)  # the field's autocomplete attribute
    required: bool = False
    has_value: bool = False  # never the value itself


class ObservedForm(Contract):
    ref: str = Field(pattern=r"^o[0-9a-f]{8}-f[0-9]{1,3}$")
    method: Literal["GET", "POST"]
    action_path: str = Field(max_length=512)
    in_scope: bool
    heading: str = Field(default="", max_length=120)
    submit_label: str = Field(default="", max_length=120)
    fields: list[ObservedField] = Field(default_factory=list, max_length=40)


class ObservedLink(Contract):
    ref: str = Field(pattern=r"^o[0-9a-f]{8}-l[0-9]{1,3}$")
    text: str = Field(max_length=120)
    path: str = Field(max_length=512)
    in_scope: bool


class BlockedRequest(Contract):
    """Something the page wanted that was not allowed. Shown, never silently dropped."""

    kind: Literal["off_scope", "redirect", "websocket", "download", "budget", "address", "other"]
    host: str = Field(max_length=253)
    reason: Line
    count: int = Field(default=1, ge=1)


class PageObservation(Contract):
    """What one page looked like to one account, already sanitized and bounded."""

    observation_id: str = Field(pattern=r"^o[0-9a-f]{8}$")
    via: Literal["http", "browser"]
    account_id: Id | None = None
    origin: str = Field(max_length=300)
    path: str = Field(max_length=512)
    status: int | None = Field(default=None, ge=100, le=599)
    title: str = Field(default="", max_length=160)
    headings: list[str] = Field(default_factory=list, max_length=12)
    text: str = Field(default="", max_length=4000)
    links: list[ObservedLink] = Field(default_factory=list, max_length=60)
    forms: list[ObservedForm] = Field(default_factory=list, max_length=12)
    blocked: list[BlockedRequest] = Field(default_factory=list, max_length=40)
    challenge: Literal["none", "captcha", "one_time_code", "single_sign_on"] = "none"
    collected_at: AwareDatetime
    truncated: bool = False

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class WebEvidence(Contract):
    """One sanitized observation kept as evidence. Fields are cited exactly, by hash."""

    evidence_id: Id
    website_id: PortableId
    kind: Literal["page", "response", "comparison", "screenshot", "note"]
    via: Literal["http", "browser", "code"]
    account_id: Id | None = None
    object_id: Id | None = None
    fields: dict[str, str] = Field(min_length=1, max_length=60)
    collected_at: AwareDatetime
    provenance: Line
    sha256: Sha256
    reviewed: bool = False  # a human looked at it; required before it leaves this computer

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if sum(len(k.encode()) + len(v.encode()) for k, v in self.fields.items()) > 65536:
            raise ValueError("an evidence item is bounded to 64 KiB of sanitized text")
        expected = digest(
            {
                "evidence_id": self.evidence_id,
                "kind": self.kind,
                "account_id": self.account_id,
                "object_id": self.object_id,
                "fields": self.fields,
            }
        )
        if self.sha256 != expected:
            raise ValueError("evidence hash does not match its content")
        return self


class EvidenceRef(Contract):
    evidence_id: Id
    field: Line
    sha256: Sha256  # of that field's exact value
