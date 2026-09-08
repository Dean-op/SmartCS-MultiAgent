from scripts import smoke_test


def test_base_smoke_accepts_authentication_as_the_chat_boundary(monkeypatch, capsys) -> None:
    def fake_fetch_json(url, *, method="GET", payload=None, timeout=5.0):
        if url.endswith("/health/live"):
            return 200, {"status": "alive"}
        if url.endswith("/health/ready"):
            return 200, {
                "status": "ready",
                "dependencies": smoke_test.EXPECTED_DEPENDENCIES,
            }
        if url.endswith("/api/v1/chat"):
            return 401, {"error": {"code": "http_error", "message": "Unauthorized", "details": []}}
        raise AssertionError(url)

    monkeypatch.setattr(smoke_test, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(smoke_test, "fetch_text", lambda *_args, **_kwargs: (200, "Swagger UI"))
    monkeypatch.setattr(smoke_test.time, "sleep", lambda _seconds: None)

    smoke_test.run_smoke_test("http://test", wait_seconds=0.02)

    assert "M15 base smoke passed" in capsys.readouterr().out
