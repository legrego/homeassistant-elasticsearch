#!/bin/bash
set -ex

# Convenience workspace directory for later use
WORKSPACE_DIR=$(pwd)

# Change some Poetry settings to better deal with working in a container
poetry config cache-dir ${WORKSPACE_DIR}/.cache
poetry config virtualenvs.in-project true

# Now install all dependencies
poetry install

if [[ ! -d "${PWD}/config" ]]; then
    mkdir -p "${PWD}/config"
    cp "${PWD}/.devcontainer/configuration.yaml" "${PWD}/config/configuration.yaml"
    ${PWD}/.venv/bin/hass --config "${PWD}/config" --script ensure_config
fi

export PYTHONPATH="${PYTHONPATH}:${PWD}/custom_components"
