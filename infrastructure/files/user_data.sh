#!/bin/bash
set -euo pipefail

exec > >(tee /var/log/user-data-debug.log | logger -t user-data ) 2>&1
set -x
echo "STARTING USER DATA"

dnf install -y docker
systemctl enable --now docker

mkdir -p /opt/agents/data
chown 65532:65532 /opt/agents/data

# Caddy's /data holds the ACME account key and issued certificates. It is bind
# mounted so a container restart does not re-issue; note it does NOT survive
# instance replacement (see the app_version variable description).
mkdir -p /opt/caddy/data /opt/caddy/config

# Shared bridge network so Caddy can reach the app container by name. The app
# no longer publishes a host port — it is reachable only through Caddy.
docker network create agents-net || true

cat > /opt/caddy/Caddyfile <<'EOF_CADDYFILE'
${caddyfile_content}
EOF_CADDYFILE

cat > /etc/systemd/system/agents.service <<EOF_UNIT
${service_content}
EOF_UNIT

cat > /etc/systemd/system/caddy.service <<'EOF_CADDY_UNIT'
${caddy_service_content}
EOF_CADDY_UNIT

systemctl daemon-reload
systemctl enable --now agents.service
systemctl enable --now caddy.service

# Restart SSM agent after Docker has set up its iptables rules, so the agent
# registers against the final network state rather than racing with Docker on boot.
systemctl restart amazon-ssm-agent
echo "DONE USER DATA"
