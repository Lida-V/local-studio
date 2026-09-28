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

## Project selection update (2026-09-28)

- Six offline regression tests pass: persistent selection/read/write/backup/reset, invalid paths and escaping Windows junctions, missing-folder refusal, media/training snapshot routing, command working-directory snapshot before approval, and queued job routing after a switch. Existing chat and media tests also pass.
- Live MCP connection enumerated 13 tools and selected a Japanese-named fixture project, wrote/read a file and restored the prior selection. No inference or training was needed for this test.
- Dedicated desktop updated; native directory dialog selected a Japanese-named fixture; toolbar and a fresh CLI process reported the same path. Reset to the default folder was checked. Open WebUI header and branding remain visible below the toolbar.
- Selection applies to all chats. A complete conversational request can contain multiple tools: wait for it to finish before switching. Only already submitted jobs and individual approved commands are pinned; this release does not bind each chat to its own project.

## File investigation, activity and insertion update (2026-09-28)

- Eight new Python regressions and four queue JavaScript cases pass, including large Japanese text, long-line continuation, CP932/UTF-16, paged search/list, error guidance, cancellation of real worker threads, preservation of user instructions, double-click, stop failure and navigation while stopping. Existing 17 checks pass.
- Actual desktop: read line 6000 from a 195208-byte Japanese fixture and a CP932 fixture; both expected phrases matched and the status returned to completed.
- Actual desktop: during a long numbered response, one click on the queued message's send-now button stopped and resumed with the new instruction. The saved chat contains exactly one inserted user message and a completed response with the expected exact phrase. No second insertion was used.
- Actual MCP: 14 tools, filename search and CP932 reading verified. Activity API requires authentication (anonymous 401); served compatibility JS has no-store and passes module syntax validation.
- read_workspace_file now returns a structured object with content and continuation positions; list_workspace returns entries and next_offset. Consumers of the previous string/list return types must update.
- The activity bar describes desktop chat tasks. MCP/CLI jobs remain independently tracked through task_result. No inference benchmark, all-model cancellation guarantee, general PDF/Office parsing or clean-machine installation claim is made.
