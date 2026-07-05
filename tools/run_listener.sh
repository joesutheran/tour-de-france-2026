#!/bin/bash
# Launches the TdF webhook listener. Sources tools/.webhook.env (gitignored) so the
# shared secret never lands in version control. Kept alive by com.tdf2026.webhook.plist.
set -u
cd "$(dirname "$0")/.." || exit 1
[ -f tools/.webhook.env ] && set -a && . tools/.webhook.env && set +a
exec /usr/bin/python3 tools/webhook_listener.py
