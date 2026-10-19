# Whisper Turbo ASR (test page)

This page exists only to demo the `cookbook-order` lint: the model
[openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo)
is a real Hugging Face model that is intentionally NOT registered in either
`ROADMAP_ORDER` or `DOWNLOADS_DESC`, so the cookbook-order check must fail CI
with an "unknown entry" violation.
