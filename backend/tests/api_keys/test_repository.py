"""ApiKeyRepository: rows are scoped to their owner and go with the account."""

from backend.api_keys.repository import ApiKeyRepository


def _user(username: str) -> int:
    from backend.database import db_write

    with db_write() as conn:
        return conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, 'x')", (username,)
        ).lastrowid


def _create(repo: ApiKeyRepository, uid: int, name: str, key_hash: str, created_at: str):
    key = repo.create_within_limit(
        uid, name, "partiu_abc123", key_hash, "read", created_at, None, limit=100
    )
    assert key is not None
    return key


class TestApiKeyRepository:
    def test_lists_only_the_owners_keys_newest_first(self, test_db):
        repo = ApiKeyRepository()
        alice, bob = _user("alice"), _user("bob")
        _create(repo, alice, "old", "h1", "2026-01-01T00:00:00+00:00")
        _create(repo, alice, "new", "h2", "2026-06-01T00:00:00+00:00")
        _create(repo, bob, "bobs", "h3", "2026-03-01T00:00:00+00:00")

        assert [k.name for k in repo.list_for_user(alice)] == ["new", "old"]
        assert [k.name for k in repo.list_for_user(bob)] == ["bobs"]

    def test_the_limit_is_checked_by_the_insert_itself(self, test_db):
        repo = ApiKeyRepository()
        alice, bob = _user("alice"), _user("bob")
        args = ("partiu_abc123", "read", "2026-01-01T00:00:00+00:00", None)
        assert repo.create_within_limit(alice, "a", args[0], "h1", *args[1:], limit=2)
        assert repo.create_within_limit(alice, "b", args[0], "h2", *args[1:], limit=2)
        assert repo.create_within_limit(alice, "c", args[0], "h3", *args[1:], limit=2) is None
        assert repo.find_by_hash("h3") is None
        # Someone else's keys do not count against alice's limit.
        assert repo.create_within_limit(bob, "d", args[0], "h4", *args[1:], limit=2)

    def test_find_by_hash(self, test_db):
        repo = ApiKeyRepository()
        key = _create(repo, _user("alice"), "x", "abc", "2026-01-01T00:00:00+00:00")
        found = repo.find_by_hash("abc")
        assert found is not None and found.id == key.id
        assert repo.find_by_hash("nope") is None

    def test_delete_is_scoped_to_the_owner(self, test_db):
        repo = ApiKeyRepository()
        alice, bob = _user("alice"), _user("bob")
        key = _create(repo, alice, "x", "abc", "2026-01-01T00:00:00+00:00")
        assert repo.delete(key.id, bob) is False
        assert repo.delete(key.id, alice) is True
        assert repo.find_by_hash("abc") is None

    def test_touch_records_last_use(self, test_db):
        repo = ApiKeyRepository()
        key = _create(repo, _user("alice"), "x", "abc", "2026-01-01T00:00:00+00:00")
        repo.touch(key.id, "2026-02-02T00:00:00+00:00")
        found = repo.find_by_hash("abc")
        assert found is not None and found.last_used_at == "2026-02-02T00:00:00+00:00"

    def test_deleting_the_account_deletes_its_keys(self, test_db):
        from backend.users.repository import UserRepository

        repo = ApiKeyRepository()
        alice = _user("alice")
        _create(repo, alice, "x", "abc", "2026-01-01T00:00:00+00:00")
        UserRepository().delete_user(alice)
        assert repo.find_by_hash("abc") is None
