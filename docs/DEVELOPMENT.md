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
- Coordinate all known ComfyUI queues before releasing models. Treat request timeouts as unknown, not idle.
