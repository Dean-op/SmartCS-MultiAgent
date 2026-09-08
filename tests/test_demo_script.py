from scripts import demo


def test_demo_configures_utf8_output_when_stream_supports_it() -> None:
    class ConfigurableStream:
        configured: dict | None = None

        def reconfigure(self, **kwargs) -> None:
            self.configured = kwargs

    stream = ConfigurableStream()

    demo.configure_output(stream)

    assert stream.configured == {"encoding": "utf-8", "errors": "replace"}


def test_demo_runs_read_only_scenarios_and_reuses_order_conversation(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None, str | None]] = []
    output: list[str] = []
    chat_count = 0

    def fake_api_call(base_url, method, path, *, payload=None, token=None):
        nonlocal chat_count
        calls.append((method, path, payload, token))
        if path == "/api/v1/auth/login":
            email = payload["email"]
            return {"access_token": f"secret-token-for-{email}"}, {}
        if path == "/api/v1/chat":
            chat_count += 1
            return (
                {
                    "conversation_id": payload.get(
                        "conversation_id", "11111111-1111-4111-8111-111111111111"
                    ),
                    "message": {"content": f"answer-{chat_count}"},
                },
                {"x-request-id": f"request-{chat_count}"},
            )
        if path == "/api/v1/reviews/pending":
            return [], {}
        raise AssertionError(path)

    monkeypatch.setattr(demo, "api_call", fake_api_call)

    demo.run_demo("http://test", emit=output.append)

    chat_calls = [call for call in calls if call[1] == "/api/v1/chat"]
    assert len(chat_calls) == 6
    assert "conversation_id" not in chat_calls[1][2]
    assert chat_calls[2][2]["conversation_id"] == "11111111-1111-4111-8111-111111111111"
    assert all(call[3] == "secret-token-for-alice@example.com" for call in chat_calls)
    assert any(call[1] == "/api/v1/reviews/pending" for call in calls)
    assert "secret-token" not in "\n".join(output)
