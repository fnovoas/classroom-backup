# Google Classroom Backup

Herramienta en Python para hacer copia de seguridad de cursos de Google Classroom: metadatos, archivos de Drive, videos (incluidos los *view-only*), enlaces de YouTube y subtítulos. Al finalizar genera un sitio web estático para consultar el contenido offline.
> El contenido descargado puede llegar a pesar decenas de GB y se guarda dentro de la carpeta de este proyecto. Se debe tener espacio de almacenamiento libre para usar.

## Características

- **Metadatos del curso**: temas, anuncios, tareas y materiales (JSON).
- **Archivos de Drive**: PDFs, documentos de Google (exportados a PDF), imágenes, notebooks, ZIP, etc.
- **Videos view-only**: descarga por streaming en paralelo cuando Drive no permite `get_media` (sesiones de Meet grabadas en Classroom).
- **Subtítulos**: transcripciones VTT/TXT de videos de Drive cuando están disponibles.
- **YouTube**: descarga de videos adjuntos con `yt-dlp`.
- **Reanudación**: omite archivos ya descargados usando `download_state.json`.
- **Sitio web estático**: interfaz tipo Classroom generada en `site/`.

## Requisitos

- Python 3.12+
- Cuenta de Google con acceso a los cursos
- Credenciales OAuth 2.0 de Google Cloud (ver [Configuración](#configuración))
- `yt-dlp` (para videos de YouTube; se instala con las dependencias)

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 yt-dlp
```

## Configuración

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita las APIs **Google Classroom** y **Google Drive**.
3. Crea credenciales OAuth 2.0 (tipo *Desktop app*) y descarga el JSON.
4. Guarda el archivo como `google_oauth_tokens.json` en la raíz del proyecto.

En el primer uso, el script inicia un servidor local en `localhost:8080`, imprime la URL de consentimiento y guarda el token en `token.json` para ejecuciones posteriores.

### Archivos sensibles (no subir a git)

| Archivo | Descripción |
|---------|-------------|
| `google_oauth_tokens.json` | Credenciales OAuth del cliente |
| `token.json` | Token de acceso del usuario |

Cada ejecución de `src.main` o `src.cli` guarda toda la salida de consola en `logs.txt` (se reinicia al inicio de cada run).

## Uso

Usa la flag `-u` para ver la salida en tiempo real:

```bash
python3 -u -m src.cli      # modo interactivo (recomendado)
python3 -u -m src.main     # línea de comandos
```

### Modo interactivo

```bash
python3 -u -m src.cli
```

Permite elegir:

- Cursos a descargar (varios a la vez)
- Tipos de recurso: videos, subtítulos, PDFs, otros
- Conexiones paralelas por video (por defecto 4)

### Línea de comandos

```bash
# Listar cursos con sus IDs
python3 -u -m src.main --list

# Respaldar un curso específico
python3 -u -m src.main --course 861843525245

# Respaldar todos los cursos
python3 -u -m src.main

# Solo metadatos, sin descargar archivos
python3 -u -m src.main --dry-run

# Sin descargas de Drive (solo JSON + sitio)
python3 -u -m src.main --no-drive

# Filtrar tipos de archivo
python3 -u -m src.main --course <id> --videos --pdfs

# Más conexiones paralelas para videos grandes
python3 -u -m src.main --course <id> --connections 8
```

## Reanudación

Cada curso guarda un `download_state.json` con el estado de cada archivo. Al volver a ejecutar el script:

- Los archivos **ya completos** se omiten (se verifica tamaño en disco).
- Los videos view-only **pendientes** se reintentan automáticamente.
- Las descargas parciales de video conservan archivos `.part` + `.part.json` para continuar donde se quedaron.

Ejemplo de salida al reanudar:

```
37 already complete, 4 to download
```

Si un curso falló por timeout de red, basta con volver a ejecutarlo:

```bash
python3 -u -m src.main --course <ID_DEL_CURSO>
```

## Estructura de salida
Tras ejecutar, se crea la carpeta ```site/```.  
```
site/
├── index.html                          # Página principal
└── backups/
    └── Nombre del Curso [COURSE_ID]/
        ├── course.json                 # Metadatos del curso
        ├── topics.json
        ├── announcements.json
        ├── coursework.json
        ├── coursework_materials.json
        ├── download_state.json         # Estado de descargas (reanudación)
        ├── materials_index.json        # Índice de archivos descargados
        ├── videos_index.json           # Videos de YouTube
        ├── links.json
        ├── forms.json
        ├── errors.json                 # Errores registrados
        └── materials/                  # Archivos descargados
            ├── documento.pdf
            ├── video 1.mp4
            └── video 1.es.vtt
```

## Ver el sitio offline

```bash
python3 -m http.server 8000
```

Abre en el navegador: [http://localhost:8000/site/](http://localhost:8000/site/)

## Solución de problemas

### El script no produce salida al iniciar

Espera unos segundos: la primera conexión a la API de Google puede tardar. Deberías ver:

```
Loading Google credentials...
Connected to Google Classroom and Drive APIs
```

### Timeout de red

Si aparece `The read operation timed out`, el script reintenta automáticamente las llamadas a la API. Si un curso falla por completo, vuelve a ejecutarlo solo para ese curso con `--course <id>`.

### Videos view-only no se descargaban

Los videos de sesiones de Classroom suelen tener `canDownload=false`. El script los descarga por streaming (`view-only video, streaming: ...`). Si en una ejecución anterior se marcaron como omitidos, al re-ejecutar se detectan como pendientes y se descargan.

### Migrar descargas existentes

Si tienes archivos descargados manualmente sin `download_state.json`:

```bash
python3 -m src.migrate_state
```

## Estructura del proyecto

```
src/
├── auth.py              # OAuth y clientes de la API de Google
├── classroom_backup.py  # Lectura de la API de Classroom
├── drive_download.py    # Descarga de archivos de Drive
├── drive_video.py       # Streaming de videos view-only
├── youtube_download.py  # Descarga de YouTube con yt-dlp
├── main.py              # Orquestador (CLI por argumentos)
├── cli.py               # Interfaz interactiva
├── build_site.py        # Generación del sitio estático
└── migrate_state.py     # Migración de estado de descargas
```

## Licencia

Uso personal/educativo. Respeta los términos de servicio de Google Classroom y Drive.
