# Copilot Instructions for homeassistant-elasticsearch

This is a Home Assistant custom component that publishes Home Assistant events to Elasticsearch clusters. This document provides guidance for AI coding assistants working with this codebase.

## Project Overview

- **Purpose**: Publish Home Assistant events to Elasticsearch using the Bulk API
- **Language**: Python 3.13+
- **Key Dependencies**: 
  - Home Assistant (homeassistant==2025.6.0)
  - Elasticsearch client (elasticsearch8~=8.14.0)
- **Architecture**: Home Assistant custom component with config flow support
- **Quality**: Platinum quality scale (per manifest.json)

## Repository Structure

```
custom_components/elasticsearch/  - Main integration code
  __init__.py                     - Component initialization
  config_flow.py                  - Configuration flow UI
  es_gateway.py                   - Elasticsearch API gateway
  es_publish_pipeline.py          - Event publishing pipeline
  datastreams/                    - Datastream management
tests/                            - Test suite
docs/                             - Documentation (MkDocs)
scripts/                          - Development scripts
  lint                            - Run linting/formatting
  test                            - Run test suite
```

## Development Workflow

### Setup

This project uses Poetry for dependency management and includes a devcontainer for consistent development:

```bash
pip install poetry~=2.2.1
poetry install
```

### Testing

**ALWAYS run tests before and after making changes:**

```bash
poetry run ./scripts/test
# Or inside poetry shell:
poetry shell
./scripts/test
```

Tests use pytest with Home Assistant custom component test framework. Snapshot testing is used extensively - if snapshots need updates, run `./scripts/update_snapshots`.

### Linting

**ALWAYS run linting before committing:**

```bash
poetry run ./scripts/lint
# Or inside poetry shell:
poetry shell
./scripts/lint
```

Linting uses:
- **ruff** for code formatting and linting (configured in `.ruff.toml`)
- Auto-fixes are applied by default (use `--no-fix` to check only)

## Code Style & Conventions

### Python Style

- **Line length**: 110 characters (configured in `.ruff.toml`)
- **Target**: Python 3.12+ (`target-version = "py312"`)
- **Type hints**: Always use type hints. Use `from __future__ import annotations` for modern syntax
- **Imports**: Managed by ruff/isort - imports are auto-sorted
- **Docstrings**: Required for public APIs (D-series rules enabled)
- **Logging**: Use structured logging via the custom logger module

### Naming Conventions

- **Classes**: PascalCase (e.g., `ElasticIntegration`, `ESGateway`)
- **Functions/Methods**: snake_case (e.g., `async_setup_entry`, `publish_events`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `ELASTIC_DOMAIN`, `CONF_URL`)
- **Private members**: Prefix with underscore (e.g., `_logger`, `_client`)

### Async Patterns

This is an async-first codebase using Home Assistant's async patterns:

- Use `async def` for all I/O operations
- Use `asyncio` primitives, not threading
- Entry point functions follow HA naming: `async_setup_entry`, `async_unload_entry`
- Use `@async_log_enter_exit_info` and `@async_log_enter_exit_debug` decorators from logger module

### Error Handling

Custom exceptions are defined in `errors.py`:
- `CannotConnect` - Connection failures
- `AuthenticationRequired` - Auth issues
- `UnsupportedVersion` - Version incompatibilities
- `ESIntegrationException` - Base integration exception

Map these to Home Assistant exceptions:
- `ConfigEntryNotReady` - Temporary failures (retryable)
- `ConfigEntryAuthFailed` - Auth failures (requires reconfiguration)

### Logging

Use the custom logging module (`logger.py`):

```python
from custom_components.elasticsearch.logger import LOGGER, have_child

# Get a child logger for specific context
_logger = have_child(name="component_name")
_logger.info("Message with context")
```

Decorators are available:
- `@log_enter_exit_debug` - For sync functions
- `@async_log_enter_exit_debug` - For async functions (debug level)
- `@async_log_enter_exit_info` - For async functions (info level)

## Key Architectural Patterns

### Config Flow

The integration uses Home Assistant's config flow for setup:
- `config_flow.py` defines the UI flow
- Validates connectivity and credentials during setup
- Supports reconfiguration and options flow

### Event Publishing Pipeline

The core publishing logic is in `es_publish_pipeline.py`:
1. Events are collected from Home Assistant
2. Buffered for efficient batch processing
3. Published to Elasticsearch using the Bulk API
4. Handles retries and error scenarios

### Datastream Management

The integration supports multiple Elasticsearch features:
- Time Series Data Streams (TSDS)
- Datastream Lifecycle Management (DLM)
- Index Lifecycle Management (ILM)

Detection and setup is automatic based on cluster capabilities.

### Gateway Abstraction

`es_gateway.py` and `es_gateway_8.py` provide abstraction over Elasticsearch client:
- Handles authentication (basic, API key)
- Manages connections and health checks
- Version-specific implementations

## Testing Guidelines

### Test Structure

- Tests mirror the source structure (`test_*.py` for each module)
- Use pytest fixtures extensively (see `conftest.py`)
- Snapshot tests for complex data structures (via syrupy)
- Mock Home Assistant core and Elasticsearch clients

### Writing Tests

```python
async def test_feature(hass, mock_es_client):
    """Test feature description."""
    # Setup
    config_entry = MockConfigEntry(domain=ELASTIC_DOMAIN, data={...})
    
    # Execute
    result = await async_setup_entry(hass, config_entry)
    
    # Assert
    assert result is True
    mock_es_client.assert_called_once()
```

### Snapshot Updates

When test output changes intentionally:
```bash
./scripts/update_snapshots
```

## Common Tasks

### Adding a New Feature

1. Update the relevant module in `custom_components/elasticsearch/`
2. Add/update type hints
3. Write tests in `tests/test_*.py`
4. Update documentation in `docs/` if user-facing
5. Run linting: `./scripts/lint`
6. Run tests: `./scripts/test`

### Debugging

- Enable debug logging in Home Assistant configuration
- Check logs for decorator-wrapped function entry/exit
- Use the devcontainer with breakpoints in VS Code

### Updating Dependencies

Dependencies are managed via Poetry:
```bash
poetry add package-name
poetry update package-name
```

Update `pyproject.toml` and regenerate `poetry.lock`.

## Security Considerations

- Never log sensitive data (passwords, API keys, tokens)
- Use Home Assistant's secret storage for credentials
- Validate all user inputs in config flow
- Handle connection timeouts and network errors gracefully

## Documentation

- User documentation is in `docs/` using MkDocs
- Update documentation for user-facing changes
- API documentation via docstrings
- Keep README.md updated for quick reference

## Home Assistant Integration Guidelines

Follow Home Assistant's integration quality checklist:
- Config flow required (✓)
- Async-first implementation (✓)
- Proper error handling (✓)
- Type hints throughout (✓)
- Test coverage >80% (✓)
- Documentation (✓)

## Additional Resources

- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Elasticsearch Python Client Docs](https://elasticsearch-py.readthedocs.io/)
- [Project Documentation](https://legrego.github.io/homeassistant-elasticsearch/)
- [Contributing Guide](../CONTRIBUTING.md)

## Tips for AI Assistants

1. **Always run tests and linting** before suggesting code is complete
2. **Maintain async patterns** - don't introduce blocking I/O
3. **Follow existing patterns** in the codebase for consistency
4. **Use type hints** - they're required and help catch errors
5. **Consider Home Assistant lifecycle** - integration loading, unloading, reload
6. **Test with snapshots** when working with complex data transformations
7. **Update documentation** for user-facing changes
8. **Use the custom logger** with decorators for observability
9. **Handle errors gracefully** - map to appropriate HA exceptions
10. **Keep changes minimal** - this is production code for user home automation

## Known Constraints

- Python >=3.13.2 required (latest HA requirement)
- Must be compatible with Home Assistant's async event loop
- Must not block the event loop (no sync I/O in main thread)
- Elasticsearch 8.x API compatibility required
- Quality scale is "platinum" - maintain high standards
