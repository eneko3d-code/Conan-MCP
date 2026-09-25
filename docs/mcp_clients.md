# Guía de Conexión de Clientes MCP: ConanMCP

Esta guía detalla la configuración paso a paso para conectar diversos clientes y agentes de Inteligencia Artificial al servidor **ConanMCP** ejecutándose en el Conan Exiles Enhanced DevKit (`http://127.0.0.1:8123/mcp`).

---

## 1. Google Antigravity

Google Antigravity soporta servidores MCP para dotar al agente de herramientas contextuales de proyecto.

### Configuración en el Espacio de Trabajo
Añade la siguiente definición a la configuración de MCP de tu agente o en el archivo de configuración global:

```json
{
  "mcpServers": {
    "conan-devkit": {
      "url": "http://127.0.0.1:8123/mcp",
      "transport": "http"
    }
  }
}
```

Una vez configurado, Antigravity descubrirá automáticamente las 38 herramientas del Conan DevKit y las tendrá disponibles durante las sesiones de pair programming.

---

## 2. Cursor IDE

Cursor cuenta con soporte nativo para Model Context Protocol (MCP) en su versión moderna.

### Configuración mediante Interfaz Gráfica
1. Abre **Cursor Settings** (`Ctrl + ,` o `File` -> `Preferences` -> `Cursor Settings`).
2. Navega a la sección **Features** -> **MCP Servers**.
3. Haz clic en **Add New MCP Server**.
4. Rellena los datos:
   - **Name:** `ConanDevKit`
   - **Type:** `HTTP` o `SSE`
   - **URL:** `http://127.0.0.1:8123/mcp`

### Configuración mediante `mcp.json`
Si configuras el archivo de configuración de MCP directamente (por ejemplo en `.cursor/mcp.json` o en la configuración global de Cursor):

```json
{
  "mcpServers": {
    "conan-devkit": {
      "url": "http://127.0.0.1:8123/mcp"
    }
  }
}
```

Si tu versión de Cursor requiere transporte STDIO por comando, utiliza el script puente proporcionado en [docs/mcp_stdio_bridge.py](mcp_stdio_bridge.py):

```json
{
  "mcpServers": {
    "conan-devkit": {
      "command": "python",
      "args": [
        "C:/Program Files/Epic Games/CEUE5Devkit/UE4/Plugins/ConanMCP/docs/mcp_stdio_bridge.py"
      ]
    }
  }
}
```

---

## 3. Claude Code y Claude Desktop

### Claude Desktop
En Windows, abre el archivo de configuración:
`%APPDATA%\Claude\claude_desktop_config.json`

Añade el servidor:
```json
{
  "mcpServers": {
    "conan-devkit": {
      "command": "python",
      "args": [
        "C:\\Program Files\\Epic Games\\CEUE5Devkit\\UE4\\Plugins\\ConanMCP\\docs\\mcp_stdio_bridge.py"
      ]
    }
  }
}
```

### Claude Code CLI
Puedes añadir el servidor mediante el comando interactivo de la CLI:
```bash
claude mcp add conan-devkit python "C:/Program Files/Epic Games/CEUE5Devkit/UE4/Plugins/ConanMCP/docs/mcp_stdio_bridge.py"
```

---

## 4. Agentes Personalizados / Codex / REST Directo

El servidor ConanMCP responde al protocolo estándar **JSON-RPC 2.0** a través de peticiones HTTP `POST`. Cualquier cliente HTTP estándar o script puede interactuar directamente con el editor.

### Flujo de Handshake Estándar (MCP 2024-11-05)

#### Paso 1: Handshake `initialize`
**Request:**
```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:8123
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "my-ai-agent",
      "version": "1.0.0"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
      "name": "conan-devkit-mcp",
      "version": "1.0.0"
    },
    "capabilities": {
      "tools": {
        "listChanged": false
      }
    }
  }
}
```

#### Paso 2: Notificación `notifications/initialized`
```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:8123
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

#### Paso 3: Listar Herramientas `tools/list`
```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:8123
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}
```

#### Paso 4: Ejecutar una Herramienta `tools/call`
```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:8123
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_editor_status",
    "arguments": {}
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"engine_version\": \"5.8.2-377096+++exiles+release\", \"devkit\": \"Conan Exiles Enhanced DevKit\", \"is_editor_active\": true, \"current_world\": \"None\", \"current_map_path\": \"None\"}"
      }
    ]
  }
}
```

---

## 5. Script Puente Universal STDIO a HTTP (`mcp_stdio_bridge.py`)

Para clientes MCP que solo implementan transporte a través de procesos locales con entrada/salida estándar (STDIO), el archivo [`docs/mcp_stdio_bridge.py`](mcp_stdio_bridge.py) reenvía de forma asíncrona cada mensaje JSON-RPC al endpoint HTTP local `127.0.0.1:8123/mcp`.
