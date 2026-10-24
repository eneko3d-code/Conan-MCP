# Modelo de Seguridad y Directivas de Ejecución: ConanMCP

El plugin **ConanMCP** fue diseñado bajo el principio de **Mínimo Privilegio** y **Defensa en Profundidad** para permitir que agentes de Inteligencia Artificial interactúen con el editor de Unreal Engine sin poner en riesgo la integridad del proyecto, el código fuente o el sistema operativo del usuario.

---

## 1. Principios Fundamentales de Seguridad

### A. Ejecución arbitraria: solo bajo opt-in explícito
- **`execute_python` es `DESTRUCTIVE` y está desactivada por defecto.** Ejecuta Python sin sandbox, por lo que solo se habilita con `CONAN_MCP_ENABLE_DESTRUCTIVE=1`. Activarla equivale a dar control total del equipo al cliente MCP: úsala únicamente con un token (`CONAN_MCP_TOKEN`) y clientes de confianza.
- **Sin shells dedicados:** El resto de herramientas no invocan PowerShell, CMD, Bash ni comandos de sistema operativo.
- **Sin Carga Arbitraria de DLLs:** No se permite cargar librerías dinámicas o binarios externos a petición del cliente MCP.
- **Lista Blanca Estricta:** Solo se ejecutan los manejadores de herramientas explícitamente registrados en la instancia de `ToolRegistry`. Cualquier intento de invocar un método o herramienta no registrada produce un error JSON-RPC `-32601 (Method not found)`.

### B. Aislamiento en Interfaz Local (Loopback Only)
- Por diseño, el socket HTTP escucha exclusivamente en `127.0.0.1`.
- Se rechazan (403) las peticiones con cabecera `Host` u `Origin` no locales: protege contra DNS rebinding y contra páginas web maliciosas que intenten llamar al servidor desde el navegador. No se emite `Access-Control-Allow-Origin: *`.
- Token Bearer opcional (`CONAN_MCP_TOKEN`), comparado en tiempo constante.
- No se expone el puerto `8123` a la red de área local (LAN) ni a Internet. Esto impide que actores externos en la misma red puedan enviar comandos al editor abierto.

### C. Validación y Saneamiento de Rutas (Path Traversal Prevention)
- El servidor Python valida (`validate_package_path`) los argumentos `package_path`, `asset_path` y `path` de **todas** las herramientas, además del recurso `conan://asset/{package_path}`: deben empezar por `/Game`, `/Engine` o `/ConanSandbox`.
- Se rechazan secuencias de escape de directorio (`..`, `//`, `\`) y bytes nulos.

---

## 2. Clasificación de Herramientas y Matriz de Autorización

Cada una de las 128 herramientas del servidor tiene asignado un nivel de seguridad inmutable:

| Nivel de Seguridad | Descripción | Soporte de Undo/Redo | Estado por Defecto |
|---|---|---|---|
| **`READ_ONLY`** | Herramientas de consulta pura, inspección de propiedades, búsqueda en AssetRegistry y lectura de DataTables. No alteran el estado en disco ni en memoria. | N/A | **Permitido** |
| **`SAFE_WRITE`** | Herramientas que modifican actores en el nivel, guardan el nivel o añaden componentes de previsualización temporal. | **Obligatorio (`Ctrl+Z`)** | **Permitido** (conmutable con `ENABLE_WRITE_TOOLS`) |
| **`DESTRUCTIVE`** | Herramientas con efectos no acotados o irreversibles (`execute_python`, `delete_asset`). | Parcial | **Desactivado** (activar con `CONAN_MCP_ENABLE_DESTRUCTIVE=1`) |

### Manejo de Violaciones de Seguridad
Si un cliente MCP intenta ejecutar una herramienta que requiere un permiso desactivado (por ejemplo, una herramienta de escritura con `CONAN_MCP_READONLY=1`), el servidor deniega la ejecución y responde con un resultado MCP `isError: true`:
```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "result": {
    "content": [{"type": "text", "text": "Security error: SAFE_WRITE tools are disabled"}],
    "isError": true
  }
}
```

---

### Herramientas de edición masiva (2.0)
- `delete_actors`, `spawn_actors_batch`, `scatter_actors`, `snap_actors_to_ground`, `duplicate_actors`, etc. son `SAFE_WRITE`: se ejecutan en **una sola transacción** (se deshacen con `undo` o Ctrl+Z), aceptan `dry_run` y tienen un límite por llamada (`max_count`, tope duro `CONAN_MCP_MAX_ACTORS`, 200 por defecto).
- `delete_actors` nunca toca Landscape, WorldSettings, foliage ni otros actores críticos salvo `allow_protected=true`, y exige un filtro o una lista explícita.
- Las DataTables fuera de `/Game/Mods` son de solo lectura salvo `allow_base_game_table=true`.
- Los ficheros (heightmaps, capturas, exportaciones) solo se leen y escriben en `<Proyecto>/Saved/ConanMCP/` y solo con nombres de fichero simples.

### Integración Tripo AI (2.2)
- El servidor solo hace conexiones salientes a la API de Tripo y a sus hosts de descarga (HTTPS, lista `CONAN_MCP_TRIPO_DOWNLOAD_HOSTS`), y solo si existe la variable `TRIPO_API_KEY`.
- La clave nunca se guarda en disco ni aparece en respuestas o logs.
- Toda tarea que gasta créditos comprueba primero el saldo y requiere `confirm_spend=true`. Existe un tope por sesión (`CONAN_MCP_TRIPO_BUDGET`). Tras el error 2010 (sin créditos) no se reintenta nunca.
- Las subidas solo admiten ficheros de `Saved/ConanMCP` y las importaciones solo se crean en `/Game/Mods/`.

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
- Se implementa un **Watchdog Timeout de 30 segundos** (configurable con `CONAN_MCP_TIMEOUT`; las tareas expiradas se cancelan y no se ejecutan después): si por alguna razón una operación queda bloqueada esperando un recurso, el temporizador expira y responde con error de timeout al cliente en lugar de congelar indefinidamente el proceso del editor.
