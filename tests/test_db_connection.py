from app.core.config import Settings
from scripts import check_db_connection


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.fetchone_count = 0
        self.closed = False

    def execute(self, sql):
        self.executed.append(sql)

    def fetchone(self):
        self.fetchone_count += 1
        return (1,)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def settings():
    return Settings(
        "test-secret",
        True,
        db_server="sqlserver.example.test",
        db_name="chatbot",
        db_user="chatbot_app",
        db_password="db-test-password",
    )


def test_check_connection_executes_only_select_one_and_closes():
    connection = FakeConnection()

    check_db_connection.check_connection(settings(), connect=lambda _: connection)

    assert connection.cursor_instance.executed == ["SELECT 1"]
    assert connection.cursor_instance.fetchone_count == 1
    assert connection.cursor_instance.closed is True
    assert connection.closed is True


def test_connection_error_message_does_not_expose_password(monkeypatch, capsys):
    monkeypatch.setattr(check_db_connection.Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setattr(
        check_db_connection,
        "_default_connect",
        lambda _: (_ for _ in ()).throw(RuntimeError("password=db-test-password")),
    )

    assert check_db_connection.main() == 1
    captured = capsys.readouterr()
    assert "SQL Server connection failed" in captured.err
    assert "db-test-password" not in captured.err
