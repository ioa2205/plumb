import pytest

from tandir.seed import PASSWORDS

ROLES = {
    "alice": "customer",
    "bob": "customer",
    "kamol": "courier",
    "farrukh": "branch_manager",
    "nodira": "branch_manager",
    "admin": "admin",
}


def test_health(lab) -> None:
    assert lab.client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("username", sorted(PASSWORDS))
def test_every_fixture_user_signs_in_with_their_role(lab, username: str) -> None:
    me = lab.client.get("/auth/me", headers=lab.as_(username))
    assert me.status_code == 200
    assert me.json()["username"] == username
    assert me.json()["role"] == ROLES[username]


def test_wrong_password_is_refused(lab) -> None:
    response = lab.client.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert response.status_code == 401


def test_unknown_user_is_refused_with_the_same_message(lab) -> None:
    unknown = lab.client.post("/auth/login", json={"username": "zara", "password": "x"})
    wrong = lab.client.post("/auth/login", json={"username": "alice", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-session"}, {"Authorization": "Basic YWxpY2U6eA=="}],
)
def test_requests_without_a_session_are_refused(lab, headers: dict[str, str]) -> None:
    assert lab.client.get("/auth/me", headers=headers).status_code == 401
    assert lab.client.get("/orders", headers=headers).status_code == 401


def test_session_cookie_is_accepted(lab) -> None:
    lab.client.cookies.set("tandir_session", lab.token("alice"))
    try:
        assert lab.client.get("/auth/me").json()["username"] == "alice"
    finally:
        lab.client.cookies.clear()


def test_logout_ends_the_session(lab) -> None:
    headers = lab.as_("alice")
    assert lab.client.post("/auth/logout", headers=headers).status_code == 204
    assert lab.client.get("/auth/me", headers=headers).status_code == 401


def test_passwords_are_stored_as_scrypt_hashes(lab) -> None:
    from sqlalchemy import select

    from tandir.models import User

    with lab.client.app.state.sessionmaker() as db:
        for user in db.scalars(select(User)):
            assert user.password_hash.startswith("scrypt$")
            assert PASSWORDS[user.username] not in user.password_hash
