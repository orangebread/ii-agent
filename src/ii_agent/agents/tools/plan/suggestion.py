"""V1 PlanModificationSuggestionsTool for generating plan modification suggestions."""

import uuid
from typing import Any, Optional, TYPE_CHECKING

from ii_agent.agents.tools.base import BaseAgentTool, ToolResult
from ii_agent.core.logger import logger

if TYPE_CHECKING:
    from ii_agent.realtime.pubsub import AsyncIOPubSub as EventStream
    from ii_agent.sessions.schemas import SessionInfo


class PlanModificationSuggestionsTool(BaseAgentTool):
    """V1 Tool for submitting plan modification suggestions.

    This tool emits PLAN_MODIFICATION_OPTIONS event directly to the frontend
    for the custom modify plans suggestion UI (not using tool confirmation flow).
    """

    name = "submit_plan_modification_suggestions"
    description = """Submit plan modification suggestions to help the user modify their project plan.
    Use this tool when you have analyzed the current plan and generated helpful modification options.

    Call this tool ONCE with the complete suggestions including:
    - A friendly message to the user
    - A list of suggested modifications they can choose from
    """
    read_only = False
    display_name = "Submit Plan Modification Suggestions"

    # Stop agent after emitting suggestions - waiting for user selection
    stop_after_tool_call = True

    input_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "A friendly message asking the user how they'd like to modify the plan (1-2 sentences)",
            },
            "suggestions": {
                "type": "array",
                "description": "List of modification suggestions for the user to choose from",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier for this suggestion",
                        },
                        "label": {
                            "type": "string",
                            "description": "Short label for the option (5-8 words)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what this modification would do",
                        },
                        "prompt_template": {
                            "type": "string",
                            "description": "The exact text to send to regenerate the plan with this modification",
                        },
                    },
                    "required": ["id", "label", "description", "prompt_template"],
                },
                "minItems": 3,
                "maxItems": 8,
            },
        },
        "required": ["message", "suggestions"],
    }

    def __init__(
        self,
        session_id: uuid.UUID,
        run_id: uuid.UUID,
        event_stream: Optional["EventStream"] = None,
        session_info: Optional["SessionInfo"] = None,
    ):
        """Initialize the PlanModificationSuggestionsToolV1.

        Args:
            session_id: Session ID for the current session
            run_id: Current run ID for tracking this operation
            event_stream: Event stream for publishing events
            session_info: Session information object
        """
        self.session_id = session_id
        self.run_id = run_id
        self._event_stream = event_stream
        self._session_info = session_info

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        """Execute the tool to emit plan modification suggestions.

        Args:
            tool_input: Dictionary containing 'message' and 'suggestions'

        Returns:
            ToolResult with success or error message
        """
        try:
            message = tool_input.get("message", "How would you like to modify the plan?")
            suggestions = tool_input.get("suggestions", [])

            # Emit PLAN_MODIFICATION_OPTIONS event to clients
            if self._event_stream is not None:
                import uuid as _uuid
                from ii_agent.realtime.events.app_events import PlanModificationOptionsEvent

                session_uuid = (
                    _uuid.UUID(self.session_id)
                    if isinstance(self.session_id, str)
                    else self.session_id
                )
                await self._event_stream.publish(
                    PlanModificationOptionsEvent(
                        session_id=session_uuid,
                        content={
                            "message": message,
                            "suggestions": suggestions,
                        },
                    )
                )

            logger.info(
                f"Plan modification suggestions submitted successfully for session {self.session_id}"
            )
            return ToolResult(
                llm_content=f"Successfully submitted {len(suggestions)} modification suggestions. Waiting for user to select a modification option.",
                user_display_content={
                    "message": message,
                    "suggestions": suggestions,
                },
                is_error=False,
                is_interrupted=True,
            )

        except Exception as e:
            logger.error(f"Error submitting plan modification suggestions: {e}", exc_info=True)
            return ToolResult(
                llm_content=f"Error submitting suggestions: {str(e)}",
                is_error=True,
            )
