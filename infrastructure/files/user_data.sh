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

# Quoted delimiter, like the unit below it. Terraform interpolates $${service_content}
# before this script ever runs, so the unit's text is inlined here — and an unquoted
# delimiter would leave bash to command-substitute the `$(aws ssm get-parameter ...)`
# calls while *writing* the file, baking plaintext secrets into a world-readable unit.
# Fetching them at start, which is what the unit documents, needs the `$(...)` to survive
# into the file verbatim.
cat > /etc/systemd/system/agents.service <<'EOF_UNIT'
${service_content}
EOF_UNIT

cat > /etc/systemd/system/agents-migrate.service <<'EOF_UNIT'
${migrate_service_content}
EOF_UNIT

cat > /etc/systemd/system/tailscale-agents.service <<'EOF_UNIT'
${tailscale_service_content}
EOF_UNIT

systemctl daemon-reload

# Enabled but not started here: agents.service Requires= it, so starting the app pulls
# the migration in and orders it first. Starting it separately would just run it twice.
systemctl enable agents-migrate.service

# Joined before the app is started, not after. This is the only route a user has into the
# box, and starting the app is the step most likely to fail — a bad image tag, or a
# migration that will not apply. Ordered after it, under `set -e`, such a failure aborted
# the script *here* and the node never joined the tailnet at all, so a database problem
# presented as a machine that had vanished. Going first costs nothing: `tailscale serve`
# only writes proxy configuration, so it answers 502 until the app is listening.
systemctl enable --now tailscale-agents.service

# Deliberately not fatal on its own. The health gate below is what decides whether the
# boot was good; letting the script past this point means the SSM agent is restarted and
# the failure is reported by that gate, rather than the script dying with the instance
# half-configured and unreachable.
systemctl enable --now agents.service || echo "agents.service failed to start" >&2

# Restart SSM agent after Docker has set up its iptables rules, so the agent
# registers against the final network state rather than racing with Docker on boot.
# Ahead of the health gate, so that a failing app still leaves the box reachable by the
# path used to debug it.
systemctl restart amazon-ssm-agent

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
curl -fsS "http://127.0.0.1:${app_port}/health" >/dev/null || { echo "app failed to become healthy" >&2; exit 1; }

echo "DONE USER DATA"
