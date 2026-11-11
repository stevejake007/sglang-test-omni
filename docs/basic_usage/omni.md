# Omni Model Usage

Omni models in SGLang-Omni serve chat requests through one OpenAI-compatible
endpoint, `/v1/chat/completions`. They accept text, image, audio, and video input,
and either answer in text or answer in text and speech, depending on the output
modalities a request asks for.

This page is the shared reference for that contract: how to send media, how to ask
for speech, where text and audio come back in the response, how streaming frames
are shaped, which request fields exist, and how errors are reported. Launch
commands, pipeline layout, hardware tuning, quantized checkpoints, and extra
per-model fields stay with each model.

Examples use `qwen3-omni` as the served model name. Each model page states its own
`model` value, launch command, and any additional fields.

## Prerequisites

Install SGLang-Omni using the [installation guide](../get_started/installation.md),
then follow the page for the model you serve for its weights, launch command, and
extra dependencies. Some models need a specific example configuration or a
platform-specific recipe.

## Supported Omni Models

| Model | Input | Output | Notes |
|---|---|---|---|
| [Qwen3-Omni](qwen3_omni.md) | Text, image, audio, video | Text, or text and speech | Text-only mode or the full speech pipeline; realtime sessions |
| [Ming-Omni](../cookbook/ming_omni.md) | Text, image, audio, video | Text, or text and speech | 44.1 kHz speech; thinker and talker stages |
| [Ming-3.0-audio](../cookbook/ming3_audio.md) | Audio, with optional text | Text, or text and speech | Transcription, audio question answering, and speech synthesis |
| [MiniCPM-o](../cookbook/minicpm_o.md) | Text, image, audio, video | Text, or text and speech | Chat here; live full-duplex calls use `/v1/realtime` |

Models that only expose the realtime or session API, such as
[PersonaPlex](../cookbook/personaplex.md), take their request format from the
[full-duplex guide](../developer_reference/full_duplex_guide.md) instead of this
page.

## General Usage

A chat request carries the conversation in `messages` and the requested outputs in
`modalities`. The default is `["text"]`; adding `"audio"` asks for speech and
requires a server that runs the model's speech stages.

### Text Output

```bash
curl -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": "Summarize the plot in one sentence."}],
    "modalities": ["text"],
    "max_tokens": 128
  }'
```

The answer is in `choices[0].message.content`:

```python
import requests

response = requests.post(
    "http://localhost:8008/v1/chat/completions",
    json={
        "model": "qwen3-omni",
        "messages": [{"role": "user", "content": "Summarize the plot in one sentence."}],
        "modalities": ["text"],
        "max_tokens": 128,
    },
    timeout=600,
)
response.raise_for_status()
print(response.json()["choices"][0]["message"]["content"])
```

The same request works through the OpenAI Python SDK when the client points at the
SGLang-Omni server. Extra fields such as `modalities` and the media lists pass
through unchanged:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8008/v1", api_key="EMPTY")
response = client.chat.completions.create(
    model="qwen3-omni",
    messages=[{"role": "user", "content": "Summarize the plot in one sentence."}],
    modalities=["text"],
    max_tokens=128,
)
print(response.choices[0].message.content)
```

### Media Input

Media reaches the model in two ways, and a request may use either one:

- Top-level `images`, `audios`, and `videos` lists, each entry a local path
  visible to the server, an HTTP(S) URL, or a data URL.
- OpenAI content parts inside a message: `text`, `image_url`, `video_url`,
  `audio_url`, and `input_audio`, where `input_audio` carries base64 `wav` or
  `mp3` data.

```json
{
  "role": "user",
  "content": [
    {"type": "image_url", "image_url": {"url": "tests/data/cars.jpg"}},
    {"type": "text", "text": "How many cars are there in the picture?"}
  ]
}
```

Media parts keep their message and their position in it across conversation
turns. When a request also uses the top-level lists, the top-level media follow
the parts of the final user message. Any other part type is rejected with a 400.
The optional `detail` field does not override the model's image preprocessing
settings.

When every part of the question comes from audio, video, or image input, set
`"content": ""` on the user message. Leaving a text question in `content` alongside
the media makes the model read both.

### Image and Text Input

```bash
curl -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": "How many cars are there in the picture?"}],
    "images": ["tests/data/cars.jpg"],
    "modalities": ["text"],
    "max_tokens": 16
  }'
```

### Audio and Image Input

```bash
curl -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": ""}],
    "images": ["tests/data/cars.jpg"],
    "audios": ["tests/data/query_to_cars.wav"],
    "modalities": ["text"],
    "max_tokens": 16
  }'
```

### Video and Audio Input

```bash
curl -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": ""}],
    "videos": ["tests/data/draw.mp4"],
    "audios": ["tests/data/query_to_draw.wav"],
    "modalities": ["text"],
    "max_tokens": 16
  }'
```

### Speech Output

Set `"modalities": ["text", "audio"]` and select the audio container with `audio`.
The reply text stays in `choices[0].message.content`; the speech arrives
base64-encoded in `choices[0].message.audio.data`.

```bash
curl -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": "How many cars are there in the picture?"}],
    "images": ["tests/data/cars.jpg"],
    "modalities": ["text", "audio"],
    "audio": {"format": "wav"},
    "max_tokens": 16
  }'
```

```python
import base64
from pathlib import Path

import requests

response = requests.post(
    "http://localhost:8008/v1/chat/completions",
    json={
        "model": "qwen3-omni",
        "messages": [
            {"role": "user", "content": "How many cars are there in the picture?"}
        ],
        "images": ["tests/data/cars.jpg"],
        "modalities": ["text", "audio"],
        "audio": {"format": "wav"},
        "max_tokens": 16,
    },
    timeout=600,
)
response.raise_for_status()
message = response.json()["choices"][0]["message"]
print(message["content"])
Path("reply.wav").write_bytes(base64.b64decode(message["audio"]["data"]))
```

Some models return the spoken text as `message.audio.transcript` as well, and take
an optional `audio.ref_audio` reference clip for voice conditioning; both are
documented with the model. A text-only server accepts
`"modalities": ["text", "audio"]` without raising an error but returns no audio, so
check that the model page's launch command starts the speech stages.

### Streaming

Set `"stream": true` to receive Server-Sent Events. Text deltas arrive in
`choices[0].delta.content`; speech chunks arrive base64-encoded in
`choices[0].delta.audio.data`. A stream ends with `data: [DONE]`.

```bash
curl -N -X POST http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-omni",
    "messages": [{"role": "user", "content": "Say one friendly sentence."}],
    "modalities": ["text", "audio"],
    "audio": {"format": "wav"},
    "stream": true,
    "max_tokens": 64
  }'
```

This client prints text as it arrives and writes each audio chunk to its own file.
Each chunk is a complete container, so concatenating the files byte for byte does
not produce one playable stream; decode the PCM frames if you need a single file.

```python
import base64
import json
from pathlib import Path

import requests

chunks: list[Path] = []
with requests.post(
    "http://localhost:8008/v1/chat/completions",
    json={
        "model": "qwen3-omni",
        "messages": [{"role": "user", "content": "Say one friendly sentence."}],
        "modalities": ["text", "audio"],
        "audio": {"format": "wav"},
        "stream": True,
        "max_tokens": 64,
    },
    stream=True,
    timeout=600,
) as response:
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data = line.removeprefix("data: ")
        if data == "[DONE]":
            break
        event = json.loads(data)
        delta = event["choices"][0].get("delta", {})
        if delta.get("content"):
            print(delta["content"], end="", flush=True)
        audio = delta.get("audio") or {}
        if audio.get("data"):
            path = Path(f"chunk_{len(chunks):03d}.wav")
            path.write_bytes(base64.b64decode(audio["data"]))
            chunks.append(path)
```

## Server Readiness

Before it reports ready, the server sends itself a chat request with a small
image, one second of audio, and a short instruction — text and audio output in
speech mode, text output in text-only mode, at most 8 new tokens from each stage
that generates tokens — once per replica of its most replicated process, one after
another, so that every replica serves one. `/health` returns 503 with status
`starting` until these requests have passed through every stage, so the one-time
kernel builds of that request path happen before the first user request. Inputs of
other shapes, such as video or a large concurrent batch, can still build a kernel
variant on first use. A failed warmup stops the server.
`SGLANG_OMNI_WARMUP_TIMEOUT` (seconds, default 600) bounds each request, and
`--skip-server-warmup` reports ready without them.

## Request Parameters

Fields accepted by `/v1/chat/completions`. Model support and defaults vary; the
model page or cookbook lists the fields, defaults, and sampling controls that
apply to a specific checkpoint.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | string | served model | Model identifier |
| `messages` | list | (required) | Chat messages, each with `role` and `content` |
| `modalities` | list | `["text"]` | Requested outputs: `["text"]`, or `["text", "audio"]` for text and speech |
| `images` | list | `null` | Image paths, HTTP(S) URLs, or data URLs |
| `audios` | list | `null` | Audio paths, HTTP(S) URLs, or data URLs |
| `videos` | list | `null` | Video paths, HTTP(S) URLs, or data URLs |
| `max_tokens` | int | model default | Maximum tokens to generate |
| `max_completion_tokens` | int | `null` | OpenAI-compatible alias for `max_tokens` |
| `temperature` | float | model default | Sampling temperature |
| `top_p` | float | model default | Top-p sampling |
| `top_k` | int | model default | Top-k sampling |
| `min_p` | float | model default | Minimum-token probability |
| `repetition_penalty` | float | model default | Repetition penalty |
| `stop` | string or list | `null` | Stop sequences |
| `seed` | int | `null` | Random seed for reproducibility |
| `stream` | bool | `false` | Stream results as Server-Sent Events |
| `audio` | object | `null` | Speech output settings, such as `{"format": "wav"}`; some models add `ref_audio` |
| `stage_sampling` | object | `null` | Per-stage sampling overrides, such as `{"thinker": {"temperature": 0.8}}` |
| `stage_params` | object | `null` | Per-stage non-sampling overrides |
| `use_audio_in_video` | bool | `null` | Set `true` to process audio embedded in video input |

## Error Handling

Non-streaming requests return HTTP 400 for invalid media, HTTP 503 when the
request queue is full, and HTTP 500 for other server failures.

With `stream=true`, errors detected after the event stream starts are sent as an
SSE event and then the stream still closes with `data: [DONE]`:

```text
data: {"error": {"message": "...", "type": "invalid_request_error", "code": 400}}
data: [DONE]
```

A full request queue uses `type: "server_error"` with `code: 503`; other server
failures use `type: "server_error"` with `code: 500`. The HTTP status stays 200
once streaming has started, so clients must check for an `error` event, including
after partial output.
