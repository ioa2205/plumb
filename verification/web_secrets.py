"""Test-account secrets: named by opaque references, resolved only by the runner (ADR-0028).

A password or token is never part of a scope, a plan, an observation, a model
request, a checkpoint or a report. Contracts carry the reference; this store
turns it into the value at the moment a field is filled, and hands every value
to the redactor so that nothing that echoes one can be saved.
"""

import os
import re
import secrets
import string

ENV_PREFIX = "PLUMB_WEB_SECRET_"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}")


class MissingSecret(ValueError):
    """The reference has no value here. The message names the reference, never a value."""


def env_name(ref: str) -> str:
    if _REF.fullmatch(ref) is None:
        raise MissingSecret("A secret reference is a short plain name.")
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", ref.upper())


class SecretStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = {}
        for ref, value in (values or {}).items():
            self.put(ref, value)

    def __repr__(self) -> str:
        return f"SecretStore({len(self._values)} references)"

    def put(self, ref: str, value: str) -> None:
        env_name(ref)
        if not value or len(value) > 1024 or any(ord(char) < 32 for char in value):
            raise MissingSecret(f"The value for {ref} is empty or not a single line.")
        self._values[ref] = value

    def load_environment(self, refs: list[str]) -> list[str]:
        """Take values from ``PLUMB_WEB_SECRET_<REF>``; returns the references still missing."""
        missing = []
        for ref in refs:
            if ref in self._values:
                continue
            value = os.environ.get(env_name(ref))
            if value:
                self.put(ref, value)
            else:
                missing.append(ref)
        return missing

    def generate(self, ref: str) -> None:
        """A fresh password for an account that an approved sign-up is about to create."""
        if ref not in self._values:
            alphabet = string.ascii_letters + string.digits
            self.put(ref, "Pl-" + "".join(secrets.choice(alphabet) for _ in range(20)) + "-9x")

    def has(self, ref: str) -> bool:
        return ref in self._values

    def get(self, ref: str) -> str:
        try:
            return self._values[ref]
        except KeyError:
            raise MissingSecret(
                f"No value is available for the secret reference {ref}. "
                f"Set {env_name(ref)} or enter it when asked."
            ) from None

    def values(self) -> tuple[str, ...]:
        """For the redactor only."""
        return tuple(self._values.values())

    def clear(self) -> None:
        self._values.clear()
