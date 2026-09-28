# Development notes

- Keep desktop cache separate from the persistent Open WebUI database. Validate resolved paths and reparse points before cleanup.
- Windows MCP clients may use a Job Object that terminates every descendant. A subprocess or double-spawn alone does not make a job survive disconnection. Use the independently launched queue worker.
- Windows background descendants can keep captured stdout/stderr pipes open after their parent exits. Launch long-running servers with real log files rather than waiting for pipe EOF.
- ComfyUI `/free` can return an empty successful body. Do not require JSON in that response.
- Open WebUI 0.11.4 persists tool images with the `files` event; a visually displayed image is not proof that it is saved in the conversation DB.
- Electron 44.4.5's npm package requires explicitly invoking the bundled installer to obtain the binary. Check `dist/electron.exe` before declaring installation successful.
- Batch launchers with non-ASCII paths use UTF-8 without BOM and an initial ASCII `chcp 65001` line.
- Reusable knowledge belongs here. Credentials, machine profiles and private production records belong outside this repository.

- Keep preparation actions separate from installation, download and training. An existing Python executable is not proof that training works.
- Open WebUI 0.11.4 video rendering needs one block HTML token: `<div><video>/api/v1/files/ID/content</video></div>`. Inline video tags can be split and displayed literally. Upload video with `process=false`, persist a `files` event, and include the block in the assistant message; test a reload.
- A server launcher returning a PID does not mean its HTTP endpoint is ready. Poll readiness with a deadline before submitting work.
- GPU handoff may skip the model server, but must still start and verify the chat server. Reopening an existing desktop window must also check the backend; verify health before opening Electron and report early server exit without waiting for the full startup timeout. Validate with `python scripts/Test-DesktopStartup.py`.
- Coordinate all known ComfyUI queues before releasing models. Treat request timeouts as unknown, not idle.

- Persist the selected project in application data, separately from disposable browser cache. Invalid/missing selections must fail rather than silently switch destinations.
- Snapshot a project for every queued job and before command confirmation. A global selection change must not redirect an already accepted operation.
- Resolve both the selected root and child path; reject traversal, absolute paths outside the project, alternate data streams and escaping junctions. This boundary applies to file tools; approved PowerShell retains Windows user permissions.
- Desktop folder selection uses the main-process native dialog. Check the IPC sender and main frame, expose no arbitrary path setter to the web page, and keep Open WebUI branding and its existing new-chat shortcut visible/available.

- Bound retrieved text by characters as well as lines. Return continuation positions for long lines, directory pages and partial searches; do not silently truncate. Reading a 100 KB+ source should not require loading it all into the model.
- Clamp oversized positive line requests instead of rejecting them: return requested/effective limits and continuation. Distinguish missing image files and directories before opening images; do not infer encoding problems from unrelated path errors.
- The default 8192-token server context and the 2400-character/120-line file excerpts are separate settings, not measured hardware ceilings. Larger contexts need memory and speed validation on the target GPU; the model's advertised context does not guarantee that it fits.
- Open WebUI 0.11.4 estimates context using characters/4, which undercounts Japanese. The runtime adapter uses a conservative Japanese-aware estimate, earlier compaction and short older file excerpts. User/system instructions and stored conversation history are preserved. The model still has a finite context limit.
- The send-now action and the cancel socket callback can both process the same queue. Hold the per-chat queue guard across stop, task reconciliation and submission; remove only the selected item after stop succeeds. A captured response object must not overwrite a newer history pointer after an await.
- Cancellation of asyncio.to_thread does not stop its OS thread. Wait for media/command operations to finish, and display stopping until they do. Do not equate a removed task ID with a completed operation.
- webui_runtime installs only against the pinned 0.11.4 build. It serves an exact-match JS compatibility patch from memory and fails on mismatched source; installed package files remain unchanged. Set FROM_INIT_PY before importing open_webui.main or its frontend path resolves incorrectly.
