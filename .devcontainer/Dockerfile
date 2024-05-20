FROM mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm

RUN apt-get update && apt-get install -y apt-transport-https gnupg2 procps less curl

COPY ".devcontainer/install-docker-cli.sh" install-docker-cli.sh

RUN /bin/bash install-docker-cli.sh

# Install Poetry for dependency management
RUN pip install poetry~=1.7

# Install peek utility
RUN pip install es-peek
RUN mkdir /home/vscode/.config/peek

COPY ".devcontainer/peek" /home/vscode/.config/peek/

RUN chown -R vscode:vscode /home/vscode/.config/peek

