# Contributing to NetLogo MCP

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/Razee4315/NetLogo_MCP.git
cd NetLogo_MCP
pip install -e ".[dev]"
```

You'll need Java JDK 11+ and NetLogo 7.0+ installed for integration testing. Unit tests use mocks and don't require either.

## Running Tests

```bash
pytest tests/ -v
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests to make sure nothing breaks
5. Commit with a clear message
6. Push to your fork and open a Pull Request

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Your Python, Java, and NetLogo versions
- Any error messages or logs

## Code Style

- Follow existing patterns in the codebase
- Keep functions focused and well-named
- Add tests for new tools or resources
