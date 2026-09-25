# Third-party software and models

The MIT license in this repository covers the original launcher, integration and tool code only. No third-party binaries, model weights, private configuration or upstream application source tree are redistributed here. The installer retrieves separately licensed dependencies from their upstream providers.

- [Open WebUI](https://github.com/open-webui/open-webui): 0.11.4, [Open WebUI License](https://github.com/open-webui/open-webui/blob/main/LICENSE). Its UI branding remains visible. This wrapper does not remove, obscure or replace the Open WebUI name or logo in the web interface.
- [Electron](https://github.com/electron/electron): 44.4.5, [MIT license](https://github.com/electron/electron/blob/main/LICENSE) and bundled Chromium/Node notices. The official runtime distribution retains those notices.
- [llama.cpp](https://github.com/ggml-org/llama.cpp): [MIT license](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE). The selected release contains additional runtime dependencies with their own conditions.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk): 1.27.2, [MIT license](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE).
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI): external, separately installed. Its source, custom nodes and models retain their respective licenses.
- [Qwen quantization](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF): external model. Consult the model card and upstream base model conditions. Download revision, filenames and SHA256 values are pinned in `config/download-manifest.json`.
- Anima and its text encoder/VAE are not downloaded by this project. Obtain them separately and check the corresponding model cards before use.

The Python and npm lockfiles identify additional dependencies; their own license files apply. No universal claim about all generated content or all model uses is made by this repository.

Additional media routes reference Qwen Image 2.1 and MiniMax H3 plus their separately supplied quantizations, encoders, VAEs and custom nodes. No weights are bundled or downloaded by these routes. LoRA preparation references Anima Standalone Trainer, DiffSynth-Studio, Musubi Tuner and Unsloth by documentation link only; no trainer installation is performed. Check each selected upstream distribution and model card before use.
