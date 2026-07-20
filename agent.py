import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Awaitable[str] | str]


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


async def _run_tool(tool: AgentTool, arguments: dict[str, Any]) -> str:
    result = tool.handler(arguments)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


async def run_agent_loop(
    client,
    history: list[dict[str, Any]],
    user_message: str,
    tools: list[AgentTool],
    model: str = "qwen/qwen3.6-27b",
    max_steps: int = 6,
    temperature: float = 0.3,
    fallback_models: list[str] | None = None,
) -> dict[str, Any]:
    if fallback_models is None:
        fallback_models = ["meta-llama/llama-4-scout-17b-16e-instruct", "codex/gpt-5.2"]
    model_chain = [model] + [m for m in fallback_models if m != model]

    tool_map = {tool.name: tool for tool in tools}
    from datetime import datetime
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_message = {"role": "system", "content": f"Aktuelles Datum und Uhrzeit: {current_datetime}."}
    messages = [system_message] + list(history)
    messages.append({"role": "user", "content": user_message})
    used_tools: list[str] = []

    for _ in range(max_steps):
        completion = None
        message = None
        for chain_index, current_model in enumerate(model_chain):
            try:
                completion = client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    tools=[tool.schema() for tool in tools] or None,
                    tool_choice="auto" if tools else None,
                    temperature=temperature,
                    max_tokens=1200,
                    top_p=0.95,
                    stream=False,
                )
                message = completion.choices[0].message
                if chain_index > 0:
                    logger.info("✅ Agent-Fallback auf %s erfolgreich", current_model)
                break
            except Exception as tool_exc:
                if "tool calling" in str(tool_exc).lower() or "not supported" in str(tool_exc).lower():
                    logger.info("Tool calling unsupported for %s, falling back to text-only mode", current_model)
                    try:
                        completion = client.chat.completions.create(
                            model=current_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=1200,
                            top_p=0.95,
                            stream=False,
                        )
                        message = completion.choices[0].message
                        break
                    except Exception as text_exc:
                        logger.warning("Agent-Modell %s fehlgeschlagen (text-only): %s", current_model, text_exc)
                        continue
                else:
                    logger.warning("Agent-Modell %s fehlgeschlagen: %s", current_model, tool_exc)
                    continue

        if message is None:
            return {
                "success": False,
                "content": "Der Agent konnte kein Modell erreichen (alle Fallbacks fehlgeschlagen).",
                "used_tools": used_tools,
                "steps": len(used_tools),
            }

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            assistant_payload = {"role": "assistant", "content": message.content or ""}
            assistant_payload["tool_calls"] = []

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    arguments = {}

                assistant_payload["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )
            messages.append(assistant_payload)

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                tool = tool_map.get(function_name)
                if not tool:
                    tool_result = f"Tool {function_name} ist nicht registriert."
                else:
                    try:
                        arguments = json.loads(tool_call.function.arguments or "{}")
                    except Exception:
                        arguments = {}
                    try:
                        tool_result = await _run_tool(tool, arguments)
                        used_tools.append(function_name)
                    except Exception as exc:
                        logger.exception("Agent-Tool %s fehlgeschlagen", function_name)
                        tool_result = f"Tool {function_name} ist fehlgeschlagen: {str(exc)[:220]}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": tool_result,
                    }
                )
            continue

        final_text = (message.content or "").strip()
        return {
            "success": bool(final_text),
            "content": final_text or "Der Agent hatte gerade keinen finalen Output.",
            "used_tools": used_tools,
            "steps": len(used_tools),
        }

    return {
        "success": False,
        "content": "Der Agent hat sein Schritt-Limit erreicht, ohne sauber abzuschliessen.",
        "used_tools": used_tools,
        "steps": len(used_tools),
    }
