# Modelo de Seguridad y Directivas de Ejecución: ConanMCP

El plugin **ConanMCP** fue diseñado bajo el principio de **Mínimo Privilegio** y **Defensa en Profundidad** para permitir que agentes de Inteligencia Artificial interactúen con el editor de Unreal Engine sin poner en riesgo la integridad del proyecto, el código fuente o el sistema operativo del usuario.

---

## 1. Principios Fundamentales de Seguridad

### A. Prohibición Absoluta de Ejecución Arbitraria (No Remote Code Execution)
- **Sin Shells:** El servidor no implementa ni expone ninguna herramienta que permita invocar PowerShell, CMD, Bash o comandos de sistema operativo.
- **Sin Carga Arbitraria de DLLs:** No se permite cargar librerías dinámicas o binarios externos a petición del cliente MCP.
- **Lista Blanca Estricta:** Solo se ejecutan los manejadores de herramientas explícitamente registrados en la instancia de `ToolRegistry`. Cualquier intento de invocar un método o herramienta no registrada produce un error JSON-RPC `-32601 (Method not found)`.

### B. Aislamiento en Interfaz Local (Loopback Only)
- Por diseño, el socket HTTP escucha exclusivamente en `127.0.0.1`.
- No se expone el puerto `8123` a la red de área local (LAN) ni a Internet. Esto impide que actores externos en la misma red puedan enviar comandos al editor abierto.

### C. Validación y Saneamiento de Rutas (Path Traversal Prevention)
- Se verifica que todos los argumentos que representen rutas a paquetes o assets pertenezcan a los montajes válidos del motor (`/Game/`, `/Engine/`, `/ConanSandbox/`).
- Se rechazan terminantemente secuencias de escape de directorio (`..`, `//`, `\` en rutas de paquetes) y extensiones de archivos ejecutables (`.exe`, `.dll`, `.bat`, `.cmd`, `.ps1`, `.vbs`).

---

## 2. Clasificación de Herramientas y Matriz de Autorización

Cada una de las 38 herramientas del servidor tiene asignado un nivel de seguridad inmutable:

| Nivel de Seguridad | Descripción | Soporte de Undo/Redo | Estado por Defecto |
|---|---|---|---|
| **`READ_ONLY`** | Herramientas de consulta pura, inspección de propiedades, búsqueda en AssetRegistry y lectura de DataTables. No alteran el estado en disco ni en memoria. | N/A | **Permitido** |
| **`SAFE_WRITE`** | Herramientas que modifican actores en el nivel, guardan el nivel o añaden componentes de previsualización temporal. | **Obligatorio (`Ctrl+Z`)** | **Permitido** (conmutable con `ENABLE_WRITE_TOOLS`) |
| **`DESTRUCTIVE`** | Herramientas que eliminan assets permanentemente, vacían niveles o borran ficheros de proyecto. | Parcial | **Desactivado** (`ENABLE_DESTRUCTIVE_TOOLS = False`) |

### Manejo de Violaciones de Seguridad
Si un cliente MCP intenta ejecutar una herramienta que requiere un permiso desactivado (por ejemplo, una herramienta de escritura cuando `ENABLE_WRITE_TOOLS = False`), el servidor deniega la ejecución de inmediato y responde con el error JSON-RPC estándar:
```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "error": {
    "code": -32001,
    "message": "Security Error: Tool 'set_actor_transform' requires SAFE_WRITE permission which is currently disabled on this ConanMCP server."
  }
}
```

---

## 3. Soporte Transaccional de Editor (`Ctrl+Z` / Deshacer)

Toda mutación de actor o escena ejecutada por una herramienta clasificada como `SAFE_WRITE` está obligada a registrarse dentro del sistema de historial del editor de Unreal Engine:

- **En C++:**
  ```cpp
  FScopedTransaction Transaction(LOCTEXT("ConanMCPAction", "ConanMCP Tool Execution"));
  TargetActor->Modify();
  TargetActor->SetActorLocation(NewLocation);
  ```
- **En Python:**
  ```python
  with unreal.ScopedEditorTransaction("ConanMCP Tool Execution"):
      actor.set_actor_location(new_loc, sweep=False, teleport=True)
  ```
Esto garantiza que si una IA realiza un cambio de posición, rotación o ajuste no deseado, el desarrollador humano en el editor puede simplemente pulsar **`Ctrl + Z`** para deshacer la acción de forma instantánea.

---

## 4. Protección de Memoria y Rendimiento del DevKit

El Conan Exiles Enhanced DevKit contiene cientos de gigabytes y decenas de miles de assets. Una consulta imprudente podría congelar la máquina o provocar un fallo por falta de memoria RAM (*Out of Memory crash*).

Para evitar esto:
1. **Búsquedas Ligeras en AssetRegistry:** Herramientas como `find_assets`, `find_conan_assets` y `find_blueprint` operan sobre metadatos cacheados de `FAssetData`. No cargan el objeto `UObject` ni sus texturas/mallas a memoria RAM.
2. **Paginación y Límites Forzados:**
   - Parámetro `max_results`: Valor por defecto `50`.
   - Límite absoluto superior: `500` resultados por consulta.
   - Paginación obligatoria (`offset` y `limit`) en tablas de datos voluminosas (`list_datatable_rows`).

---

## 5. Sincronización y Watchdog del Game Thread

Unreal Engine no permite alterar actores, mundos o transacciones fuera del **Game Thread** (hilo principal). Las peticiones HTTP que llegan al servidor MCP se reciben en hilos de sockets de fondo (*Background Socket Threads*).

Para salvaguardar la estabilidad:
- Todas las operaciones que tocan objetos de Unreal Engine son despachadas de forma segura al Game Thread mediante `AsyncTask(ENamedThreads::GameThread)` o la cola de ejecución del editor.
- Se implementa un **Watchdog Timeout de 30 segundos**: si por alguna razón una operación queda bloqueada esperando un recurso, el temporizador expira y responde con error de timeout al cliente en lugar de congelar indefinidamente el proceso del editor.
