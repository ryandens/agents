#!/bin/bash
set -euo pipefail

# Secret rotation triggers: changing either hash causes user_data_replace_on_change to
# replace the instance. They are only ever comments — the values are read from SSM at
# runtime, so these lines exist purely to make the rendered user_data differ on rotation.
# GOOGLE_CLIENT_SECRET_HASH=${google_client_secret_hash}
# SESSION_SECRET_HASH=${session_secret_hash}

exec > >(tee /var/log/user-data-debug.log | logger -t user-data ) 2>&1
set -x
echo "STARTING USER DATA"

dnf install -y docker
systemctl enable --now docker

# Written straight to yum.repos.d rather than via `dnf config-manager`, which lives in an
# optional plugin package this AMI does not guarantee.
curl -fsSL https://pkgs.tailscale.com/stable/amazon-linux/2023/tailscale.repo \
    -o /etc/yum.repos.d/tailscale.repo
dnf install -y tailscale
systemctl enable --now tailscaled

mkdir -p /opt/agents/data
chown 65532:65532 /opt/agents/data

cat > /etc/systemd/system/agents.service <<EOF_UNIT
${service_content}
EOF_UNIT

cat > /etc/systemd/system/tailscale-agents.service <<EOF_UNIT
${tailscale_service_content}
EOF_UNIT

systemctl daemon-reload
systemctl enable --now agents.service

# Started after the app so `tailscale serve` has something behind it the moment the node
# appears on the tailnet. The app binds loopback only, so this is the sole way in.
systemctl enable --now tailscale-agents.service

# Wait for the app to answer before declaring the boot good. Nothing gates traffic now
# that the ALB's health check is gone, so a failure here is the signal that used to be an
# unhealthy target: visible in the user-data log rather than in the console.
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${app_port}/health" >/dev/null; then
        echo "app healthy"
        break
    fi
    sleep 2
done

# Restart SSM agent after Docker has set up its iptables rules, so the agent
# registers against the final network state rather than racing with Docker on boot.
systemctl restart amazon-ssm-agent
echo "DONE USER DATA"
