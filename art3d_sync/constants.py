# 3d-art-api's default port (src/main.ts: process.env.PORT ?? 3500)
SERVER_URL = "http://localhost:3500"

# Must match the DEV_TOKEN fallback in 3d-art-api's blender-sync.gateway.ts and
# 3d-art-web's blender-sync.client.ts — stand-in for real auth.
DEV_TOKEN = "art3d-dev-token"
