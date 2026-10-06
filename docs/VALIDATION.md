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

## Qwen Image 2.1 prompt skill (2026-09-30)

- Twenty offline regressions pass: fixed topics, invalid inputs, paragraph pagination, complete infographic text preservation, canonical-source freshness, malformed-source fallback, instruction replacement/idempotency, project independence and helper reload on a changed file signature.
- Fresh MCP connection enumerated 15 tools and read the multi-reference guide. CLI read a local-edit guide. The live toolkit and existing preset were updated while preserving unrelated settings.
- A disposable Open WebUI API client using the deployed preset consulted overview and t2i, received actual guide results and returned an English prompt for a synthetic blue-bowl request. No image-generation or command tool was invoked. This verifies the model/tool/API path; the desktop chat workflow was not separately operated for this change.
- Public source scan passes on 63 files. Generic core/recipe snapshots are included; private runtime paths and private source notes are replaced with portable guidance and upstream links. Official PE model weights and full system prompts are not bundled.
- This is prompt-design guidance. Reference/edit execution, image quality, transparency success, fresh installation and unrestricted content generation are not validated by these tests.

## Optional Huihui model selection (2026-09-30)

- Downloaded publisher UD-DW-Q4_K_M GGUF at fixed revision, verified all 16,551,316,384 bytes and SHA256, retained the reviewed upstream Apache-2.0 LICENSE, and preserved standard model files.
- Actual RTX 4090 deployment switched to the new profile, verified the launched process identity and --model path, retained stable alias/ports and8192 context, and preserved preset settings apart from display name.
- Synthetic Japanese game arithmetic with JSON schema and two independent colored-shape image requests passed. Existing mmproj-F16 reuse worked for those fixtures. Generic Open WebUI API/tool flow consulted overview and t2i, returned an English image prompt, and invoked no generation or command tool. Fresh MCP connection exposed15 tools.
- Actual server props showed vision=true and n_ctx8192. GPU-wide usage at one check was21,081/24,564MiB including other applications, not an isolated model peak.
- 47 new offline checks pass: profile/path validation 12, failure-injected switch/rollback 17, maintenance admission/streaming/SPA ordering 8, ordered bounded range download 10. 77 total Python unittest cases plus six ChatTools checks and a 76-file source scan passed with the existing relevant regressions.
- Active WebUI/Comfy work caused deployment or switching to refuse without stopping it. An additional live switch back to standard was refused during a separate Comfy job; both directions and recovery failure paths are covered offline. The original standard model already has separate live startup/vision validation.
- Updated toolkit can install the admission gate while WebUI runs; launcher startup also installs it. The authenticated state endpoint is positioned before the SPA root mount. Existing installations must deploy the updated toolkit or restart the updated launcher before switching.
- No adult-content generation, refusal-rate assessment, general creative quality, video understanding, desktop click workflow, clean-machine install or other-GPU performance is claimed for this change. Chat model selection does not change ComfyUI image models or solve accumulated-image context overflow.

## Strata + Qwen3.8 Flash Next (2026-10-06)

Existing Windows deployment: RTX 4090 24 GB, 157.7 GiB RAM, NVIDIA driver 610.62. Strata v0.1.39 is pinned to `6f32ec070f23ced9f50e704d854d775da52591ab`, with the Windows CUDA 13 release, GSQ-RCO IQ3_S two-part GGUF, dedicated vision projector and pinned MTP tensors. The prepared context is 131,072 tokens.

- All eight live Strata API checks passed: loaded text/vision health and canonical/legacy aliases; Japanese JSON with 17×19 = 323; two independent colored-shape images with swapped positions; a synthetic tool/result loop; ordinary SSE text; long-context exact retrieval; and recovery after disconnecting the verifier's own streaming request.
- Long-context `count_tokens` reported 15,673 input tokens; the actual completion reported 15,762 prompt tokens with the response-format instructions. This verifies input above the former 8K limit. It does not validate an input filling the complete 128K context or arbitrary long-document accuracy.
- A fresh stdio MCP connection advertised the expected 15 tools, read the multi-reference prompt guide and submitted one synthetic `ask_qwen` job. Only that job was polled; it completed with the exact `STUDIO_MCP_OK` text. The verifier-owned MCP child exited with code 0 without forced termination.
- A disposable Open WebUI API client used the existing preset with only the installed read-only guide schema advertised. It consulted overview, supplied actual guide results in a native tool loop and returned a blue-bowl image prompt through SSE. No media/project tool was executed, no saved chat was created and the selected project was not changed. This covers the model/tool/API path; desktop clicks were not operated for this test.
- `Test-StrataMTP.py` has 11 offline checks covering fixed manifest/ranges, resumed tensor hashing, preserved corrupt/oversized files, invalid status/encoding/length, incompatible inventories and refusal of floating/foreign sources. Eight checks require the pinned local Strata source and skip when it is absent; the tests never fetch a checkout or real tensors.
- Strata owned-process disappearance, measured GPU release, restart and one synthetic 512px Anima blue-bowl handoff all passed with the dedicated desktop open. Flash Next recovered with vision and 131072 context, and exact Japanese/ASCII replies. Selected-project record hashes matched. The original deployment then removed exactly the three SHA-verified retired27B artifacts (33,943,364,096bytes); no chats, attachments, projects or training data were removed.
- Initial700MiB reserve produced a low-free-VRAM warning. The final reserve1536MiB was verified in the actual engine command, startup had approximately1049MiB free without the LOW warning, and all eight API tests plus WebUI/MCP tests were repeated. This is a device-specific observation, not a peak or other-GPU guarantee.

JSON response formats use schema prompting followed by server validation, with one generation and no hidden retry. This integration installs `jsonschema>=4.23,<5`; an external Strata setup without it checks only that the response is one JSON object. The schema root must be an object; local `#` references work and remote references are rejected. This is not grammar-constrained decoding. Invalid schemas return HTTP 400; malformed/incomplete JSON, duplicate keys, non-finite numbers and schema violations return HTTP 502 with `structured_output_failed`. Structured formats combined with tools/MCP are explicitly rejected. Structured SSE buffers content until validation; the ordinary incremental SSE and native tool checks above were separate requests. See the [pinned Strata API documentation](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/DETAILS.md#json-response-formats).

Clean-machine public Setup, other GPUs/RAM capacities, full 128K input, sustained reliability, video understanding, adult-content suitability, refusal rates and general creative quality remain unverified. The tests do not guarantee unrestricted generation or behavior for every image/document/tool. Runtime results and synthetic fixtures remain outside this public source tree.

## Optional Swift 1.5 Flash Next (2026-10-06)

The same Windows/RTX 4090 deployment selected Swift IQ3_XXS at SC117 revision `70238546d13a135459cf25d7647c3690cb7e1165`. Five downloaded files (both GGUF shards, its own BF16 projector, Swift and Qwen licenses) matched fixed sizes and SHA256. Four reused MTP files also matched their pinned hashes. A separate native pack was built: Swift uses PLE from shard 1, unlike the stock profile. The loaded API model path, canonical alias and actual owned engine arguments matched Swift, with 131072 context and 1536MiB VRAM reserve. Stock Flash Next was preserved.

- Seven of eight initial API checks passed, including Japanese structured arithmetic, both colored-shape images, ordinary SSE, exact retrieval from 15673 counted input tokens /15762 completion prompt tokens, and own-request cancellation. The initial tool test failed strict final JSON formatting. A diagnostic rerun correctly executed both native tools and combined their values, but changed the required `fixture` key to `memo`. Explicit literal keys and an output template then passed the unchanged strict validator. Failed results were preserved; this is not a claim of flawless tool-output instruction following.
- MCP advertised15 tools, read a guide and completed the verifier's synthetic job with exact `STUDIO_MCP_OK`; its owned child exited normally. The initial WebUI test exhausted its five-turn guide budget after five normal guide calls, before a final response. A separate WebUI rerun with an explicit English final prompt and a twelve-turn budget passed while preserving the same deadline and guide-only guards. No saved chat, project content, image-generation or command tool was used in that prompt test.
- Owned-process disappearance, GPU release, restart, one512px Anima image and return to Swift all passed. The resulting blue ceramic bowl was separately viewed. Swift recovered with vision/128K and exact synthetic replies; selected-project metadata hashes matched. The dedicated desktop, chat server and worker remained running.
- 105 offline tests passed: model profiles20, switch/rollback27, range download12, Swift preparation15, Swift download7, Strata lifecycle11 and chat adapter13. The public source scan passed after the allowlisted export. Runtime weights, private configuration, chat history and test images/logs are not distributed.

The inspected local preset system matched its authored source and had no blanket sexual-content prohibition; preset filters were empty and the WebUI functions list contained no entries. A generated assistant statement about its own policies is not evidence of a server setting. This inspection does not establish how every retained conversation or model will behave. Adult-content suitability/refusal rates, full128K input, general creative quality, clean-machine installation and other hardware remain untested. Swift's commercial-use conditions are separate from this repository's MIT license; see THIRD_PARTY_NOTICES.md and the downloaded upstream licenses.
