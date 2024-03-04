FROM mcr.microsoft.com/vscode/devcontainers/python:0-3.11-bullseye

RUN apt-get update && apt-get install -y apt-transport-https gnupg2 procps less curl
RUN wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | apt-key add -
RUN echo "deb https://artifacts.elastic.co/packages/7.x/apt stable main" | tee /etc/apt/sources.list.d/elastic-7.x.list
RUN apt-get update && apt-get install elasticsearch
RUN chmod g+rw /var/lib/elasticsearch
RUN chmod g+rw /var/log/elasticsearch
RUN usermod -G elasticsearch -a vscode

# Install Poetry for dependency management
RUN pip install poetry~=1.7
RUN pip3 install homeassistant==2024.2.5

# Install peek utility
RUN pip install es-peek
RUN mkdir /home/vscode/.config/peek
COPY ".devcontainer/peek" /home/vscode/.config/peek/
RUN chown -R vscode:vscode /home/vscode/.config/peek

RUN mv /etc/elasticsearch/elasticsearch.yml /etc/elasticsearch/elasticsearch.yml.old
COPY ".devcontainer/elasticsearch/config_7x" /etc/elasticsearch/