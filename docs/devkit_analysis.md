# Informe de Análisis Técnico: Conan Exiles Enhanced DevKit (UE 5.8.2)

**Fecha:** 25 de septiembre de 2026  
**Plugin:** ConanMCP  
**Entorno Analizado:** Conan Exiles Enhanced DevKit (`CEUE5Devkit`)  
**Autor:** Antigravity AI Coding Assistant  

---

## 1. Resumen Ejecutivo

Este informe documenta los hallazgos técnicos derivados del análisis en profundidad de la instalación local del **Conan Exiles Enhanced DevKit** ubicado en `C:\Program Files\Epic Games\CEUE5Devkit`. El objetivo es definir la viabilidad, arquitectura y dependencias para el desarrollo del plugin **ConanMCP**, un servidor MCP (Model Context Protocol) integrado para inspección y control seguro del editor.

---

## 2. Versión del Motor y Build Identificada

- **Versión del Motor:** Unreal Engine 5.8.2 personalizada por Funcom para Conan Exiles.
  - `MajorVersion`: 5
  - `MinorVersion`: 8
  - `PatchVersion`: 2
  - `Changelist`: 377096
  - `CompatibleChangelist`: 377096
  - `IsLicenseeVersion`: 1
  - `IsPromotedBuild`: 1
  - `BranchName`: `++exiles+release`
  - `BuildId`: `377096`
- **Archivo de versión:** `Engine/Build/Build.version`
- **Tipo de Distribución:** **Installed Build (Rocket Build)** confirmado por `Engine/Build/InstalledBuild.txt`.
- **Sistema Operativo Anfitrión:** Windows 11 (25H2) [10.0.26200.9457], 64-bit.
- **Hardware de Ejecución:** Intel Core i5-14600KF (14 núcleos físicos, 20 hilos).

---

## 3. Estructura del Proyecto ConanSandbox y Targets del Editor

- **Ruta del Proyecto:** `C:\Program Files\Epic Games\CEUE5Devkit\UE4\ConanSandbox.uproject`
- **Script de Lanzamiento:** `RunDevKit.bat`:
  ```bat
  start Engine\Binaries\Win64\UnrealEditor.exe "%~dp0\UE4\ConanSandbox.uproject" -ModDevKit
  ```
- **Target Principal del Editor:** `ConanSandboxEditor`
  - **Tipo de Target:** `TargetType.Editor`
  - **Configuración:** `Development`
  - **Entorno de Compilación:** `Shared`
  - **Build Settings:** `BuildSettingsVersion.Latest` / `V7`
  - **Include Order:** `EngineIncludeOrderVersion.Latest`
  - **Receipt de Target Encontrado:** `UE4/Binaries/Win64/ConanSandboxEditor.target` (33,990 líneas de manifiesto de dependencias, DLLs y módulos registrados bajo `BuildId: 377096`).
- **Archivos de Target y Build disponibles en el proyecto:**
  - `UE4/Intermediate/Source/ConanSandboxEditor.Target.cs`
  - `UE4/Intermediate/Source/ConanSandbox.Target.cs`
  - `UE4/Intermediate/Source/ConanSandbox.Build.cs`
  - `UE4/Intermediate/Source/ConanSandbox.cpp`

---

## 4. Análisis de Plugins y Módulos Críticos

### 4.1. ModelContextProtocol (MCP Oficial de Epic Games)
- **Ubicación:** `Engine/Plugins/Experimental/ModelContextProtocol/ModelContextProtocol.uplugin`
- **Estado:** **INCOMPATIBLE / NO UTILIZABLE**
- **Diagnóstico:**
  - El archivo `.uplugin` existe, pero **no contiene binarios compilados (`.dll`)** ni código fuente C++.
  - Declara dependencia obligatoria de `ToolsetRegistry`.
  - Los plugins relacionados `ToolsetRegistry` (`Engine/Plugins/Experimental/ToolsetRegistry`) y `MCPClientToolset` (`Engine/Plugins/Experimental/Toolsets/MCPClientToolset`) tampoco disponen de binarios precompilados.
  - Al intentar activarlos, el editor falla en la fase `EarliestPossiblePluginsLoaded` con el error:
    ```
    LogInit: Warning: Incompatible or missing module: ToolsetRegistry
    LogInit: Warning: Incompatible or missing module: MCPClientToolset
    "The following modules are missing or built with a different engine version:
    ToolsetRegistry
    MCPClientToolset
    Engine modules cannot be compiled at runtime. Please build through your IDE."
    ```
  - **Decisión de Arquitectura:** Descartar completamente la dependencia de `ModelContextProtocol`, `ToolsetRegistry`, `MCPClientToolset` y `AllToolsets`. ConanMCP implementará su propio servidor MCP autónomo mediante HTTP/JSON-RPC 2.0.

### 4.2. Módulo HTTPServer
- **Estado:** **DISPONIBLE y COMPILADO**
- **Ubicación del Binario:** `Engine/Binaries/Win64/UnrealEditor-HTTPServer.dll`
- **Registro:** Confirmado en `Engine/Binaries/Win64/UnrealEditor.modules` (`"HTTPServer": "UnrealEditor-HTTPServer.dll"`).
- **Módulos de Red y Serialización Asociados Disponibles:**
  - `HTTP` (`UnrealEditor-HTTP.dll`)
  - `Sockets` (`UnrealEditor-Sockets.dll`)
  - `WebSockets` (`UnrealEditor-WebSockets.dll`)
  - `Json` (`UnrealEditor-Json.dll`)
  - `JsonUtilities` (`UnrealEditor-JsonUtilities.dll`)
- **Conclusión:** Se puede utilizar directamente el módulo `HTTPServer` nativo de Unreal Engine o sockets TCP locales para el endpoint HTTP/JSON-RPC en el puerto 8123.

### 4.3. Módulo AssetRegistry
- **Estado:** **DISPONIBLE y COMPILADO**
- **Ubicación del Binario:** `Engine/Binaries/Win64/UnrealEditor-AssetRegistry.dll`
- **Registro:** Confirmado en `UnrealEditor.modules`.
- **Módulos Complementarios:** `AssetTools` (`UnrealEditor-AssetTools.dll`).
- **Conclusión:** Permite consultar metadatos de assets mediante `FAssetData` de manera instantánea y sin incurrir en la carga masiva en memoria de miles de objetos (`UObject`).

### 4.4. Módulo Niagara y Sistema de Partículas
- **Estado:** **DISPONIBLE y COMPILADO**
- **Ubicación:** `Engine/Plugins/FX/Niagara/Binaries/Win64/`
- **Binarios Presentes:**
  - `UnrealEditor-Niagara.dll`
  - `UnrealEditor-NiagaraEditor.dll`
  - `UnrealEditor-NiagaraCore.dll`
  - `UnrealEditor-NiagaraShader.dll`
- **Sistema Cascade:** Disponible en el runtime del motor.
- **Plugin de Conversión:** `CascadeToNiagaraConverter` disponible y activo en `ConanSandbox.uproject`.
- **Conclusión:** Soporte completo tanto para Niagara como para Cascade.

### 4.5. Otros Módulos Clave Verificados
- `UnrealEd` (`UnrealEditor-UnrealEd.dll`) - Editor transaccional (`FScopedTransaction`), selección de actores, guardado de niveles.
- `LevelEditor` (`UnrealEditor-LevelEditor.dll`) - Interacción con el nivel actual y viewports.
- `BlueprintGraph` y `Kismet` (`UnrealEditor-BlueprintGraph.dll`, `UnrealEditor-Kismet.dll`) - Inspección de Blueprints.
- `Slate` y `SlateCore` (`UnrealEditor-Slate.dll`, `UnrealEditor-SlateCore.dll`) - Interfaz gráfica de usuario en el editor.
- `ToolMenus` y `WorkspaceMenuStructure` (`UnrealEditor-ToolMenus.dll`, `UnrealEditor-WorkspaceMenuStructure.dll`) - Integración de menús y pestañas (`Window -> Developer Tools -> Conan MCP`).
- `PythonScriptPlugin` (`Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Win64/UnrealEditor-PythonScriptPlugin.dll`) - Módulo de script de Python precompilado por Epic/Funcom.

---

## 5. Análisis del Sistema de Compilación (Toolchain y SDKs)

### 5.1. UnrealBuildTool (UBT)
- **Ubicación:** `C:\Program Files\Epic Games\CEUE5Devkit\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe`
- **Framework:** .NET 10.0 runtime (`Engine/Binaries/ThirdParty/DotNet/10.0/win-x64`).
- **Prueba de Ejecución:** UBT arranca y procesa argumentos correctamente.
- **Resultado de la Validación del Target:**
  Al invocar UBT para `ConanSandboxEditor Win64 Development`, UBT analiza las reglas y plugins pero arroja:
  ```
  Platform Win64 is not a valid platform to build. SDK validation failed:
    Sdk: not found. Required version 10.0.19041.0.
  ```

### 5.2. Estado del Entorno de Desarrollo en la Máquina
1. **Visual Studio:** `Visual Studio Community 2022` (17.14.35) instalado en `C:\Program Files\Microsoft Visual Studio\2022\Community`.
2. **C++ Workload (MSVC):** **NO INSTALADO**. La carpeta `VC\Tools\MSVC` no existe en la instalación actual de VS 2022 (solo C# / .NET / Auxiliary).
3. **Windows SDK:** **NO INSTALADO**. Solo existe SDK 8.1 legado en `Program Files (x86)\Windows Kits\8.1`. Se requiere Windows 10/11 SDK (`10.0.19041.0` a `10.0.22621.0`).
4. **Headers C++ de Conan DevKit:** Funcom suministró el DevKit como un Installed Build de modding sin la carpeta `Engine/Source/Runtime` o `Engine/Source/Editor`.

---

## 6. Riesgos Identificados y Estrategia de Mitigación

| Riesgo / Desafío | Impacto | Estrategia de Mitigación |
| :--- | :--- | :--- |
| **Incompatibilidad de ModelContextProtocol** | Crítico si se intentara reutilizar | Implementar servidor MCP nativo e independiente en ConanMCP usando `HTTPServer` / `JsonUtilities`. No depender de plugins rotos. |
| **Falta de Windows SDK y MSVC C++ en el sistema** | Bloquea la compilación de cualquier binario nativo C++ | Instalar los componentes necesarios de C++ (Windows 10/11 SDK y MSVC v143) mediante `winget` o Visual Studio Installer. |
| **Volumen masivo de assets en Conan Exiles** | Posible congelamiento del Editor durante búsquedas | Utilizar exclusivamente `AssetRegistry` con `FAssetData` en memoria sin cargar `UObject`. Imponer límite por defecto de 50 resultados (máximo 500) y paginación. |
| **Llamadas HTTP asíncronas fuera del Game Thread** | Corrupción de memoria o crash por accesos concurrentes a UObject | Toda llamada a APIs de Unreal se despachará al Game Thread mediante `AsyncTask(ENamedThreads::GameThread, ...)` con un timeout configurable (30 s). |
| **Seguridad de agentes MCP externos** | Riesgo de operaciones no deseadas o destructivas | Enlazar exclusivamente a `127.0.0.1` por defecto. Clasificar herramientas en `READ_ONLY`, `SAFE_WRITE` y `DESTRUCTIVE`. Bloquear ejecución de scripts y comandos del sistema operativo. |
| **Modificaciones irreversibles en el nivel** | Pérdida de trabajo del usuario en el editor | Envolver todas las herramientas de escritura en `FScopedTransaction` y llamar a `Modify()` para habilitar Undo/Redo (`Ctrl+Z`). |

---

## 7. Conclusión de la Fase 1

La instalación del Conan Exiles Enhanced DevKit cuenta con todos los módulos y subsistemas requeridos en tiempo de ejecución (`HTTPServer`, `AssetRegistry`, `Niagara`, `UnrealEd`, `JsonUtilities`, `ToolMenus`), pero carece de los binarios precompilados de `ModelContextProtocol` oficial. Por lo tanto, el desarrollo de un servidor MCP autónomo y desacoplado dentro de **ConanMCP** es la arquitectura óptima, segura y 100% compatible.
