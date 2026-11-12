# ModTraductor — Beta 0.1

Aplicación web inicial para analizar mods Java de Minecraft y generar un Resource Pack con archivos de idioma en español.

## Qué hace esta versión
- Acepta archivos `.jar` (máximo 100 MB).
- Lee metadatos de Fabric, Forge y NeoForge cuando están disponibles.
- Busca JSON en `assets/<namespace>/lang/`.
- Permite traducir hasta 80 cadenas por operación mediante MyMemory (servicio externo gratuito con límites).
- Permite editar los textos detectados.
- Genera `ModTraductor_es_ES.zip` con `assets/<namespace>/lang/es_es.json` y `pack.mcmeta`.
- No ejecuta el JAR ni extrae sus rutas a disco.

## Límites importantes
- No traduce código Java/Kotlin ni textos incrustados directamente en el código.
- No garantiza que todos los mods usen el formato estándar de idioma JSON.
- La traducción automática gratuita tiene límites y puede fallar o necesitar corrección humana.
- Esta beta mantiene las sesiones en memoria: reiniciar el servidor borra los trabajos. No es adecuada todavía para tráfico público grande.
- El `pack_format` debe corresponder a la versión de Minecraft elegida. La interfaz permite cambiarlo; no se debe asumir que un único valor sirve para todas las versiones.
- Antes de abrir el servicio al público, añade autenticación/rate limiting, almacenamiento temporal con expiración, límites por IP y una política de privacidad.

## Ejecutar en tu PC
Requiere Python 3.11+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre http://127.0.0.1:8000

## Publicar online gratis (Render)
1. Crea una cuenta en GitHub y un repositorio nuevo.
2. Sube el contenido de esta carpeta al repositorio.
3. En Render, crea un servicio nuevo desde ese repositorio (Blueprint o Web Service con Docker).
4. Render detectará `render.yaml`/`Dockerfile`.
5. Espera el despliegue y abre la URL `*.onrender.com`.

Los planes gratuitos y sus límites pueden cambiar. Un servicio gratuito puede entrar en reposo y tardar en iniciar.

## Seguridad
El servidor nunca ejecuta los JAR. Aun así, solo sube mods de fuentes confiables. No publiques mods privados ni archivos para los que no tengas permiso. No uses esta beta como servicio público sin reforzar controles y privacidad.
