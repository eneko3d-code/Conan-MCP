# Protocolo de Pruebas y Verificación: ConanMCP

Este documento describe la suite de pruebas automatizadas, las pruebas manuales y los procedimientos de verificación para el plugin **ConanMCP** en el Conan Exiles Enhanced DevKit.

---

## 1. Estrategia de Pruebas

El sistema de pruebas de ConanMCP valida cuatro capas críticas:
1. **Conectividad y Red:** Arranque del servidor HTTP en `127.0.0.1:8123`, respuestas a peticiones GET de estado y manejo de sockets.
2. **Cumplimiento del Protocolo MCP (2024-11-05):** Verificación del handshake de inicialización, notificaciones, `ping`, listado de herramientas (`tools/list`) y ejecución (`tools/call`).
3. **Validación del Catálogo de Herramientas:** Verificación de la presencia, esquemas JSON y funcionalidad de las **38 herramientas**.
4. **Manejo de Errores y Robustez:** Validación de respuestas JSON-RPC 2.0 ante métodos desconocidos (`-32601`), herramientas no existentes y ciclo de vida de reinicio del servidor.

---

## 2. Suite Automatizada de Pruebas (`test_mcp_server.py`)

La suite de pruebas automatizada se encuentra en:
`C:\Program Files\Epic Games\CEUE5Devkit\UE4\Plugins\ConanMCP\docs\test_mcp_server.py`

### Cómo Ejecutar la Suite
Se recomienda ejecutar la suite con el propio intérprete de Python 3.11 distribuido con el DevKit:

```powershell
& "C:\Program Files\Epic Games\CEUE5Devkit\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" "C:\Program Files\Epic Games\CEUE5Devkit\UE4\Plugins\ConanMCP\docs\test_mcp_server.py"
```

### Detalle de los 11 Casos de Prueba Ejecutados

| ID | Prueba | Descripción | Resultado Verificado |
|---|---|---|---|
| **01** | `Server Boot` | Arranque del servidor en hilo secundario y escucha en puerto 8123. | ✅ PASSED |
| **02** | `GET /mcp` | Verificación del endpoint HTTP informativo para monitorización rápida. | ✅ PASSED |
| **03** | `initialize` | Handshake inicial de protocolo MCP con capacidades y datos de versión. | ✅ PASSED |
| **04** | `notifications/initialized` | Confirmación asíncrona de inicialización enviada por el cliente. | ✅ PASSED |
| **05** | `ping` | Verificación de latencia y estado activo mediante método estándar MCP. | ✅ PASSED |
| **06** | `tools/list` | Recuperación y validación del esquema de las 38 herramientas requeridas. | ✅ PASSED |
| **07** | `tools/call (get_editor_status)` | Ejecución de consulta de estado del motor y DevKit. | ✅ PASSED |
| **08** | `tools/call (get_selected_actors)` | Ejecución de consulta de selección de actores en la escena. | ✅ PASSED |
| **09** | `Error -32601 (Invalid Method)` | Comprobación de respuesta correcta ante RPC inexistente. | ✅ PASSED |
| **10** | `Error -32601 (Invalid Tool)` | Comprobación de denegación ante herramienta no registrada. | ✅ PASSED |
| **11** | `Server Lifecycle (Stop/Restart)` | Detención completa, liberación de socket TCP y reanudación limpia. | ✅ PASSED |

### Registro de Ejecución Real
```text
============================================================
ConanMCP Automated Protocol & Tool Verification Test
============================================================
[1] Starting ConanMCP server on 127.0.0.1:8123...
[ConanMCP] Registered 38 tools for ConanMCP
[ConanMCP] MCP server started on 127.0.0.1:8123 (Endpoint: /mcp)
[2] Testing HTTP GET endpoint...
    GET Response: {'service': 'ConanMCP', 'version': '1.0.0', 'protocol': 'MCP / JSON-RPC 2.0', 'status': 'running', 'registered_tools': 38}
    PASSED: GET endpoint
[3] Testing 'initialize'...
    initialize Response: {
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
    PASSED: initialize
[4] Testing 'notifications/initialized'...
[ConanMCP] Client initialized
    PASSED: notifications/initialized
[5] Testing 'ping'...
    PASSED: ping
[6] Testing 'tools/list'...
    Total registered tools: 38
    All 38 required tools verified in tools/list schema!
    PASSED: tools/list
[7] Testing tools/call 'get_editor_status'...
[ConanMCP] Tool called: get_editor_status
[ConanMCP] Tool completed in 0.0 ms
    Status Result: {'engine_version': '5.8.2-377096+++exiles+release', 'devkit': 'Conan Exiles Enhanced DevKit', 'is_editor_active': True, 'current_world': 'None', 'current_map_path': 'None'}
    PASSED: tools/call get_editor_status
[8] Testing tools/call 'get_selected_actors'...
[ConanMCP] Tool called: get_selected_actors
[ConanMCP] Tool completed in 0.0 ms
    PASSED: tools/call get_selected_actors
[9] Testing invalid method error handling...
    Expected Error Caught: {'code': -32601, 'message': "Method 'non_existent_method' not found"}
    PASSED: Method not found (-32601)
[10] Testing non-existent tool error handling...
    Expected Error Caught: {'code': -32601, 'message': "Tool 'non_existent_tool_xyz' not found"}
    PASSED: Tool not found (-32601)
[11] Testing server Stop and Restart...
[ConanMCP] MCP server stopped
    Server stopped successfully (connection refused as expected)
[ConanMCP] Registered 38 tools for ConanMCP
[ConanMCP] MCP server started on 127.0.0.1:8123 (Endpoint: /mcp)
    Server restarted and responding successfully!
[ConanMCP] MCP server stopped
    PASSED: Server start/stop lifecycle

============================================================
ALL 11 AUTOMATED MCP PROTOCOL TESTS PASSED SUCCESSFULLY!
============================================================
```

---

## 3. Pruebas Manuales con el Editor Abierto

Cuando el Conan Exiles DevKit esté ejecutándose en vivo, puedes realizar las siguientes validaciones interactivas:

### Prueba A: Verificar el Output Log
En la pestaña **Output Log** de Unreal Engine, busca las líneas con categoría `LogConanMCP`:
```
LogConanMCP: Starting ConanMCP auto-initializer...
LogConanMCP: Registered 38 tools for ConanMCP
LogConanMCP: MCP server started on 127.0.0.1:8123 (Endpoint: /mcp)
```

### Prueba B: Consultar Actores en Vivo con PowerShell
En una consola externa:
```powershell
$body = @{
    jsonrpc = "2.0"
    id = 1
    method = "tools/call"
    params = @{
        name = "list_level_actors"
        arguments = @{
            max_results = 5
        }
    }
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8123/mcp" -Method Post -Body $body -ContentType "application/json"
$response.result.content[0].text | ConvertFrom-Json
```

### Prueba C: Previsualización de Partículas en Actor
Invoca `preview_particle_on_actor` especificando un actor existente en la escena y un sistema de partículas de Conan Exiles. Comprueba que el efecto visual se instancia inmediatamente en el visor del editor y que pulsar **`Ctrl + Z`** revierte la operación limpiamente.
