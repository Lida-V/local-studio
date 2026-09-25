# Validation scope

## Original working deployment

Windows, RTX 4090 24 GB, Python 3.11, Open WebUI 0.11.4, Electron 44.4.5, MCP SDK 1.27.2, llama.cpp b11146.

- Japanese chat, image and text attachments, conversation persistence.
- Dedicated Electron window; memory-only session; owned temporary directory removed after exit.
- Existing conversation and saved image displayed after reopening.
- MCP handshake and all eleven tool definitions.
- Workspace file write/read/backup and out-of-root rejection.
- Local Qwen calculation returned 323 for 17×19.
- MCP Anima image at 512×512 completed after disconnect/reconnect; Qwen resumed.

## Public source tree

- Allowlisted source export; no private Git history, credentials, profile paths, chat DB, model weights or runtime logs.
- Python syntax/JSON/manifest/source scan with Verify-Source.py.
- Temporary-directory boundary/backup tests and mocked busy ComfyUI/empty-response tests with Test-ChatTools.py.
- JavaScript and PowerShell syntax checks.

Public sources replace machine-specific tools and source paths with discovery and repository-relative paths. The complete public installer has not been run on a clean machine. Tests above do not claim fresh-install, other-GPU, all model behavior, long-running reliability, general audio/video editing or image-editing coverage.

## Media and preparation update (2026-09-25)

- Actual generation on the original RTX 4090 deployment: Anima 512×512, Qwen Image 2.1 512×512, MiniMax H3 608×352 / 56 frames / 24 fps with H.264 video and AAC stereo audio. Qwen resumed afterward.
- Actual Qwen image and H3 video were attached to a synthetic verification chat. Reloaded video element reported 608×352, 2.333333 seconds, readyState 4 and no media error. This is attachment/render verification; autonomous model selection through a new full conversation was not separately retested for both added models.
- Desktop preparation window: switch model and create a Qwen Image 2.1 preparation folder. MCP: enumerate 11 tools, read guides and prepare a Qwen3.8 folder. No training executed.
- Offline tests cover geometry, unknown/busy server handling, lock release, preparation path validation, duplicate rejection and no subprocess execution.
- No trainer quality, full fine-tuning, fresh public installation or other GPU claims are made.
