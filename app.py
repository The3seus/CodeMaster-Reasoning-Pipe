"""
title: CodeMaster Reasoning Pipe
author: Sam Paniagua
version: 0.0.2
"""

import json
from time import time
from pydantic import BaseModel, Field
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Awaitable, Any, AsyncGenerator
import asyncio
from fastapi import Request
from open_webui.utils.misc import get_last_user_message
from open_webui.routers.ollama import generate_chat_completion as ollama_chat_completion
from open_webui.routers.openai import generate_chat_completion as openai_chat_completion
import logging

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.set_name("codemaster_reasoning_pipe")
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False


@dataclass
class User:
    id: str
    email: str
    name: str
    role: str


class Pipe:
    class Valves(BaseModel):
        REASONING_MODEL: str = Field(
            default="your_reasoning_model_id_here",
            description="Model used for initial reasoning and chain-of-thought steps.",
        )
        USE_OPENAI_API_REASONING_MODEL: bool = Field(
            default=False,
            description="Use OpenAI API for reasoning model if True, Ollama if False.",
        )
        RESPONDING_MODEL: str = Field(
            default="your_responding_model_id_here",
            description="Model used for final response generation.",
        )
        USE_OPENAI_API_RESPONDING_MODEL: bool = Field(
            default=False,
            description="Use OpenAI API for responding model if True, Ollama if False.",
        )
        ENABLE_SHOW_REASONING_TRACE: bool = Field(
            default=False, description="Toggle visibility of reasoning trace."
        )
        MAX_REASONING_TIME: int = Field(
            default=120, description="Maximum time in seconds for reasoning steps."
        )
        COT_ITERATIONS: int = Field(
            default=3,
            description="Number of chain-of-thought iterations for refining reasoning.",
        )

    def __init__(self):
        self.type = "manifold"
        self.valves = self.Valves()
        self.total_reasoning_tokens = 0
        self.max_reasoning_time_reached = False
        self.__user__ = None
        self._json_buffer = ""

    def pipes(self):
        name = "codemaster-"
        for model in self.valves.REASONING_MODEL.split(","):
            name += model.strip().split(":")[0] + "-"
        name = name[:-1] + "-to-" + self.valves.RESPONDING_MODEL.strip().split(":")[0]
        return [{"name": name, "id": name}]

    def get_chunk_content(self, chunk: bytes):
        self._json_buffer += chunk.decode("utf-8")
        while True:
            newline_index = self._json_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._json_buffer[:newline_index].strip()
            self._json_buffer = self._json_buffer[newline_index + 1 :]
            if not line:
                continue
            try:
                chunk_data = json.loads(line)
                if "message" in chunk_data and "content" in chunk_data["message"]:
                    yield chunk_data["message"]["content"]
                if chunk_data.get("done", False):
                    break
            except json.JSONDecodeError as e:
                logger.error(f'ChunkDecodeError: unable to parse "{line[:100]}": {e}')
                self._json_buffer = line + "\n" + self._json_buffer
                break

    async def get_response(
        self, model: str, messages: List[Dict[str, str]], reasoning: bool, stream: bool
    ):
        use_openai_api = (
            self.valves.USE_OPENAI_API_REASONING_MODEL
            if reasoning
            else self.valves.USE_OPENAI_API_RESPONDING_MODEL
        )
        generate_completion = (
            openai_chat_completion if use_openai_api else ollama_chat_completion
        )
        response = await generate_completion(
            self.__request__,
            {"model": model, "messages": messages, "stream": stream},
            user=self.__user__,
        )
        return response

    async def get_completion(
        self,
        model: str,
        messages: list,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ):
        response = None
        try:
            reasoning = False
            stream = False
            response = await self.get_response(model, messages, reasoning, stream)
            if not response:
                return "**No content available**"
            if "choices" in response and response["choices"]:
                return response["choices"][0]["message"]["content"]
            if "message" in response and "content" in response["message"]:
                return response["message"]["content"]
            return "**No content available**"
        except Exception as e:
            await self.set_status_end(
                f"Error: Is {model} a valid model? ({e})", __event_emitter__
            )
        finally:
            if response and hasattr(response, "close"):
                await response.close()

    async def stream_response(
        self,
        model: str,
        messages: List[Dict[str, str]],
        reasoning: bool,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> AsyncGenerator[str, None]:
        start_time = time()
        try:
            stream = True
            response = await self.get_response(model, messages, reasoning, stream)
            while True:
                chunk = await response.body_iterator.read(1024)
                if not chunk:
                    break
                for part in self.get_chunk_content(chunk):
                    yield part
                if reasoning and (time() - start_time > self.valves.MAX_REASONING_TIME):
                    logger.info(f'Max reasoning time reached for model "{model}"')
                    self.max_reasoning_time_reached = True
                    break
            if self.max_reasoning_time_reached:
                await response.close()
                return
        except Exception as e:
            api = (
                "OpenAI"
                if (reasoning and self.valves.USE_OPENAI_API_REASONING_MODEL)
                else "Ollama"
            )
            category = "Reasoning" if reasoning else "Responding"
            await self.set_status_end(
                f"{category} Error: Invalid model {model} in {api} API ({e})",
                __event_emitter__,
            )
        finally:
            if response and hasattr(response, "close"):
                await response.close()

    async def run_step(
        self,
        model: str,
        messages: list,
        prompt: str,
        reasoning: bool,
        step_name: str,
        title_name: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        messages = json.loads(json.dumps(messages))
        messages[-1] = {"role": "user", "content": prompt}
        await self.send_data(f"\n### {title_name}\n", reasoning, __event_emitter__)
        response_text = ""
        num_tokens = 0
        async for chunk in self.stream_response(
            model.strip(), messages, reasoning, __event_emitter__
        ):
            response_text += chunk
            num_tokens += 1
            await self.send_data(chunk, reasoning, __event_emitter__)
            await self.set_status(
                f"{step_name} ({num_tokens} tokens)", __event_emitter__
            )
        if reasoning:
            self.total_reasoning_tokens += num_tokens
        return response_text.strip()

    async def run_initial_reasoning(
        self,
        model: str,
        messages: list,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        prompt = """You are an expert in reasoning and problem-solving. Analyze the following query and break it down into smaller, manageable parts. For coding tasks, consider the problem requirements, necessary functions, and overall structure. For general tasks, identify the key components and logical steps needed to address the query.

User Query:
{query}

Provide your initial reasoning in the following format:
<reasoning>
Step 1: Query Breakdown
[Break down the query into smaller parts or steps]

Step 2: Key Components
[Identify the key concepts, functions, or elements required]

Step 3: Approach Outline
[Outline a high-level approach or plan to solve the query]
</reasoning>
""".format(
            query=query
        )
        reasoning = await self.run_step(
            model,
            messages,
            prompt,
            True,
            "Initial Reasoning",
            "Initial Reasoning",
            __event_emitter__,
        )
        await self.set_status("Completed initial reasoning", __event_emitter__)
        await asyncio.sleep(0.2)
        return reasoning

    async def run_chain_of_thought(
        self,
        model: str,
        messages: list,
        initial_reasoning: str,
        query: str,
        iterations: int,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> List[str]:
        reasoning_chain = [initial_reasoning]
        for i in range(iterations):
            previous_iterations = "\n".join(reasoning_chain)
            prompt = (
                """You are refining your reasoning through a chain-of-thought process. Based on all previous iterations, improve your approach by considering alternative methods, potential edge cases, and enhancements in logic or efficiency.

Previous Iterations:
"""
                + previous_iterations
                + """

User Query:
{query}

Provide the following for this iteration:
<chain-of-thought>
Iteration {iteration}:
- Refinement: [Describe how you're improving the approach]
- Considerations: [Note any edge cases, optimizations, or alternative solutions]
- Updated Plan: [Provide the updated plan or pseudocode]
</chain-of-thought>
""".format(
                    query=query, iteration=i + 1
                )
            )
            iteration_output = await self.run_step(
                model,
                messages,
                prompt,
                True,
                f"Chain-of-Thought Iteration {i+1}",
                f"Iteration {i+1}",
                __event_emitter__,
            )
            reasoning_chain.append(iteration_output)
            await self.set_status(
                f"Completed chain-of-thought iteration {i+1}", __event_emitter__
            )
            await asyncio.sleep(0.2)
        return reasoning_chain

    async def run_final_response(
        self,
        messages: list,
        query: str,
        reasoning_chains: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        await self.set_status("Generating final response...", __event_emitter__)
        prompt = f"""You are tasked with generating a final response based on the following reasoning history.

Reasoning History:
{reasoning_chains}

User Query:
{query}

Follow these steps:
1. Review the reasoning history and extract the key insights or solutions.
2. For coding tasks, generate the final code based on the most refined plan.
3. For general tasks, formulate a concise and logical answer.
4. Ensure the response is complete, accurate, and directly addresses the query.

Provide only the final response or code.
"""
        response_text = await self.run_step(
            self.valves.RESPONDING_MODEL.strip(),
            messages,
            prompt,
            False,
            "Generating final response",
            "Final Response",
            __event_emitter__,
        )
        await asyncio.sleep(0.2)
        return response_text

    async def pipe(
        self,
        body: dict,
        __user__: dict,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]],
        __request__: Request,
        __task__=None,
    ) -> str:
        self.__user__ = User(**__user__)
        self.__request__ = __request__
        messages = body["messages"]
        query = get_last_user_message(messages)
        if __task__ is None:
            start_time = time()
            models = self.valves.REASONING_MODEL.split(",")
            initial_reasonings = [
                await self.run_initial_reasoning(
                    models[i], messages, query, __event_emitter__
                )
                for i in range(len(models))
            ]
            reasoning_chains = [
                await self.run_chain_of_thought(
                    models[i],
                    messages,
                    initial_reasonings[i],
                    query,
                    self.valves.COT_ITERATIONS,
                    __event_emitter__,
                )
                for i in range(len(models))
            ]
            all_reasoning = "\n\n".join(
                ["\n".join(chain) for chain in reasoning_chains]
            )
            final_response = await self.run_final_response(
                messages, query, all_reasoning, __event_emitter__
            )
            total_duration = int(time() - start_time)
            status_msg = (
                f"Reasoned with {self.total_reasoning_tokens} tokens in max time {total_duration}s"
                if self.max_reasoning_time_reached
                else f"Reasoned with {self.total_reasoning_tokens} tokens in {total_duration}s"
            )
            await self.set_status_end(status_msg, __event_emitter__)
            return final_response
        else:
            return await self.get_completion(
                self.valves.RESPONDING_MODEL.strip(), messages, __event_emitter__
            )

    async def set_status(
        self,
        description: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ):
        await __event_emitter__(
            {"type": "status", "data": {"description": description, "done": False}}
        )

    async def send_data(
        self,
        data: str,
        reasoning: bool,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ):
        if not reasoning or self.valves.ENABLE_SHOW_REASONING_TRACE:
            await __event_emitter__(
                {
                    "type": "message",
                    "data": {
                        "content": data,
                        "role": "assistant-reasoning" if reasoning else "assistant",
                    },
                }
            )

    async def set_status_end(
        self,
        data: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ):
        await __event_emitter__(
            {"type": "status", "data": {"description": data, "done": True}}
        )
