"""CLI transport and LangChain tool-call bridge regression tests."""

import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from tradingagents.llm_clients.codex_client import CodexChatModel, CodexError, run_codex


@tool
def stock_price(symbol: str) -> str:
    """Look up a stock price."""
    return "123"


def test_adapter_returns_validated_tool_calls(monkeypatch):
    transport = Mock(
        return_value={
            "content": "",
            "tool_calls": [{"name": "stock_price", "arguments": '{"symbol":"TCS.NS"}'}],
        }
    )
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.run_codex", transport)
    result = CodexChatModel().bind_tools([stock_price]).invoke("Analyze TCS.NS")
    assert result.tool_calls[0]["name"] == "stock_price"
    assert result.tool_calls[0]["args"] == {"symbol": "TCS.NS"}
    prompt = transport.call_args.args[0]
    assert "stock_price" in prompt and "Analyze TCS.NS" in prompt


@pytest.mark.parametrize(
    "call",
    [
        {"name": "shell", "arguments": "{}"},
        {"name": "stock_price", "arguments": '{"wrong": 1}'},
        {"name": "stock_price", "arguments": "not-json"},
    ],
)
def test_unknown_or_invalid_tool_calls_rejected(monkeypatch, call):
    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.run_codex",
        lambda *_: {"content": "", "tool_calls": [call]},
    )
    with pytest.raises(CodexError):
        CodexChatModel().bind_tools([stock_price]).invoke("Analyze")


def test_tool_results_preserved_in_next_request(monkeypatch):
    transport = Mock(return_value={"content": "Evidence report", "tool_calls": []})
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.run_codex", transport)
    messages = [
        HumanMessage(content="Analyze"),
        AIMessage(
            content="",
            tool_calls=[{"name": "stock_price", "args": {"symbol": "TCS.NS"}, "id": "call1"}],
        ),
        ToolMessage(content="123 INR", tool_call_id="call1"),
    ]
    assert CodexChatModel().invoke(messages).content == "Evidence report"
    assert "123 INR" in transport.call_args.args[0]
    assert "call1" in transport.call_args.args[0]


def test_pydantic_structured_output_uses_bridge(monkeypatch):
    class Decision(BaseModel):
        action: str

    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.run_codex",
        lambda *_: {
            "content": "",
            "tool_calls": [{"name": "Decision", "arguments": '{"action":"HOLD"}'}],
        },
    )
    result = CodexChatModel().with_structured_output(Decision).invoke("Decide")
    assert result.action == "HOLD"


def test_transport_uses_stdin_no_shell_and_no_api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    monkeypatch.setenv("DASHBOARD_SECRET", "do-not-inherit")

    def complete(command, **kwargs):
        assert kwargs["input"] == "private prompt"
        assert "private prompt" not in command
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "DASHBOARD_SECRET" not in kwargs["env"]
        assert "read-only" in command and "features.shell_tool=false" in command
        assert not kwargs.get("shell")
        output = command[command.index("--output-last-message") + 1]
        from pathlib import Path

        Path(output).write_text(json.dumps({"content": "OK", "tool_calls": []}))
        return Mock(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("tradingagents.llm_clients.codex_client.subprocess.run", complete)
    assert run_codex("private prompt", "gpt-6-astra")["content"] == "OK"


def test_transport_errors_are_secret_free(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.subprocess.run",
        lambda *_args, **_kwargs: Mock(
            returncode=1, stderr="secret usage limit reached", stdout=""
        ),
    )
    with pytest.raises(CodexError, match="usage limit") as error:
        run_codex("prompt", "gpt-6-astra")
    assert "secret" not in str(error.value)


def test_explicit_no_tools_rejects_model_tool_request(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.run_codex",
        lambda *_: {
            "content": "",
            "tool_calls": [{"name": "stock_price", "arguments": '{"symbol":"TCS.NS"}'}],
        },
    )
    with pytest.raises(CodexError):
        CodexChatModel().bind_tools([stock_price], tool_choice="none").invoke("Analyze")


def test_explicit_named_tool_is_required(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.run_codex",
        lambda *_: {"content": "No call", "tool_calls": []},
    )
    with pytest.raises(CodexError):
        CodexChatModel().bind_tools(
            [stock_price], tool_choice={"type": "function", "function": {"name": "stock_price"}}
        ).invoke("Analyze")
