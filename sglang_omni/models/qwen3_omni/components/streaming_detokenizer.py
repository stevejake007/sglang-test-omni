# SPDX-License-Identifier: Apache-2.0
"""Qwen3-Omni decode-stage result builder on the shared streaming detokenizer."""

from __future__ import annotations

from typing import Any

from transformers import AutoTokenizer

from sglang_omni.models.qwen3_omni.merge import decode_events
from sglang_omni.models.qwen3_omni.payload_types import (
    Qwen3OmniEvent,
    Qwen3OmniPipelineState,
)
from sglang_omni.proto import StagePayload
from sglang_omni.scheduling.streaming_detokenizer import (
    StreamingDetokenizeScheduler as SharedStreamingDetokenizeScheduler,
)
from sglang_omni.scheduling.streaming_detokenizer import (
    Tokenizer,
    prompt_token_count,
    thinker_output,
)


def event_to_dict(event: Qwen3OmniEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "modality": event.modality,
        "payload": dict(event.payload),
        "is_final": bool(event.is_final),
    }


def build_decode_result(
    payload: StagePayload,
    *,
    tokenizer: Tokenizer,
    eos_token_id: int | None,
    is_streaming: bool,
) -> dict[str, Any]:
    state = Qwen3OmniPipelineState.from_dict(payload.data)
    thinker_out = thinker_output(state)
    step = int(thinker_out.get("step") or len(thinker_out.get("output_ids", [])))
    events = list(
        decode_events(
            thinker_out=thinker_out,
            state=state,
            tokenizer=tokenizer,
            eos_token_id=eos_token_id,
            step=step,
        )
    )
    result: dict[str, Any] = {"events": [event_to_dict(event) for event in events]}
    final_event = next(
        (
            event
            for event in reversed(events)
            if event.is_final or event.type in {"text_final", "final"}
        ),
        None,
    )
    if final_event is not None:
        result.update(final_event.payload)
        result.setdefault("modality", final_event.modality)
    if is_streaming:
        result.pop("text", None)
    elif "text" not in result:
        output_ids = thinker_out.get("output_ids")
        if isinstance(output_ids, list) and output_ids:
            result["text"] = tokenizer.decode(output_ids, skip_special_tokens=True)
            result.setdefault("modality", "text")
    for key in ("finish_reason", "output_token_logprobs", "weight_version"):
        value = thinker_out.get(key)
        if value is not None:
            result.setdefault(key, value)
    completion_ids = thinker_out.get("output_ids") or []
    prompt_tokens = prompt_token_count(state)
    result.setdefault(
        "usage",
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": len(completion_ids),
            "total_tokens": prompt_tokens + len(completion_ids),
        },
    )
    return result


class StreamingDetokenizeScheduler(SharedStreamingDetokenizeScheduler):
    """Shared scheduler bound to Qwen3-Omni decode_events."""

    def __init__(
        self,
        tokenizer: Tokenizer,
        eos_token_id: int | None,
        *,
        stage_name: str = "decode",
    ) -> None:
        super().__init__(
            tokenizer,
            eos_token_id,
            stage_name=stage_name,
            build_result=lambda payload, is_streaming: build_decode_result(
                payload,
                tokenizer=tokenizer,
                eos_token_id=eos_token_id,
                is_streaming=is_streaming,
            ),
        )


def create_streaming_detokenize_scheduler(
    model_path: str,
    *,
    stage_name: str = "decode",
) -> StreamingDetokenizeScheduler:
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    return StreamingDetokenizeScheduler(
        tokenizer=tokenizer,
        eos_token_id=tokenizer.eos_token_id,
        stage_name=stage_name,
    )
