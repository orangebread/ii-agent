"""Deep unit tests for ii_agent.chat.llm.openai (OpenAIProvider) - coverage gaps."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from ii_agent.core.config.llm_config import LLMConfig
from ii_agent.chat.types import (
    ArrayResultContent,
    BinaryContent,
    ErrorJsonContent,
    ExecutionDeniedContent,
    FileDataContentPart,
    FinishReason,
    ImageDataContentPart,
    ImageUrlContentPart,
    JsonResultContent,
    Message,
    MessageRole,
    ReasoningContent,
    StorybookProgressContent,
    StorybookResultContent,
    TextContent,
    TextResultContent,
    ToolCall,
    ToolResult,
)

_SESSION_ID = "00000000-0000-4000-8000-000000000321"


def _make_llm_config(
    model: str = "gpt-4o",
    api_key: str = "test-key",
    azure_endpoint: Optional[str] = None,
    azure_api_version: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    thinking_tokens: Optional[int] = None,
) -> LLMConfig:
    kwargs: Dict[str, Any] = dict(
        model=model,
        provider="OpenAI",
        api_key=SecretStr(api_key),
    )
    if azure_endpoint is not None:
        kwargs["azure_endpoint"] = azure_endpoint
    if azure_api_version is not None:
        kwargs["azure_api_version"] = azure_api_version
    if base_url is not None:
        kwargs["base_url"] = base_url
    if temperature is not None:
        kwargs["temperature"] = temperature
    if thinking_tokens is not None:
        kwargs["thinking_tokens"] = thinking_tokens
    return LLMConfig(**kwargs)


def _make_provider(config: Optional[LLMConfig] = None):
    from ii_agent.chat.llm.openai import OpenAIProvider
    import openai

    with (
        patch.object(openai, "AsyncOpenAI", return_value=MagicMock()),
        patch.object(openai, "AsyncAzureOpenAI", return_value=MagicMock()),
    ):
        return OpenAIProvider(config or _make_llm_config())


def _make_empty_container_file():
    from ii_agent.chat.llm.openai import ContainerFile

    return ContainerFile(container_id=None, files=[])


def _make_user_message(text: str = "Hello", file_ids: Optional[List[str]] = None) -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.USER,
        parts=[TextContent(text=text)],
        file_ids=file_ids,
    )


def _make_assistant_message(
    text: str = "Hi", tool_calls: Optional[List[ToolCall]] = None
) -> Message:
    parts = [TextContent(text=text)]
    if tool_calls:
        parts.extend(tool_calls)
    return Message(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.ASSISTANT,
        parts=parts,
    )


def _make_tool_result_message(tool_call_id: str = "c1", name: str = "tool", output=None) -> Message:
    if output is None:
        output = TextResultContent(value="result")
    return Message(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.TOOL,
        parts=[ToolResult(tool_call_id=tool_call_id, name=name, output=output)],
    )


# ---------------------------------------------------------------------------
# _convert_tools - deeper coverage
# ---------------------------------------------------------------------------


class TestConvertToolsDeep:
    """Tests for _convert_tools covering all branches."""

    def test_code_interpreter_tool_added_when_enabled(self):
        provider = _make_provider()
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(container_id="c1", files=[])
        result = provider._convert_tools(None, cf, is_code_interpreter_enabled=True)
        assert result is not None
        ci_tools = [t for t in result if t.get("type") == "code_interpreter"]
        assert len(ci_tools) == 1

    def test_code_interpreter_tool_includes_file_ids_when_present(self):
        from ii_agent.chat.llm.openai import ContainerFile, FileResponseObject

        provider = _make_provider()
        f = FileResponseObject(
            id="f1",
            provider_file_id="pf1",
            provider="openai",
            content_type="text/csv",
            file_name="data.csv",
        )
        cf = ContainerFile(container_id="c1", files=[f])
        result = provider._convert_tools(None, cf, is_code_interpreter_enabled=True)
        ci_tools = [t for t in result if t.get("type") == "code_interpreter"]
        assert "file_ids" in ci_tools[0]["container"]
        assert "pf1" in ci_tools[0]["container"]["file_ids"]

    def test_code_interpreter_tool_no_file_ids_when_all_images(self):
        from ii_agent.chat.llm.openai import ContainerFile, FileResponseObject

        provider = _make_provider()
        f = FileResponseObject(
            id="f1",
            provider_file_id="pf1",
            provider="openai",
            content_type="image/png",
            file_name="img.png",
        )
        cf = ContainerFile(container_id="c1", files=[f])
        result = provider._convert_tools(None, cf, is_code_interpreter_enabled=True)
        ci_tools = [t for t in result if t.get("type") == "code_interpreter"]
        assert "file_ids" not in ci_tools[0]["container"]

    def test_flat_tool_format_passed_through_unchanged(self):
        provider = _make_provider()
        tool = {"type": "function", "name": "search", "description": "desc", "parameters": {}}
        result = provider._convert_tools([tool], _make_empty_container_file())
        assert result[0] == tool

    def test_nested_function_format_converted_to_flat(self):
        provider = _make_provider()
        tool = {
            "type": "function",
            "function": {"name": "search", "description": "desc", "parameters": {"type": "object"}},
        }
        result = provider._convert_tools([tool], _make_empty_container_file())
        assert result[0]["name"] == "search"
        assert "function" not in result[0]

    def test_unknown_tool_format_passed_through(self):
        provider = _make_provider()
        tool = {"weird_key": "value"}
        result = provider._convert_tools([tool], _make_empty_container_file())
        assert result[0] == tool

    def test_empty_tools_with_code_interpreter_returns_only_ci(self):
        provider = _make_provider()
        result = provider._convert_tools(
            [], _make_empty_container_file(), is_code_interpreter_enabled=True
        )
        assert any(t.get("type") == "code_interpreter" for t in result)

    def test_returns_none_when_no_tools_and_no_ci(self):
        provider = _make_provider()
        result = provider._convert_tools(
            [], _make_empty_container_file(), is_code_interpreter_enabled=False
        )
        assert result is None


# ---------------------------------------------------------------------------
# _convert_messages - deeper user message coverage
# ---------------------------------------------------------------------------


class TestConvertMessagesUserDeep:
    """Deep coverage of user message conversion edge cases."""

    def test_user_message_with_text_only_no_binary(self):
        provider = _make_provider()
        msg = _make_user_message("Hello world")
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_user_message_with_multiple_text_parts(self):
        provider = _make_provider()
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[TextContent(text="First"), TextContent(text="Second")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Both text parts should be included in content
        assert len(result) == 1
        content = result[0]["content"]
        texts = [c["text"] for c in content if c.get("type") == "input_text"]
        assert "First" in texts
        assert "Second" in texts

    def test_user_message_webp_image_converted(self):
        provider = _make_provider()
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[BinaryContent(data=b"webpdata", mime_type="image/webp", path="/tmp/img.webp")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        content = result[0]["content"]
        assert content[0]["type"] == "input_image"

    def test_user_message_gif_image_converted(self):
        provider = _make_provider()
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[BinaryContent(data=b"gifdata", mime_type="image/gif", path="/tmp/img.gif")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        content = result[0]["content"]
        assert content[0]["type"] == "input_image"

    def test_user_message_empty_text_skipped(self):
        provider = _make_provider()
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[TextContent(text="")],
        )
        # Empty text still produces a content part
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Empty text should still generate a message
        assert len(result) == 1

    def test_user_message_with_tool_call_part_skipped(self):
        # ToolCall parts in user messages are not converted to content
        provider = _make_provider()
        tc = ToolCall(id="c1", name="tool", input="{}", finished=True)
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[TextContent(text="Hello"), tc],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Only text content should be present
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _convert_messages - deeper assistant message coverage
# ---------------------------------------------------------------------------


class TestConvertMessagesAssistantDeep:
    """Deep coverage of assistant message conversion."""

    def test_assistant_with_reasoning_content_ignored_in_assistant_output(self):
        # ReasoningContent in assistant messages is not explicitly handled
        provider = _make_provider()
        rc = ReasoningContent(thinking="I think...", signature="sig")
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[rc, TextContent(text="Result")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Assistant message with text should be included
        assert any(m.get("role") == "assistant" for m in result)

    def test_assistant_with_multiple_tool_calls(self):
        provider = _make_provider()
        tc1 = ToolCall(id="call_1", name="search", input='{"q": "a"}', finished=True)
        tc2 = ToolCall(id="call_2", name="calc", input='{"expr": "1+1"}', finished=True)
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[tc1, tc2],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        func_calls = [m for m in result if m.get("type") == "function_call"]
        assert len(func_calls) == 2

    def test_assistant_with_only_tool_call_no_text_message(self):
        """Assistant message with only a ToolCall (no TextContent) should not produce a text message."""
        provider = _make_provider()
        tc = ToolCall(id="call_1", name="search", input='{"q": "test"}', finished=True)
        msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[tc],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Only function_call items, no message items with role="assistant"
        text_messages = [
            m for m in result if m.get("type") == "message" and m.get("role") == "assistant"
        ]
        assert len(text_messages) == 0


# ---------------------------------------------------------------------------
# _convert_messages - tool result deeper coverage
# ---------------------------------------------------------------------------


class TestConvertMessagesToolResultDeep:
    """Deep coverage of tool result conversion in OpenAI format."""

    def test_image_url_content_part_in_array_result(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(value=[ImageUrlContentPart(url="https://example.com/img.png")]),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        output = result[0]["output"]
        assert isinstance(output, list)
        assert any("img.png" in str(item) for item in output)

    def test_storybook_progress_content_converted(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            StorybookProgressContent(
                storybook_id="00000000-0000-4000-8000-000000000421",
                storybook_name="Book",
                total_pages=10,
                completed_pages=5,
                current_page=5,
                status="generating",
                generating_pages=[],
                error_message=None,
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        data = json.loads(result[0]["output"])
        assert data["type"] == "storybook_progress"
        assert data["storybook_id"] == "00000000-0000-4000-8000-000000000421"

    def test_storybook_result_content_converted(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            StorybookResultContent(
                storybook_id="00000000-0000-4000-8000-000000000422",
                storybook_name="B2",
                pages=[],
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        data = json.loads(result[0]["output"])
        assert data["type"] == "storybook"
        assert data["page_count"] == 0

    def test_unknown_output_type_uses_str(self):
        provider = _make_provider()
        # Use a Message with manually mocked tool_results to simulate unknown output type
        msg = MagicMock(spec=Message)
        msg.role = MessageRole.TOOL
        msg.parts = []

        unknown_output = MagicMock()
        unknown_output.__class__.__name__ = "WeirdOutput"

        tr = MagicMock()
        tr.tool_call_id = "c1"
        tr.name = "tool"
        tr.output = unknown_output

        msg.tool_results = MagicMock(return_value=[tr])

        result = provider._convert_messages([msg], _make_empty_container_file())
        # Should not raise, fallback to str
        assert result[0]["type"] == "function_call_output"

    def test_tool_result_with_file_data_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(
                value=[
                    FileDataContentPart(
                        mime_type="application/pdf", data="pdfdata", filename="doc.pdf"
                    )
                ]
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        output = result[0]["output"]
        assert isinstance(output, list)
        assert output[0]["type"] == "input_file"

    def test_tool_result_with_image_data_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(
                value=[ImageDataContentPart(media_type="image/png", data="imgdata")]
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        output = result[0]["output"]
        assert isinstance(output, list)
        assert output[0]["type"] == "input_image"

    def test_tool_result_execution_denied_no_reason(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", ExecutionDeniedContent(reason=None))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"] == "Tool execution denied."

    def test_tool_result_json_result_serialized(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1", "tool", JsonResultContent(value={"nested": {"key": "value"}})
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert json.loads(result[0]["output"]) == {"nested": {"key": "value"}}

    def test_tool_result_error_json_serialized(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1", "tool", ErrorJsonContent(value={"error": "oops", "code": 500})
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        data = json.loads(result[0]["output"])
        assert data["error"] == "oops"


# ---------------------------------------------------------------------------
# OpenAIProvider.send() - deeper coverage
# ---------------------------------------------------------------------------


class TestOpenAIProviderSendDeep:
    """Deep tests for send() method covering various response types."""

    @pytest.mark.asyncio
    async def test_send_with_text_output_message(self):
        provider = _make_provider()

        # Mock ResponseOutputText
        text_part = MagicMock()
        text_part.text = "Hello, I'm ChatGPT!"

        from openai.types.responses import ResponseOutputText

        text_part.__class__ = ResponseOutputText

        output_message = MagicMock()
        output_message.type = "message"
        output_message.content = [text_part]

        mock_response = MagicMock()
        mock_response.output = [output_message]
        mock_response.status = "completed"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        assert result.finish_reason == FinishReason.END_TURN

    @pytest.mark.asyncio
    async def test_send_with_function_call_output(self):
        provider = _make_provider()

        func_call = MagicMock()
        func_call.type = "function_call"
        func_call.call_id = "call_abc"
        func_call.name = "web_search"
        func_call.arguments = '{"query": "python"}'

        mock_response = MagicMock()
        mock_response.output = [func_call]
        mock_response.status = "completed"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Search for python")],
                    session_id=_SESSION_ID,
                )

        assert result.finish_reason == FinishReason.TOOL_USE

    @pytest.mark.asyncio
    async def test_send_with_usage_tokens(self):
        provider = _make_provider()

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_response.usage.input_tokens_details = MagicMock()
        mock_response.usage.input_tokens_details.cached_tokens = 10

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50
        assert result.usage.cache_read_tokens == 10

    @pytest.mark.asyncio
    async def test_send_with_failed_status(self):
        provider = _make_provider()

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "failed"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        assert result.finish_reason == FinishReason.ERROR

    @pytest.mark.asyncio
    async def test_send_with_incomplete_status(self):
        provider = _make_provider()

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "incomplete"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        assert result.finish_reason == FinishReason.MAX_TOKENS

    @pytest.mark.asyncio
    async def test_send_with_unknown_status(self):
        provider = _make_provider()

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "some_unknown_status"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        assert result.finish_reason == FinishReason.UNKNOWN

    @pytest.mark.asyncio
    async def test_send_filters_system_messages_from_user_messages(self):
        """System messages should be used as instructions, not sent as user messages."""
        provider = _make_provider()

        system_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[TextContent(text="Be helpful")],
        )

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = None

        captured_params = {}

        async def capture_create(**kwargs):
            captured_params.update(kwargs)
            return mock_response

        with patch.object(provider.client.responses, "create", new=capture_create):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                await provider.send(
                    messages=[system_msg, _make_user_message("Hello")],
                    session_id=_SESSION_ID,
                )

        # The input should not contain system role messages
        input_msgs = captured_params.get("input", [])
        system_msgs = [m for m in input_msgs if isinstance(m, dict) and m.get("role") == "system"]
        assert len(system_msgs) == 0
        assert "Be helpful" in captured_params["instructions"]

    @pytest.mark.asyncio
    async def test_send_codex_reasoning_uses_stateless_contract(self):
        provider = _make_provider(
            _make_llm_config(
                model="gpt-5",
                base_url="https://chatgpt.com/backend-api/codex",
            )
        )
        assistant_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[TextContent(text="previous response")],
            provider_metadata={"OpenAI": {"response_id": "resp_abc123"}},
        )
        system_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[TextContent(text="Be helpful")],
        )

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = None

        captured_params = {}

        async def capture_create(**kwargs):
            captured_params.update(kwargs)
            return mock_response

        with patch.object(provider.client.responses, "create", new=capture_create):
            await provider.send(
                messages=[
                    system_msg,
                    _make_user_message("Hello"),
                    assistant_msg,
                    _make_user_message("Next"),
                ],
                session_id=_SESSION_ID,
                provider_options={"openai": {"max_output_tokens": 1024}},
            )

        assert captured_params["store"] is False
        assert "reasoning.encrypted_content" in captured_params["include"]
        assert "previous_response_id" not in captured_params
        assert "max_output_tokens" not in captured_params
        assert "Be helpful" in captured_params["instructions"]
        input_msgs = captured_params["input"]
        assert all(msg.get("role") != "system" for msg in input_msgs if isinstance(msg, dict))

    @pytest.mark.asyncio
    async def test_send_accepts_provider_options_keyword(self):
        provider = _make_provider()

        mock_response = MagicMock()
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = None

        with patch.object(
            provider.client.responses, "create", new=AsyncMock(return_value=mock_response)
        ):
            with patch(
                "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
                new=AsyncMock(return_value=_make_empty_container_file()),
            ):
                result = await provider.send(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                    provider_options={"openai": {"reasoning": {"effort": "high"}}},
                )

        assert result.finish_reason == FinishReason.END_TURN


# ---------------------------------------------------------------------------
# OpenAIProvider.stream() - event types coverage
# ---------------------------------------------------------------------------


class TestOpenAIProviderStreamDeep:
    """Deep tests for stream() event handling."""

    def _make_streaming_provider(self):
        provider = _make_provider()
        return provider

    def _mock_stream_events(self, events):
        """Create an async context manager mock that yields events."""

        async def async_gen():
            for e in events:
                yield e

        ctx_mock = MagicMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=async_gen())
        ctx_mock.__aexit__ = AsyncMock(return_value=None)
        return ctx_mock

    @pytest.mark.asyncio
    async def test_stream_text_delta_event(self):
        """Test that text delta events are properly emitted."""

        provider = self._make_streaming_provider()
        from openai.types.responses import ResponseTextDeltaEvent

        mock_text_delta = ResponseTextDeltaEvent(
            content_index=0,
            delta="Hello",
            item_id="item_123",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        )

        async def fake_stream():
            yield mock_text_delta

        with patch(
            "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
            new=AsyncMock(return_value=_make_empty_container_file()),
        ):
            with patch.object(
                provider.client.responses,
                "create",
                new=AsyncMock(return_value=fake_stream()),
            ):
                events = []
                async for event in provider.stream(
                    messages=[_make_user_message("Hello")],
                    session_id=_SESSION_ID,
                ):
                    events.append(event)

        assert events

    @pytest.mark.asyncio
    async def test_stream_previous_response_id_extracted(self):
        """Test that previous_response_id is extracted from last assistant message."""
        provider = self._make_streaming_provider()

        asst_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[TextContent(text="previous response")],
            provider_metadata={"OpenAI": {"response_id": "resp_abc123"}},
        )

        captured_params = {}

        async def fake_create(**kwargs):
            captured_params.update(kwargs)
            # Build a minimal response to avoid exceptions
            raise RuntimeError("stop early")

        with patch(
            "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
            new=AsyncMock(return_value=_make_empty_container_file()),
        ):
            with patch.object(provider.client.responses, "create", new=fake_create):
                with pytest.raises(RuntimeError, match="stop early"):
                    async for _ in provider.stream(
                        messages=[
                            _make_user_message("Hello"),
                            asst_msg,
                            _make_user_message("Next"),
                        ],
                        session_id=_SESSION_ID,
                    ):
                        pass

        assert captured_params["previous_response_id"] == "resp_abc123"

    @pytest.mark.asyncio
    async def test_stream_codex_reasoning_uses_stateless_contract(self):
        provider = _make_provider(
            _make_llm_config(
                model="gpt-5",
                base_url="https://chatgpt.com/backend-api/codex",
            )
        )
        assistant_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[TextContent(text="previous response")],
            provider_metadata={"OpenAI": {"response_id": "resp_abc123"}},
        )
        system_msg = Message(
            id=uuid.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[TextContent(text="Be helpful")],
        )
        captured_params = {}

        async def fake_stream():
            if False:
                yield None

        async def capture_create(**kwargs):
            captured_params.update(kwargs)
            return fake_stream()

        with patch(
            "ii_agent.chat.llm.openai.OpenAIProvider._get_files_within_session",
            new=AsyncMock(return_value=_make_empty_container_file()),
        ):
            with patch.object(provider.client.responses, "create", new=capture_create):
                async for _ in provider.stream(
                    messages=[
                        system_msg,
                        _make_user_message("Hello"),
                        assistant_msg,
                        _make_user_message("Next"),
                    ],
                    session_id=_SESSION_ID,
                    provider_options={"openai": {"max_output_tokens": 1024}},
                ):
                    pass

        assert captured_params["store"] is False
        assert "reasoning.encrypted_content" in captured_params["include"]
        assert "previous_response_id" not in captured_params
        assert "max_output_tokens" not in captured_params
        assert "Be helpful" in captured_params["instructions"]
        input_msgs = captured_params["input"]
        assert all(msg.get("role") != "system" for msg in input_msgs if isinstance(msg, dict))


# ---------------------------------------------------------------------------
# _download_file_citations - edge cases
# ---------------------------------------------------------------------------


class TestDownloadFileCitationsDeep:
    """Tests for _download_file_citations edge cases."""

    @pytest.mark.asyncio
    async def test_empty_citations_returns_empty_container_file(self):
        provider = _make_provider()
        result = await provider._download_file_citations([], "session-123")

        from ii_agent.chat.llm.openai import ContainerFile

        assert isinstance(result, ContainerFile)
        assert result.files == []
        assert result.container_id is None

    @pytest.mark.asyncio
    async def test_citation_without_file_id_skipped(self):
        provider = _make_provider()

        citation = MagicMock()
        citation.file_id = None  # Missing file_id
        citation.container_id = "container_1"

        mock_session = MagicMock()
        mock_session.user_id = "user_1"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_db_ctx = MagicMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("ii_agent.chat.llm.openai.get_db_session_local", return_value=mock_db_ctx):
            result = await provider._download_file_citations([citation], "session-123")

        assert result.files == []


# ---------------------------------------------------------------------------
# ContainerFile edge cases
# ---------------------------------------------------------------------------


class TestContainerFileEdgeCases:
    """Edge case tests for ContainerFile methods."""

    def _make_file(self, content_type: str, provider_file_id: str):
        from ii_agent.chat.llm.openai import FileResponseObject

        return FileResponseObject(
            id="f1",
            provider_file_id=provider_file_id,
            provider="openai",
            content_type=content_type,
            file_name="file",
        )

    def test_mixed_content_types(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(
            container_id="c1",
            files=[
                self._make_file("text/csv", "csv-id"),
                self._make_file("image/png", "img-id"),
                self._make_file("application/pdf", "pdf-id"),
                self._make_file("text/plain", "txt-id"),
                self._make_file("application/json", "json-id"),
            ],
        )
        container_ids = cf.get_container_file_ids()
        image_ids = cf.get_image_file_ids()
        pdf_ids = cf.get_pdf_file_ids()

        assert "csv-id" in container_ids
        assert "txt-id" in container_ids
        assert "json-id" in container_ids
        assert "img-id" not in container_ids
        assert "pdf-id" not in container_ids
        assert "img-id" in image_ids
        assert "pdf-id" in pdf_ids

    def test_no_container_id(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(container_id=None, files=[])
        assert cf.container_id is None

    def test_application_pdf_excluded_from_container_files(self):
        """application/pdf should be excluded from container file IDs (endswith pdf)."""
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(container_id="c1", files=[self._make_file("application/pdf", "pdf-id")])
        assert "pdf-id" not in cf.get_container_file_ids()
        assert "pdf-id" in cf.get_pdf_file_ids()


# ---------------------------------------------------------------------------
# _get_content_type - extension edge cases
# ---------------------------------------------------------------------------


class TestGetContentTypeDeep:
    """Additional coverage for _get_content_type."""

    @pytest.mark.parametrize(
        "filename,expected_contains",
        [
            ("report.tex", "tex"),
            ("document.doc", "msword"),
            ("code.js", "javascript"),
            ("Code.JS", "javascript"),
            ("MY_FILE.PY", "python"),
        ],
    )
    def test_extensions(self, filename, expected_contains):
        provider = _make_provider()
        result = provider._get_content_type(filename)
        assert expected_contains.lower() in result.lower()

    def test_file_without_extension(self):
        provider = _make_provider()
        result = provider._get_content_type("Makefile")
        assert result == "text/plain"

    def test_filename_with_multiple_dots(self):
        provider = _make_provider()
        result = provider._get_content_type("archive.tar.gz")
        # Should default to text/plain
        assert result == "text/plain"


# ---------------------------------------------------------------------------
# OpenAIResponseParams edge cases
# ---------------------------------------------------------------------------


class TestOpenAIResponseParamsDeep:
    def test_all_optional_fields_none_excluded(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4", input="hi")
        d = params.to_dict(exclude_none=True)
        assert "instructions" not in d
        assert "tools" not in d
        assert "temperature" not in d
        assert "reasoning" not in d
        assert "store" not in d
        assert "include" not in d
        assert "previous_response_id" not in d

    def test_reasoning_field_included(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4", input="hi", reasoning={"effort": "high"})
        d = params.to_dict()
        assert d["reasoning"] == {"effort": "high"}

    def test_previous_response_id_included(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4", input="hi", previous_response_id="resp_123")
        d = params.to_dict()
        assert d["previous_response_id"] == "resp_123"

    def test_max_output_tokens_included(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4", input="hi", max_output_tokens=500)
        d = params.to_dict()
        assert d["max_output_tokens"] == 500


# ---------------------------------------------------------------------------
# OpenAIProvider model() method
# ---------------------------------------------------------------------------


class TestOpenAIProviderModel:
    def test_model_method_returns_dict(self):
        provider = _make_provider(_make_llm_config(model="gpt-4o-mini"))
        result = provider.model()
        assert result["id"] == "gpt-4o-mini"
        assert result["name"] == "gpt-4o-mini"
