FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nodejs \
    npm \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python packages — only what your pipeline needs, no pytorch
RUN pip3 install \
    numpy \
    pandas \
    matplotlib \
    scipy \
    pillow \
    anthropic \
    openai \
    google-generativeai

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
CMD ["/bin/bash"]