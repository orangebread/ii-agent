"""Unit tests for ii_agent.chat.llm.openai (OpenAIProvider)."""

from __future__ import annotations

import json
import uuid as _uuid_mod
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from ii_agent.core.config.llm_config import LLMConfig
from ii_agent.chat.types import (
    ArrayResultContent,
    BinaryContent,
    ErrorJsonContent,
    ErrorTextContent,
    ExecutionDeniedContent,
    FileDataContentPart,
    ImageDataContentPart,
    ImageUrlContentPart,
    JsonResultContent,
    Message,
    MessageRole,
    StorybookProgressContent,
    StorybookResultContent,
    TextContent,
    TextContentPart,
    TextResultContent,
    ToolCall,
    ToolResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_config(
    model: str = "gpt-4o",
    api_key: str = "test-key",
    azure_endpoint: Optional[str] = None,
    azure_api_version: Optional[str] = None,
    base_url: Optional[str] = None,
    runtime_product: Optional[str] = None,
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
    if runtime_product is not None:
        kwargs["runtime_product"] = runtime_product
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


class TestLLMProviderFactoryCodex:
    def test_openai_codex_runtime_uses_codex_provider(self):
        from ii_agent.chat.llm.factory import LLMProviderFactory
        from ii_agent.chat.llm.openai import CodexProvider

        provider_class = LLMProviderFactory._resolve_provider_class(
            _make_llm_config(
                model="gpt-5.4",
                base_url="https://chatgpt.com/backend-api/codex",
                runtime_product="codex",
            )
        )

        assert provider_class is CodexProvider

    def test_standard_openai_runtime_uses_openai_provider(self):
        from ii_agent.chat.llm.factory import LLMProviderFactory
        from ii_agent.chat.llm.openai import OpenAIProvider

        provider_class = LLMProviderFactory._resolve_provider_class(_make_llm_config())

        assert provider_class is OpenAIProvider


_SESSION_ID = "00000000-0000-4000-8000-000000000123"
_MSG_ID = _uuid_mod.uuid4()


def _make_user_message(text: str = "Hello", file_ids: List[str] = None) -> Message:
    return Message(
        id=_uuid_mod.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.USER,
        parts=[TextContent(text=text)],
        file_ids=file_ids,
    )


def _make_assistant_message(text: str = "Hi") -> Message:
    return Message(
        id=_uuid_mod.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.ASSISTANT,
        parts=[TextContent(text=text)],
    )


def _make_tool_result_message(tool_call_id: str = "c1", name: str = "tool", output=None) -> Message:
    if output is None:
        output = TextResultContent(value="result")
    return Message(
        id=_uuid_mod.uuid4(),
        session_id=_SESSION_ID,
        role=MessageRole.TOOL,
        parts=[ToolResult(tool_call_id=tool_call_id, name=name, output=output)],
    )


def _make_empty_container_file():
    from ii_agent.chat.llm.openai import ContainerFile

    return ContainerFile(container_id=None, files=[])


# ---------------------------------------------------------------------------
# OpenAIResponseParams
# ---------------------------------------------------------------------------


class TestOpenAIResponseParams:
    def test_required_fields(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4o", input="Hello")
        assert params.model == "gpt-4o"
        assert params.input == "Hello"

    def test_to_dict_excludes_none_by_default(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4o", input="Hello")
        d = params.to_dict()
        assert "instructions" not in d or d.get("instructions") is None

    def test_to_dict_includes_none_when_flag_false(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4o", input="Hello")
        d = params.to_dict(exclude_none=False)
        assert "instructions" in d

    def test_stream_default_false(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4o", input="Hello")
        assert params.stream is False

    def test_extra_fields_allowed(self):
        from ii_agent.chat.llm.openai import OpenAIResponseParams

        params = OpenAIResponseParams(model="gpt-4o", input="Hi", extra_param="val")
        assert params.model_extra.get("extra_param") == "val"


# ---------------------------------------------------------------------------
# FileResponseObject
# ---------------------------------------------------------------------------


class TestFileResponseObject:
    def test_valid_object(self):
        from ii_agent.chat.llm.openai import FileResponseObject

        obj = FileResponseObject(
            id="file-1",
            provider_file_id="prov-1",
            provider="openai",
            content_type="image/png",
            file_name="photo.png",
        )
        assert obj.provider == "openai"
        assert obj.file_size == 0

    def test_anthropic_provider_also_valid(self):
        from ii_agent.chat.llm.openai import FileResponseObject

        obj = FileResponseObject(
            id="f1",
            provider_file_id="p1",
            provider="anthropic",
            content_type="text/plain",
            file_name="file.txt",
        )
        assert obj.provider == "anthropic"


# ---------------------------------------------------------------------------
# ContainerFile
# ---------------------------------------------------------------------------


class TestContainerFile:
    def _make_file(self, content_type: str, provider_file_id: str):
        from ii_agent.chat.llm.openai import FileResponseObject

        return FileResponseObject(
            id="f1",
            provider_file_id=provider_file_id,
            provider="openai",
            content_type=content_type,
            file_name="file",
        )

    def test_get_container_file_ids_excludes_images_and_pdfs(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(
            container_id="c1",
            files=[
                self._make_file("text/csv", "csv-id"),
                self._make_file("image/png", "img-id"),
                self._make_file("application/pdf", "pdf-id"),
            ],
        )
        result = cf.get_container_file_ids()
        assert "csv-id" in result
        assert "img-id" not in result
        assert "pdf-id" not in result

    def test_get_image_file_ids(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(
            container_id="c1",
            files=[
                self._make_file("image/jpeg", "jpg-id"),
                self._make_file("text/plain", "txt-id"),
            ],
        )
        result = cf.get_image_file_ids()
        assert "jpg-id" in result
        assert "txt-id" not in result

    def test_get_pdf_file_ids(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(
            container_id="c1",
            files=[
                self._make_file("application/pdf", "pdf-id"),
                self._make_file("text/plain", "txt-id"),
            ],
        )
        result = cf.get_pdf_file_ids()
        assert "pdf-id" in result
        assert "txt-id" not in result

    def test_empty_files_returns_empty_lists(self):
        from ii_agent.chat.llm.openai import ContainerFile

        cf = ContainerFile(container_id=None, files=[])
        assert cf.get_container_file_ids() == []
        assert cf.get_image_file_ids() == []
        assert cf.get_pdf_file_ids() == []


# ---------------------------------------------------------------------------
# OpenAIProvider initialization
# ---------------------------------------------------------------------------


class TestOpenAIProviderInit:
    def test_standard_init(self):
        from ii_agent.chat.llm.openai import OpenAIProvider
        import openai

        with patch.object(openai, "AsyncOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            config = _make_llm_config()
            provider = OpenAIProvider(config)
            assert provider.model_name == "gpt-4o"
            mock_cls.assert_called_once()

    def test_azure_init_uses_azure_client(self):
        from ii_agent.chat.llm.openai import OpenAIProvider
        import openai

        with patch.object(openai, "AsyncAzureOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            config = _make_llm_config(
                azure_endpoint="https://my-resource.openai.azure.com",
                azure_api_version="2024-01-01",
            )
            OpenAIProvider(config)
            mock_cls.assert_called_once()

    def test_custom_base_url_passed_to_client(self):
        from ii_agent.chat.llm.openai import OpenAIProvider
        import openai

        with patch.object(openai, "AsyncOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            config = _make_llm_config(base_url="http://custom-api.local/v1")
            OpenAIProvider(config)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get("base_url") == "http://custom-api.local/v1"

    def test_default_base_url_is_openai(self):
        from ii_agent.chat.llm.openai import OpenAIProvider
        import openai

        with patch.object(openai, "AsyncOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            config = _make_llm_config()
            OpenAIProvider(config)
            call_kwargs = mock_cls.call_args[1]
            assert "openai.com" in call_kwargs.get("base_url", "")


# ---------------------------------------------------------------------------
# _get_content_type
# ---------------------------------------------------------------------------


class TestGetContentType:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("photo.png", "image/png"),
            ("image.jpg", "image/jpeg"),
            ("image.jpeg", "image/jpeg"),
            ("animation.gif", "image/gif"),
            ("preview.webp", "image/webp"),
            ("script.py", "text/x-python"),
            ("data.json", "application/json"),
            ("doc.pdf", "application/pdf"),
            ("readme.txt", "text/plain"),
            ("doc.md", "text/markdown"),
            ("file.css", "text/css"),
            ("page.html", "text/html"),
            ("code.ts", "application/typescript"),
            (
                "report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (
                "slides.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
            ("script.sh", "application/x-sh"),
            ("code.go", "text/x-golang"),
            ("code.java", "text/x-java"),
            ("code.rb", "text/x-ruby"),
            ("code.php", "text/x-php"),
            ("code.cs", "text/x-csharp"),
            ("code.cpp", "text/x-c++"),
            ("code.c", "text/x-c"),
            ("unknown.xyz", "text/plain"),
        ],
    )
    def test_content_type_mapping(self, filename, expected):
        provider = _make_provider()
        result = provider._get_content_type(filename)
        assert result == expected

    def test_uppercase_filename_handled(self):
        provider = _make_provider()
        result = provider._get_content_type("IMAGE.PNG")
        assert result == "image/png"

    def test_mixed_case_extension(self):
        provider = _make_provider()
        result = provider._get_content_type("Photo.JPEG")
        assert result == "image/jpeg"


# ---------------------------------------------------------------------------
# _convert_messages - system messages
# ---------------------------------------------------------------------------


class TestConvertMessagesSystem:
    def test_system_message_excluded_from_input(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[TextContent(text="You are helpful.")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result == []

    def test_extract_system_instructions_returns_joined_text(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[TextContent(text="You are helpful.")],
        )
        assert provider._extract_system_instructions([msg]) == "You are helpful."

    def test_system_message_without_text_skipped(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.SYSTEM,
            parts=[],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result == []


# ---------------------------------------------------------------------------
# _convert_messages - user messages
# ---------------------------------------------------------------------------


class TestConvertMessagesUser:
    def test_text_content_converted(self):
        provider = _make_provider()
        msg = _make_user_message("Hello world")
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "input_text"
        assert result[0]["content"][0]["text"] == "Hello world"

    def test_binary_image_converted_to_input_image(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[
                BinaryContent(data=b"\xff\xd8\xff", mime_type="image/jpeg", path="/tmp/img.jpg")
            ],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        content = result[0]["content"]
        assert content[0]["type"] == "input_image"
        assert content[0]["image_url"].startswith("data:image")

    def test_binary_pdf_converted_to_input_file(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[BinaryContent(data=b"%PDF", mime_type="application/pdf", path="/tmp/file.pdf")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        content = result[0]["content"]
        assert content[0]["type"] == "input_file"

    def test_unsupported_binary_type_skipped(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[BinaryContent(data=b"data", mime_type="application/zip", path="/tmp/file.zip")],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        # No content added for unsupported types, so message skipped
        assert result == []

    def test_empty_parts_skipped(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.USER,
            parts=[],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result == []


# ---------------------------------------------------------------------------
# _convert_messages - assistant messages
# ---------------------------------------------------------------------------


class TestConvertMessagesAssistant:
    def test_text_content_converted(self):
        provider = _make_provider()
        msg = _make_assistant_message("I can help!")
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert any(m["role"] == "assistant" for m in result)
        asst = next(m for m in result if m["role"] == "assistant")
        assert asst["content"][0]["text"] == "I can help!"

    def test_tool_call_converted_to_function_call(self):
        provider = _make_provider()
        tc = ToolCall(id="call_123", name="web_search", input='{"q": "test"}', finished=True)
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[tc],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        func_calls = [m for m in result if m.get("type") == "function_call"]
        assert len(func_calls) == 1
        assert func_calls[0]["name"] == "web_search"
        assert func_calls[0]["call_id"] == "call_123"

    def test_unfinished_tool_call_skipped(self):
        provider = _make_provider()
        tc = ToolCall(id="call_456", name="tool", input="{}", finished=False)
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[tc],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        func_calls = [m for m in result if m.get("type") == "function_call"]
        assert len(func_calls) == 0

    def test_no_content_no_output(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.ASSISTANT,
            parts=[],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result == []


# ---------------------------------------------------------------------------
# _convert_messages - tool result messages
# ---------------------------------------------------------------------------


class TestConvertMessagesToolResult:
    def test_text_result_content(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "search", TextResultContent(value="Search result"))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert len(result) == 1
        assert result[0]["type"] == "function_call_output"
        assert result[0]["output"] == "Search result"
        assert result[0]["call_id"] == "c1"

    def test_error_text_content(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", ErrorTextContent(value="Error!"))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"] == "Error!"

    def test_json_result_serialized(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", JsonResultContent(value={"k": "v"}))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert json.loads(result[0]["output"]) == {"k": "v"}

    def test_error_json_serialized(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", ErrorJsonContent(value={"err": True}))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert json.loads(result[0]["output"]) == {"err": True}

    def test_execution_denied_reason(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1", "tool", ExecutionDeniedContent(reason="Not permitted")
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"] == "Not permitted"

    def test_execution_denied_no_reason_fallback(self):
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", ExecutionDeniedContent(reason=None))
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"] == "Tool execution denied."

    def test_array_result_with_text_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1", "tool", ArrayResultContent(value=[TextContentPart(text="item")])
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert isinstance(result[0]["output"], list)
        assert result[0]["output"][0]["type"] == "input_text"

    def test_array_result_with_image_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(value=[ImageDataContentPart(media_type="image/png", data="base64")]),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"][0]["type"] == "input_image"

    def test_array_result_with_file_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(
                value=[
                    FileDataContentPart(
                        mime_type="application/pdf", data="pdfdata", filename="f.pdf"
                    )
                ]
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"][0]["type"] == "input_file"

    def test_array_result_with_image_url_part(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            ArrayResultContent(value=[ImageUrlContentPart(url="http://example.com/img.png")]),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert result[0]["output"][0]["type"] == "input_text"
        assert "http://example.com/img.png" in result[0]["output"][0]["text"]

    def test_storybook_progress_content(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            StorybookProgressContent(
                storybook_id="00000000-0000-4000-8000-000000000411",
                storybook_name="Book",
                total_pages=10,
                completed_pages=5,
                current_page=5,
                status="generating",  # must be one of: generating, completed, failed
                generating_pages=[],
                error_message=None,
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        data = json.loads(result[0]["output"])
        assert data["type"] == "storybook_progress"

    def test_storybook_result_content(self):
        provider = _make_provider()
        msg = _make_tool_result_message(
            "c1",
            "tool",
            StorybookResultContent(
                storybook_id="00000000-0000-4000-8000-000000000412",
                storybook_name="Book",
                pages=[],
            ),
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        data = json.loads(result[0]["output"])
        assert data["type"] == "storybook"

    def test_error_text_with_empty_value(self):
        # ErrorTextContent with empty value also produces valid output
        provider = _make_provider()
        msg = _make_tool_result_message("c1", "tool", ErrorTextContent(value=""))
        result = provider._convert_messages([msg], _make_empty_container_file())
        # Output should be present (even if empty string)
        assert result[0]["call_id"] == "c1"

    def test_multiple_tool_results_in_one_message(self):
        provider = _make_provider()
        msg = Message(
            id=_uuid_mod.uuid4(),
            session_id=_SESSION_ID,
            role=MessageRole.TOOL,
            parts=[
                ToolResult(tool_call_id="c1", name="t1", output=TextResultContent(value="r1")),
                ToolResult(tool_call_id="c2", name="t2", output=TextResultContent(value="r2")),
            ],
        )
        result = provider._convert_messages([msg], _make_empty_container_file())
        assert len(result) == 2
        assert result[0]["call_id"] == "c1"
        assert result[1]["call_id"] == "c2"


# ---------------------------------------------------------------------------
# _convert_tools
# ---------------------------------------------------------------------------


class TestConvertTools:
    def test_none_tools_returns_none(self):
        provider = _make_provider()
        result = provider._convert_tools(None, _make_empty_container_file())
        assert result is None

    def test_empty_tools_returns_empty(self):
        provider = _make_provider()
        result = provider._convert_tools([], _make_empty_container_file())
        assert result == [] or result is None

    def test_function_tool_converted(self):
        provider = _make_provider()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Searches the web",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = provider._convert_tools(tools, _make_empty_container_file())
        assert result is not None
        assert len(result) >= 1
        func_tools = [t for t in result if t.get("type") == "function"]
        assert len(func_tools) >= 1
        assert func_tools[0]["name"] == "web_search"

    def test_non_function_tool_passed_through(self):
        # Tools that already have "name" at top level are treated as already-converted
        # and are passed through as-is. This verifies the pass-through behavior.
        provider = _make_provider()
        tools = [
            {"type": "builtin", "name": "calculator"},
        ]
        result = provider._convert_tools(tools, _make_empty_container_file())
        # Non-function tools with a 'name' key are passed through unchanged
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "calculator"


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT_TEMPLATE
# ---------------------------------------------------------------------------


class TestSystemPromptTemplate:
    def test_template_has_current_date_placeholder(self):
        from ii_agent.chat.prompts.openai_system_prompt import (
            template,
        )
        from datetime import datetime

        result = template.substitute(current_date=datetime.now().strftime("%Y-%m-%d"))
        assert "2026" in result or str(datetime.now().year) in result

    def test_template_contains_chatgpt(self):
        from ii_agent.chat.prompts.openai_system_prompt import SYSTEM_PROMPT_TEMPLATE

        assert "ChatGPT" in SYSTEM_PROMPT_TEMPLATE

    def test_template_contains_tools_section(self):
        from ii_agent.chat.prompts.openai_system_prompt import SYSTEM_PROMPT_TEMPLATE

        assert "## web" in SYSTEM_PROMPT_TEMPLATE
        assert "web_search" in SYSTEM_PROMPT_TEMPLATE
