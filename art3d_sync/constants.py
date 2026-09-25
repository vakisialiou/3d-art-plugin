# 3d-art-api's default port (src/main.ts: process.env.PORT ?? 3500)
SERVER_URL = "http://localhost:3500"

# Matches the api gateway's own DEV_TOKEN fallback (blender-sync.gateway.ts)
# and the web client's constant (blender-sync.client.ts) — a stand-in for
# real auth, not yet implemented.
DEV_TOKEN = "art3d-dev-token"
