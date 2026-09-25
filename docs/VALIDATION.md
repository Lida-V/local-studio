# Validation scope

## Original working deployment

Windows, RTX 4090 24 GB, Python 3.11, Open WebUI 0.11.4, Electron 44.4.5, MCP SDK 1.27.2, llama.cpp b11146.

- Japanese chat, image and text attachments, conversation persistence.
- Dedicated Electron window; memory-only session; owned temporary directory removed after exit.
- Existing conversation and saved image displayed after reopening.
- MCP handshake and all seven tool definitions.
- Workspace file write/read/backup and out-of-root rejection.
- Local Qwen calculation returned 323 for 17×19.
- MCP Anima image at 512×512 completed after disconnect/reconnect; Qwen resumed.

## Public source tree

- Allowlisted source export; no private Git history, credentials, profile paths, chat DB, model weights or runtime logs.
- Python syntax/JSON/manifest/source scan with Verify-Source.py.
- Temporary-directory boundary/backup tests and mocked busy ComfyUI/empty-response tests with Test-ChatTools.py.
- JavaScript and PowerShell syntax checks.

Public sources replace machine-specific tools and source paths with discovery and repository-relative paths. The complete public installer has not been run on a clean machine. Tests above do not claim fresh-install, other-GPU, all model behavior, long-running reliability, audio/video or image-editing coverage.
