# Guía de Configuración: ConanMCP

Esta guía detalla todas las opciones de configuración disponibles para el servidor **ConanMCP**, tanto en el runtime embebido como en el módulo C++ nativo.

---

## 1. Parámetros de Red y Conectividad

Por defecto, ConanMCP se enlaza a la interfaz loopback local para garantizar la máxima seguridad:

| Parámetro | Valor por Defecto | Descripción |
|---|---|---|
| **Host / Bind Address** | `127.0.0.1` | Dirección IP de escucha del servidor. Por seguridad, no debe exponerse a interfaces públicas (`0.0.0.0`) sin mecanismos adicionales de cifrado y autenticación. |
| **Port** | `8123` | Puerto TCP en el que escucha el endpoint HTTP. |
| **Endpoint Path** | `/mcp` | Ruta del endpoint HTTP donde se procesan las peticiones JSON-RPC 2.0 y el handshake GET. |

---

## 2. Parámetros de Seguridad y Límites de Ejecución

Para prevenir sobrecarga de memoria en proyectos con cientos de miles de assets como Conan Exiles, y para evitar mutaciones no deseadas del mapa, se configuran las siguientes directivas:

```python
# Variables en Content/Python/conan_mcp_server.py
BIND_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 8123
ENDPOINT_PATH = "/mcp"

# Banderas de control de operaciones
ENABLE_WRITE_TOOLS = True          # Permite herramientas de tipo SAFE_WRITE (con transacciones Undo)
ENABLE_DESTRUCTIVE_TOOLS = False   # Bloquea de forma estricta el borrado de assets o niveles
ENABLE_LOGGING = True              # Registra las llamadas en el Output Log de Unreal
MAX_RESULTS = 50                   # Límite por defecto para consultas AssetRegistry y actores
```

### Explicación de Banderas de Seguridad:
1. `ENABLE_WRITE_TOOLS` (por defecto `True`):
   - Cuando está activo, permite herramientas como `set_actor_transform`, `save_current_level`, `preview_particle_on_actor` y `remove_preview_particle`.
   - Si se cambia a `False`, el servidor responderá con código de error JSON-RPC `-32001 (Security Error)` a cualquier intento de modificación, comportándose estrictamente en modo solo lectura.
2. `ENABLE_DESTRUCTIVE_TOOLS` (por defecto `False`):
   - Protege los activos del proyecto contra eliminaciones masivas o irreparables. Ninguna IA externa puede destruir assets salvo que el desarrollador cambie explícitamente este valor.
3. `MAX_RESULTS` (por defecto `50`):
   - Evita que consultas globales sobre `/Game/` devuelvan 100,000 registros de golpe, lo que causaría bloqueos o respuestas HTTP de cientos de megabytes.

---

## 3. Variables de Entorno (Opcional)

Puedes sobreescribir la configuración sin tocar el código asignando variables de entorno antes de lanzar el DevKit:

- `CONAN_MCP_PORT`: Define un puerto alternativo (ej. `8125`).
- `CONAN_MCP_HOST`: Define la dirección de escucha (ej. `127.0.0.1`).
- `CONAN_MCP_READONLY`: Si se define como `1`, desactiva automáticamente las herramientas de escritura.

---

## 4. Configuración C++ Nativa (`UConanMCPSettings`)

En compilaciones que utilicen los módulos C++, los parámetros se gestionan a través del sistema de configuración de Unreal Engine en:
`Project Settings` -> `Plugins` -> `Conan MCP`

Propiedades expuestas en C++:
```cpp
UPROPERTY(config, EditAnywhere, Category = "Server")
FString BindAddress = TEXT("127.0.0.1");

UPROPERTY(config, EditAnywhere, Category = "Server")
int32 Port = 8123;

UPROPERTY(config, EditAnywhere, Category = "Server")
bool bAutoStartServer = true;

UPROPERTY(config, EditAnywhere, Category = "Security")
bool bAllowWriteTools = true;

UPROPERTY(config, EditAnywhere, Category = "Security")
bool bAllowDestructiveTools = false;

UPROPERTY(config, EditAnywhere, Category = "Limits")
int32 MaxAssetQueryResults = 50;
```

---

## 5. Comandos de Consola del Editor

Desde la consola integrada de Unreal Engine (tecla `~` o la barra inferior de comandos del editor), se encuentran disponibles los siguientes comandos:

- `ConanMCP.Start [Puerto]`: Inicia el servidor manualmente. Si se especifica un número de puerto, sobreescribe el puerto configurado.
- `ConanMCP.Stop`: Detiene el servidor y libera el socket TCP.
- `ConanMCP.Status`: Muestra en el Output Log el estado actual, puerto, número de clientes y herramientas registradas.
- `ConanMCP.ListTools`: Imprime en el Output Log el listado completo de las 38 herramientas con su nivel de seguridad.
- `ConanMCP.ReloadTools`: Recarga y vuelve a registrar todas las definiciones de herramientas.

---

## 6. Panel de Control Slate (Dashboard en el Editor)

Para desarrolladores que prefieran interfaz gráfica dentro de Unreal Engine:
1. Dirígete al menú superior del editor: `Window` -> `Developer Tools` -> `Conan MCP Dashboard`.
2. El dashboard permite:
   - Visualizar el estado de conexión (Running / Stopped) con indicador cromático.
   - Ajustar el puerto de escucha.
   - Botones interactivos para **Iniciar Servidor** y **Detener Servidor**.
   - Tabla interactiva con el listado de herramientas activas y sus categorías.
