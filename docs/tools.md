# Catálogo Completo de Herramientas: ConanMCP

El plugin **ConanMCP** expone un catálogo de **38 herramientas** agrupadas en 8 dominios funcionales. Cada herramienta define su esquema JSON Schema para validación de argumentos y su clasificación de seguridad.

---

## Índice de Categorías
1. [Herramientas de Editor (4)](#1-herramientas-de-editor)
2. [Herramientas de Actores (6)](#2-herramientas-de-actores)
3. [Herramientas de Assets (6)](#3-herramientas-de-assets)
4. [Herramientas de Esqueletos y Mallas (4)](#4-herramientas-de-esqueletos-y-mallas)
5. [Herramientas de Blueprints (4)](#5-herramientas-de-blueprints)
6. [Herramientas de Tablas de Datos (DataTables) (4)](#6-herramientas-de-tablas-de-datos-datatables)
7. [Herramientas de Partículas y VFX (5)](#7-herramientas-de-partículas-y-vfx)
8. [Herramientas Específicas de Conan Exiles (5)](#8-herramientas-específicas-de-conan-exiles)

---

## 1. Herramientas de Editor

### `get_editor_status`
- **Categoría:** Editor
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve el estado operativo del editor, versión del motor, rama y nombre del mapa cargado.
- **Esquema de Entrada:**
  ```json
  { "type": "object", "properties": {} }
  ```
- **Ejemplo de Retorno:**
  ```json
  {
    "engine_version": "5.8.2-377096+++exiles+release",
    "devkit": "Conan Exiles Enhanced DevKit",
    "is_editor_active": true,
    "current_world": "ConanSandbox",
    "current_map_path": "/Game/Maps/ConanSandbox"
  }
  ```

### `get_current_level`
- **Categoría:** Editor
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve la ruta del nivel activo en el editor, si tiene cambios sin guardar (`is_dirty`) y el recuento de actores.
- **Esquema de Entrada:**
  ```json
  { "type": "object", "properties": {} }
  ```

### `save_current_level`
- **Categoría:** Editor
- **Seguridad:** `SAFE_WRITE`
- **Descripción:** Guarda en disco el nivel actualmente activo y sus paquetes asociados.
- **Esquema de Entrada:**
  ```json
  { "type": "object", "properties": {} }
  ```

### `get_selected_actors`
- **Categoría:** Editor
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve la lista de actores seleccionados actualmente en el World Outliner del editor, incluyendo nombres, clases y coordenadas.
- **Esquema de Entrada:**
  ```json
  { "type": "object", "properties": {} }
  ```

---

## 2. Herramientas de Actores

### `list_level_actors`
- **Categoría:** Actors
- **Seguridad:** `READ_ONLY`
- **Descripción:** Lista los actores presentes en el nivel actual con filtrado opcional por clase, nombre o tag.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "class_filter": { "type": "string", "description": "Filtro por clase (ej: StaticMeshActor, PointLight)" },
      "name_filter": { "type": "string", "description": "Subcadena en el nombre o label" },
      "tag_filter": { "type": "string", "description": "Tag de actor" },
      "max_results": { "type": "number", "description": "Límite de resultados (default 50, max 500)" }
    }
  }
  ```

### `find_actor`
- **Categoría:** Actors
- **Seguridad:** `READ_ONLY`
- **Descripción:** Busca un actor en el nivel por nombre exacto o etiqueta (Actor Label).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Nombre o label del actor" }
    },
    "required": ["actor"]
  }
  ```

### `get_actor_info`
- **Categoría:** Actors
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve información completa de un actor: clase, ubicación en el Outliner, tags de gameplay y jerarquía de componentes adjuntos.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Nombre o label del actor" }
    },
    "required": ["actor"]
  }
  ```

### `get_actor_transform`
- **Categoría:** Actors
- **Seguridad:** `READ_ONLY`
- **Descripción:** Obtiene las coordenadas espaciales mundiales (`location`, `rotation` en Pitch/Yaw/Roll, y `scale`).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Nombre o label del actor" }
    },
    "required": ["actor"]
  }
  ```

### `set_actor_transform`
- **Categoría:** Actors
- **Seguridad:** `SAFE_WRITE`
- **Descripción:** Modifica la posición, rotación o escala de un actor. Se registra automáticamente en el historial de Deshacer (`Ctrl+Z`).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Nombre del actor" },
      "location": {
        "type": "object",
        "properties": { "x": { "type": "number" }, "y": { "type": "number" }, "z": { "type": "number" } }
      },
      "rotation": {
        "type": "object",
        "properties": { "pitch": { "type": "number" }, "yaw": { "type": "number" }, "roll": { "type": "number" } }
      },
      "scale": {
        "type": "object",
        "properties": { "x": { "type": "number" }, "y": { "type": "number" }, "z": { "type": "number" } }
      }
    },
    "required": ["actor"]
  }
  ```

### `get_actor_components`
- **Categoría:** Actors
- **Seguridad:** `READ_ONLY`
- **Descripción:** Lista detallada de todos los componentes (`UActorComponent`, `USceneComponent`, etc.) asociados a un actor.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Nombre del actor" }
    },
    "required": ["actor"]
  }
  ```

---

## 3. Herramientas de Assets

### `find_assets`
- **Categoría:** Assets
- **Seguridad:** `READ_ONLY`
- **Descripción:** Realiza búsquedas ultrarrápidas mediante `AssetRegistry` sin instanciar objetos pesados en memoria.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "class_name": { "type": "string", "description": "Clase del asset (ej: StaticMesh, Blueprint, DataTable)" },
      "package_path": { "type": "string", "description": "Ruta de carpeta (ej: /Game/Characters, /Game/Items)" },
      "name_filter": { "type": "string", "description": "Subcadena en el nombre del asset" },
      "max_results": { "type": "number", "description": "Límite de resultados (default 50, max 500)" }
    }
  }
  ```

### `get_asset_info`
- **Categoría:** Assets
- **Seguridad:** `READ_ONLY`
- **Descripción:** Obtiene los metadatos y etiquetas (AssetRegistry tags) de un asset específico.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "asset_path": { "type": "string", "description": "Ruta de objeto o paquete (ej: /Game/Weapons/Sword_01)" }
    },
    "required": ["asset_path"]
  }
  ```

### `get_asset_class`
- **Categoría:** Assets
- **Seguridad:** `READ_ONLY`
- **Descripción:** Resuelve la clase C++ nativa o Blueprint generada de un asset.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "asset_path": { "type": "string" }
    },
    "required": ["asset_path"]
  }
  ```

### `get_asset_path`
- **Categoría:** Assets
- **Seguridad:** `READ_ONLY`
- **Descripción:** Resuelve el nombre corto de un asset a su ruta canónica de paquete (`PackageName`) y de objeto (`ObjectPath`).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "asset_name": { "type": "string" }
    },
    "required": ["asset_name"]
  }
  ```

### `get_asset_dependencies`
- **Categoría:** Assets
- **Seguridad:** `READ_ONLY`
- **Descripción:** Consulta el grafo de dependencias de un asset: qué otros paquetes necesita y qué paquetes lo referencian a él.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "package_name": { "type": "string", "description": "Ruta del paquete (ej: /Game/Items/BP_IronSword)" }
    },
    "required": ["package_name"]
  }
  ```

### `save_asset`
- **Categoría:** Assets
- **Seguridad:** `SAFE_WRITE`
- **Descripción:** Guarda a disco las modificaciones pendientes del paquete especificado.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "package_name": { "type": "string", "description": "Ruta del paquete a guardar" }
    },
    "required": ["package_name"]
  }
  ```

---

## 4. Herramientas de Esqueletos y Mallas

### `get_skeletal_mesh_info`
- **Categoría:** Skeleton
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve la cantidad de LODs, ranuras de materiales asignadas y el asset de Skeleton vinculado a un `USkeletalMesh`.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "mesh_path": { "type": "string", "description": "Ruta del asset SkeletalMesh" }
    },
    "required": ["mesh_path"]
  }
  ```

### `get_skeleton_info`
- **Categoría:** Skeleton
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve el recuento total de huesos y de sockets configurados en un `USkeleton`.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "skeleton_path": { "type": "string", "description": "Ruta del Skeleton" }
    },
    "required": ["skeleton_path"]
  }
  ```

### `get_skeleton_sockets`
- **Categoría:** Skeleton
- **Seguridad:** `READ_ONLY`
- **Descripción:** Lista los nombres de los sockets, el hueso al que están anclados y su offset de transformación local.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "asset_path": { "type": "string", "description": "Ruta del Skeleton o SkeletalMesh" }
    },
    "required": ["asset_path"]
  }
  ```

### `get_bones`
- **Categoría:** Skeleton
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve la jerarquía completa de huesos (nombres de huesos e índices de hueso padre).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "mesh_path": { "type": "string", "description": "Ruta del SkeletalMesh" }
    },
    "required": ["mesh_path"]
  }
  ```

---

## 5. Herramientas de Blueprints

### `find_blueprint`
- **Categoría:** Blueprints
- **Seguridad:** `READ_ONLY`
- **Descripción:** Busca assets de tipo Blueprint en el proyecto.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "name": { "type": "string", "description": "Filtro de nombre" },
      "path": { "type": "string", "description": "Ruta base (ej: /Game/Blueprints)" }
    }
  }
  ```

### `get_blueprint_info`
- **Categoría:** Blueprints
- **Seguridad:** `READ_ONLY`
- **Descripción:** Proporciona la clase padre y la clase generada (`GeneratedClass`) de un Blueprint.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "blueprint_path": { "type": "string" }
    },
    "required": ["blueprint_path"]
  }
  ```

### `get_blueprint_parent_class`
- **Categoría:** Blueprints
- **Seguridad:** `READ_ONLY`
- **Descripción:** Obtiene el nombre y la ruta de la clase base nativa o Blueprint padre directo.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "blueprint_path": { "type": "string" }
    },
    "required": ["blueprint_path"]
  }
  ```

### `get_blueprint_variables`
- **Categoría:** Blueprints
- **Seguridad:** `READ_ONLY`
- **Descripción:** Inspecciona y enumera las variables miembro declaradas en el Blueprint.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "blueprint_path": { "type": "string" }
    },
    "required": ["blueprint_path"]
  }
  ```

---

## 6. Herramientas de Tablas de Datos (DataTables)

### `find_datatable`
- **Categoría:** DataTable
- **Seguridad:** `READ_ONLY`
- **Descripción:** Busca tablas de datos (`UDataTable`) en el proyecto.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "path": { "type": "string" }
    }
  }
  ```

### `get_datatable_info`
- **Categoría:** DataTable
- **Seguridad:** `READ_ONLY`
- **Descripción:** Devuelve la estructura de fila (`RowStruct`), el número total de filas y los identificadores de fila.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "datatable_path": { "type": "string" }
    },
    "required": ["datatable_path"]
  }
  ```

### `list_datatable_rows`
- **Categoría:** DataTable
- **Seguridad:** `READ_ONLY`
- **Descripción:** Obtiene los nombres de fila de forma paginada para tablas masivas.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "datatable_path": { "type": "string" },
      "offset": { "type": "number", "description": "Índice inicial" },
      "limit": { "type": "number", "description": "Cantidad máxima de filas (default 50)" }
    },
    "required": ["datatable_path"]
  }
  ```

### `get_datatable_row`
- **Categoría:** DataTable
- **Seguridad:** `READ_ONLY`
- **Descripción:** Extrae el contenido completo de una fila en formato JSON estructurado.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "datatable_path": { "type": "string" },
      "row_name": { "type": "string", "description": "Nombre o ID de la fila" }
    },
    "required": ["datatable_path", "row_name"]
  }
  ```

---

## 7. Herramientas de Partículas y VFX

### `find_particle_systems`
- **Categoría:** Particles
- **Seguridad:** `READ_ONLY`
- **Descripción:** Localiza emisores Niagara (`UNiagaraSystem`) o sistemas Cascade heredados (`UParticleSystem`).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "type": { "type": "string", "description": "'NiagaraSystem' o 'ParticleSystem'" },
      "path": { "type": "string" }
    }
  }
  ```

### `get_particle_info`
- **Categoría:** Particles
- **Seguridad:** `READ_ONLY`
- **Descripción:** Inspecciona las propiedades de un sistema de partículas (emisores, tipo y bounds).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "particle_path": { "type": "string" }
    },
    "required": ["particle_path"]
  }
  ```

### `get_character_sockets`
- **Categoría:** Particles
- **Seguridad:** `READ_ONLY`
- **Descripción:** Lista los sockets disponibles en el componente SkeletalMesh de un personaje o actor para adjuntar efectos o armas.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string" }
    },
    "required": ["actor"]
  }
  ```

### `preview_particle_on_actor`
- **Categoría:** Particles
- **Seguridad:** `SAFE_WRITE`
- **Descripción:** Instancia y adjunta un componente temporal de partículas en un socket o raíz de un actor en el editor para previsualización inmediata.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string" },
      "particle_path": { "type": "string" },
      "socket_name": { "type": "string" }
    },
    "required": ["actor", "particle_path"]
  }
  ```

### `remove_preview_particle`
- **Categoría:** Particles
- **Seguridad:** `SAFE_WRITE`
- **Descripción:** Elimina los componentes de previsualización de partículas añadidos a un actor.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "actor": { "type": "string" }
    },
    "required": ["actor"]
  }
  ```

---

## 8. Herramientas Específicas de Conan Exiles

### `find_conan_assets`
- **Categoría:** Conan
- **Seguridad:** `READ_ONLY`
- **Descripción:** Realiza búsquedas de assets contextualizadas específicamente en los directorios de Conan Exiles (`/Game/` y `/ConanSandbox/`).
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Término de búsqueda" },
      "class_name": { "type": "string", "description": "Filtro opcional de clase" }
    }
  }
  ```

### `find_conan_datatables`
- **Categoría:** Conan
- **Seguridad:** `READ_ONLY`
- **Descripción:** Localiza tablas de datos de gameplay, recetas de crafteo, tablas de spawn de NPC y estadísticas de Conan Exiles.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Término de búsqueda (ej: ItemTable, SpawnTable)" }
    }
  }
  ```

### `find_conan_characters`
- **Categoría:** Conan
- **Seguridad:** `READ_ONLY`
- **Descripción:** Encuentra Blueprints y datos de NPCs, monstruos, jefes y thralls del juego.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Nombre del personaje o facción (ej: Cimmerian, Darfari)" }
    }
  }
  ```

### `find_conan_items`
- **Categoría:** Conan
- **Seguridad:** `READ_ONLY`
- **Descripción:** Búsqueda rápida de armaduras, armas, consumibles y componentes de construcción de Conan Exiles.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Nombre de item o arma" }
    }
  }
  ```

### `find_conan_particles`
- **Categoría:** Conan
- **Seguridad:** `READ_ONLY`
- **Descripción:** Busca en las librerías de efectos visuales (magia, fuego, sangre, impactos, tormentas de arena) de Conan Exiles.
- **Esquema de Entrada:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Término de búsqueda (ej: Sandstorm, Spell, Blood)" }
    }
  }
  ```
