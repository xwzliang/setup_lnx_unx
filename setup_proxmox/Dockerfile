FROM debian:trixie-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg \
       -o /usr/share/keyrings/proxmox-archive-keyring.gpg \
    && echo '136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45  /usr/share/keyrings/proxmox-archive-keyring.gpg' | sha256sum -c \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/proxmox-archive-keyring.gpg] https://download.proxmox.com/debian/pve trixie pve-no-subscription' \
       > /etc/apt/sources.list.d/proxmox.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends proxmox-auto-install-assistant xorriso \
    && rm -rf /var/lib/apt/lists/*
