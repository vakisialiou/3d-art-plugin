from . import bl_info

# The server when neither ART3D_SERVER_URL nor the developer preference names
# another one (3d-art-api's default port).
DEFAULT_SERVER_URL = "http://localhost:3500"

# The editor↔server contract version: a server on another version answers
# 426 and the panel asks for an add-on update.
PROTOCOL_VERSION = 1

# Editor family, as the server lists devices and editors.
CLIENT_KIND = "blender"

PLUGIN_VERSION = ".".join(str(part) for part in bl_info["version"])
