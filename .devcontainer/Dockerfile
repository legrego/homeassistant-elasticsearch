FROM mcr.microsoft.com/vscode/devcontainers/python:0-3.10-bullseye

RUN apt-get update && apt-get install -y apt-transport-https gnupg2 procps less curl
RUN wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | apt-key add -
RUN echo "deb https://artifacts.elastic.co/packages/7.x/apt stable main" | tee /etc/apt/sources.list.d/elastic-7.x.list
RUN apt-get update && apt-get install elasticsearch
RUN chmod g+rw /var/lib/elasticsearch
RUN chmod g+rw /var/log/elasticsearch
RUN usermod -G elasticsearch -a vscode

RUN mv /etc/elasticsearch/elasticsearch.yml /etc/elasticsearch/elasticsearch.yml.old
COPY ".devcontainer/elasticsearch/config_7x" /etc/elasticsearch/