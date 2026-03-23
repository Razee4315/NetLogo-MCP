# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-02-23

### Added

- Initial release of NetLogo MCP Server
- 12 tools: `open_model`, `command`, `report`, `run_simulation`, `set_parameter`, `get_world_state`, `get_patch_data`, `export_view`, `create_model`, `list_models`, `save_model`, `export_world`
- 3 resources: `netlogo://docs/primitives`, `netlogo://docs/programming`, `netlogo://models/{name}`
- 3 prompts: `analyze_model`, `create_abm`, `parameter_sweep`
- Headless and GUI mode support
- Built-in NetLogo primitives reference and programming guide
- Path traversal protection on all file operations
- XML escaping for `.nlogox` model creation
- Stdout protection to prevent JVM corruption of MCP stdio transport
- Mock-based test suite (no Java/NetLogo needed to run tests)
- Cross-platform JVM detection (Windows, Linux, macOS)
