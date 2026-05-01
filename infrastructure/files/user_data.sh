#!/bin/bash
set -euo pipefail

exec > >(tee /var/log/user-data-debug.log | logger -t user-data ) 2>&1
set -x
echo "STARTING USER DATA"

dnf install -y docker
systemctl enable --now docker

mkdir -p /opt/agents/data
chown 65532:65532 /opt/agents/data

cat > /etc/systemd/system/agents.service <<EOF_UNIT
${service_content}
EOF_UNIT

systemctl daemon-reload
systemctl enable --now agents.service

# Restart SSM agent after Docker has set up its iptables rules, so the agent
# registers against the final network state rather than racing with Docker on boot.
systemctl restart amazon-ssm-agent
echo "DONE USER DATA"
