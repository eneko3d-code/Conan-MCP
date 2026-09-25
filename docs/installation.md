# Guía de Instalación: ConanMCP

Esta guía detalla los pasos para instalar, desplegar y validar el plugin **ConanMCP** en el **Conan Exiles Enhanced DevKit** (Unreal Engine 5.8.2).

---

## 1. Requisitos del Sistema y Entorno

- **Motor:** Conan Exiles Enhanced DevKit basado en Unreal Engine 5.8.2 (`++exiles+release`, CL `377096`).
- **Sistema Operativo:** Windows 10 / Windows 11 (64-bit).
- **Plugins Nativos de Unreal Engine Requeridos:**
  - `PythonScriptPlugin` (Habilitado por defecto en el DevKit de Conan Exiles).
  - `EditorScriptingUtilities` (Habilitado por defecto en el DevKit de Conan Exiles).
- **Red Local:** Puerto TCP `8123` disponible en interfaz `127.0.0.1`.

---

## 2. Comprensión Técnica: Arquitectura de Distribución de Funcom

El Conan Exiles Enhanced DevKit es una **Installed Build (Rocket Build)** empaquetada por Funcom (`Engine/Build/InstalledBuild.txt`). 

### El Problema Común con Plugins C++ en DevKits
En distribuciones Installed Build:
1. El motor no incluye las cabeceras completas de desarrollo en `Engine/Source/Runtime` o `Engine/Source/Editor`.
2. Si un archivo `.uplugin` declara módulos C++ en el bloque `"Modules"` sin que existan previamente binarios DLL compilados con el `BuildId` exacto (`377096`), Unreal Engine intentará compilar el módulo al arrancar.
3. Si la máquina no cuenta con el SDK de Windows (`10.0.19041.0`) y las herramientas de compilador MSVC C++ configuradas, el DevKit muestra el error crítico:
   > *"The following modules are missing or built with a different engine version: [...] Engine modules cannot be compiled at runtime. Please build through your IDE."*
   y el editor se cierra inmediatamente.

### La Solución de ConanMCP (Arquitectura Dual)
Para garantizar una experiencia inmediata sin fricción y 100% libre de errores:
1. **Runtime Embebido Autónomo:** `ConanMCP` implementa un runtime de servidor MCP de alto rendimiento en `Content/Python/conan_mcp_server.py`, el cual es arrancado automáticamente por `init_unreal.py` a través del `PythonScriptPlugin` integrado en el propio editor.
2. **C++ Nativo para Entornos de Desarrollo:** Para usuarios o estudios que dispongan de la suite de compilación C++ y deseen enlazar módulos nativos, el código C++ completo está estructurado en `Source/ConanMCP/` respetando los estándares de UE 5.8.2.

---

## 3. Pasos de Instalación

### Paso 1: Estructurar el Directorio del Plugin
Asegúrate de que la carpeta del plugin se encuentre en el directorio de plugins del proyecto:
```
C:\Program Files\Epic Games\CEUE5Devkit\UE4\Plugins\ConanMCP
```

La estructura mínima requerida para el funcionamiento inmediato es:
```
ConanMCP/
├── ConanMCP.uplugin
├── Content/
│   └── Python/
│       ├── init_unreal.py
│       └── conan_mcp_server.py
├── Source/
│   └── ConanMCP/ ...
└── docs/ ...
```

### Paso 2: Verificar el archivo `ConanMCP.uplugin`
El archivo descriptor debe contener:
```json
{
	"FileVersion": 3,
	"Version": 1,
	"VersionName": "1.0.0",
	"FriendlyName": "ConanMCP",
	"Description": "Embedded Model Context Protocol (MCP) server for Conan Exiles Enhanced DevKit (UE 5.8.2).",
	"Category": "AI / Developer Tools",
	"CreatedBy": "Antigravity",
	"CanContainContent": true,
	"IsBetaVersion": false,
	"IsExperimentalVersion": false,
	"Installed": false,
	"Plugins": [
		{
			"Name": "PythonScriptPlugin",
			"Enabled": true
		},
		{
			"Name": "EditorScriptingUtilities",
			"Enabled": true
		}
	]
}
```

### Paso 3: Lanzar el DevKit
Inicia el DevKit ejecutando:
```bat
C:\Program Files\Epic Games\CEUE5Devkit\RunDevKit.bat
```
El motor detectará el plugin, montará el contenido y ejecutará `Content/Python/init_unreal.py` durante la fase de inicialización de Python.

En el Output Log del editor se observará:
```
LogConanMCP: Starting ConanMCP auto-initializer...
LogConanMCP: Registered 38 tools for ConanMCP
LogConanMCP: MCP server started on 127.0.0.1:8123 (Endpoint: /mcp)
```

---

## 4. Validación de la Instalación

### Opción A: Comprobación con PowerShell
Abre una terminal PowerShell y ejecuta:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8123/mcp" -Method Get
```
Salida esperada:
```json
service          : ConanMCP
version          : 1.0.0
protocol         : MCP / JSON-RPC 2.0
status           : running
registered_tools : 38
```

### Opción B: Comprobación con cURL
```bash
curl http://127.0.0.1:8123/mcp
```

### Opción C: Ejecución de la Suite Automatizada de Pruebas
Puedes ejecutar la suite de pruebas completa utilizando el intérprete de Python 3.11 embebido en el propio DevKit:
```powershell
& "C:\Program Files\Epic Games\CEUE5Devkit\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" "C:\Program Files\Epic Games\CEUE5Devkit\UE4\Plugins\ConanMCP\docs\test_mcp_server.py"
```
Todas las 11 pruebas del protocolo MCP y herramientas deben completarse con éxito (`PASSED`).

---

## 5. Solución de Problemas de Instalación

| Problema | Causa Probable | Solución |
|---|---|---|
| `Error: Port 8123 already in use` | Otra instancia del DevKit o servidor MCP está ocupando el puerto 8123. | Cierra procesos huérfanos con `Stop-Process -Name UnrealEditor` o cambia el puerto en `conan_mcp_server.py`. |
| El servidor no responde en `127.0.0.1:8123` | El DevKit aún está cargando shaders o el `PythonScriptPlugin` no se ha inicializado. | Espera a que el editor termine de cargar el mapa principal o revisa la pestaña `Output Log`. |
| `ImportError: No module named 'conan_mcp_server'` | La ruta del plugin no se agregó a `sys.path`. | Asegúrate de usar la última versión de `init_unreal.py` que incluye `sys.path.insert(0, script_dir)`. |
