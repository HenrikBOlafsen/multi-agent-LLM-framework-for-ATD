# Multi agent LLM framework for ATD
Multi agent LLM framework for architectural tech debt


## Setup
uv is used as package manager. See how to install [here](https://docs.astral.sh/uv/getting-started/installation/)

Docker is used

How to build image from Dockerfile:
docker build --target dev -t atd-dev .

How to run container from image and open terminal inside the container:
docker run --rm -it -v "${PWD}:/workspace" -w /workspace atd-dev
