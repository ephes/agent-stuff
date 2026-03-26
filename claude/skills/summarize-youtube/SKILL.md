---
name: summarize-youtube
description: This skill should be used when the user asks to "summarize a YouTube video", "summarize this video", pastes a YouTube URL and asks for a summary, says "what is this video about", or asks to "extract a transcript" from a YouTube link.
allowed-tools: Bash
---

# Summarize YouTube Videos

## Overview

Extract transcripts from YouTube videos using the `summarize` CLI (`@steipete/summarize`) and produce a concise summary. The transcript is extracted locally and then summarized in-context by Claude.

## When To Use

Use this skill when:
- The user provides a YouTube URL and wants a summary.
- The user asks to extract or read a YouTube transcript.
- The user pastes a YouTube link and asks "what is this about?"

## Workflow

1. Receive a YouTube URL from the user.
2. Run `summarize "<URL>" --extract --youtube auto --timestamps` to extract the raw transcript.
3. If `--timestamps` output is too long (over ~30k chars), re-run without `--timestamps` or truncate.
4. Read the extracted transcript and produce a structured summary including:
   - **Title** (from the transcript metadata if available)
   - **Key topics** covered
   - **Summary** (3-5 paragraphs depending on video length)
   - **Notable quotes or takeaways** (if applicable)

## CLI Reference

```bash
# Extract raw transcript (preferred - lets Claude summarize)
summarize "<URL>" --extract --youtube auto --timestamps

# Extract and format as markdown via LLM (alternative)
summarize "<URL>" --extract --format md --markdown-mode llm

# Extract with slide screenshots (requires ffmpeg + yt-dlp)
summarize "<URL>" --slides --extract
```

### YouTube transcript modes

| Mode | Behavior |
|------|----------|
| `auto` (default) | youtubei -> captionTracks -> yt-dlp -> Apify |
| `web` | youtubei -> captionTracks only |
| `no-auto` | Creator captions only (skip auto-generated) |
| `yt-dlp` | Download audio + local Whisper transcription |

## Rules

- Always use `--extract` so that Claude performs the summarization rather than an external LLM.
- Pass `--youtube auto` unless the user requests a specific mode.
- If extraction fails, suggest the user try `--youtube web` or `--youtube yt-dlp` as fallbacks.
- For very long videos (> 2 hours), warn the user that the transcript may be truncated and offer to focus on specific sections.
- Do not install or modify the `summarize` package; assume `summarize` is already available on `PATH`.
