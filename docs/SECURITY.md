# Security Model

NetLogo MCP gives the connecting AI client **arbitrary file and process I/O
on the host machine**, scoped to the user the server runs as. The `command`
and `create_model` tools accept any NetLogo statement; NetLogo's standard
primitives include `file-open` / `file-write-line` / `file-delete`,
`export-world` / `import-world`, `set-current-directory`, and — via
extensions — shell calls (`sh`), Python execution (`py`), and network I/O
(`web`). Treat the trust boundary the same way you treat a local terminal:
**only connect this server to AI clients you trust as much as a shell.**

Concretely:

- The stdio transport assumes the parent client is trusted. There is no
  auth, and adding it wouldn't help — the parent process owns the file
  descriptors.
- The `models/` and `exports/` directories are writable by any tool call.
  Don't point `NETLOGO_MODELS_DIR` at a location you wouldn't `chmod o+w`.
- Models downloaded via `open_comses_model` are extracted with
  path-traversal and zip-bomb guards (see below), but **once loaded, any
  `command` call against them runs untrusted NetLogo code**. Read the ODD
  doc and skim the source before running setups on third-party models.
- An opt-in restricted mode is available: set `NETLOGO_MCP_RESTRICTED=true`
  to block dangerous primitives (`file-*`, `import-world`,
  `set-current-directory`, `user-*` dialogs, and common extension shell
  escapes like `sh:exec`, `py:run`, `web:get`). The default remains
  unrestricted — the product is "let the AI drive NetLogo," and a
  restricted default would break the core flow.

## CoMSES download safety

Safety properties applied to every CoMSES archive download:

- Archives streamed with a hard byte cap (`COMSES_MAX_DOWNLOAD_MB`, default
  50 MB) enforced mid-stream, not just via HEAD.
- Every zip member is path-traversal-validated before extraction.
- Zip-bomb refusal on uncompressed-size overflow.
- Extraction is atomic: downloads land in a temp dir first, then move to
  the cache only on success.
- Cache directories are trusted only when they carry the
  `.comses_complete` marker.
- `"latest"` is resolved to a concrete version before any cache path is
  computed; the resolved version is returned to the AI so follow-up reads
  stay pinned to the same slot.
