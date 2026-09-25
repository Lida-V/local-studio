# Local Studio development

- Keep machine-specific paths in the untracked config/support-config.json generated from its example.
- Never commit credentials, conversation data, model weights, runtime state or downloaded binaries.
- The supported runtime root for this release is C:/AI/LocalLLM; do not silently claim other roots are supported.
- Preserve Open WebUI branding. Keep third-party license boundaries explicit.
- Tests must not stop unrelated GPU jobs or use private conversations. Use fixtures and temporary directories.
- Record reusable implementation lessons in docs/DEVELOPMENT.md. Organization-wide knowledge logs, if used by a maintainer, must remain outside this public repository.
