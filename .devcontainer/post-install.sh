#!/bin/bash
set -ex

# Convenience workspace directory for later use
WORKSPACE_DIR=$(pwd)

# Change some Poetry settings to better deal with working in a container
poetry config cache-dir ${WORKSPACE_DIR}/.cache
poetry config virtualenvs.in-project true

# Now install all dependencies
poetry install

if [[ ! -d "${WORKSPACE_DIR}/config" ]]; then
    mkdir -p "${WORKSPACE_DIR}/config"
    cp "${WORKSPACE_DIR}/.devcontainer/configuration.yaml" "${WORKSPACE_DIR}/config/configuration.yaml"
    ${WORKSPACE_DIR}/.venv/bin/hass --config "${WORKSPACE_DIR}/config" --script ensure_config
fi

export PYTHONPATH="${PYTHONPATH}:${WORKSPACE_DIR}/custom_components"
