import io, json, os, re, zipfile, uuid, asyncio
from pathlib import PurePosixPath
from typing import Dict, Any
import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ModTraductor", version="0.1.0")
MAX_UPLOAD = 100 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_ENTRIES = 5000
sessions: Dict[str, Dict[str, Any]] = {}

def safe_json_bytes(data: bytes):
    if len(data) > MAX_JSON:
        raise ValueError("Archivo de idioma demasiado grande.")
    return json.loads(data.decode("utf-8-sig"))

def detect_mod_metadata(zf):
    names = set(zf.namelist())
    meta = {"name": None, "id": None, "loader": "Desconocido"}
    candidates = [
        ("fabric.mod.json", "Fabric"),
        ("META-INF/mods.toml", "Forge"),
        ("META-INF/neoforge.mods.toml", "NeoForge"),
        ("mcmod.info", "Forge antiguo"),
    ]
    for path, loader in candidates:
        if path in names:
            meta["loader"] = loader
            try:
                raw = zf.read(path)
                if path.endswith(".json"):
                    obj = json.loads(raw.decode("utf-8-sig"))
                    meta["name"] = obj.get("name") or obj.get("displayName")
                    meta["id"] = obj.get("id")
                elif path.endswith(".toml"):
                    text = raw.decode("utf-8", "ignore")
                    m = re.search(r'(?m)^\s*modId\s*=\s*"([^"]+)"', text)
                    n = re.search(r'(?m)^\s*displayName\s*=\s*"([^"]+)"', text)
                    meta["id"] = m.group(1) if m else None
                    meta["name"] = n.group(1) if n else None
                else:
                    obj = json.loads(raw.decode("utf-8-sig"))
                    if isinstance(obj, list) and obj:
                        meta["name"] = obj[0].get("name")
                        meta["id"] = obj[0].get("modid")
            except Exception:
                pass
            break
    return meta

def parse_mod(raw: bytes):
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("El archivo no parece ser un .JAR válido.")
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError("El mod contiene demasiados archivos.")
    metadata = detect_mod_metadata(zf)
    languages = {}
    for info in infos:
        # Never extract archive paths to disk. Read only bounded language JSON files.
        p = PurePosixPath(info.filename)
        parts = p.parts
        if info.is_dir() or len(parts) < 4:
            continue
        if parts[0] != "assets" or parts[-2] != "lang" or not parts[-1].lower().endswith(".json"):
            continue
        namespace = parts[1]
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", namespace):
            continue
        if info.file_size > MAX_JSON:
            continue
        try:
            obj = safe_json_bytes(zf.read(info))
            if isinstance(obj, dict):
                # Keep only string values; non-string JSON values are not translatable.
                strings = {str(k): v for k, v in obj.items() if isinstance(k, str) and isinstance(v, str)}
                if strings:
                    languages.setdefault(namespace, {})[p.name] = strings
        except Exception:
            continue
    zf.close()
    if not languages:
        raise ValueError("No encontré archivos de idioma JSON en assets/<modid>/lang/. Este mod puede usar otro sistema de traducción.")
    return metadata, languages

@app.get("/", response_class=HTMLResponse)
def home():
    with open("app/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/upload")
async def upload_mod(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".jar"):
        raise HTTPException(400, "Sube un archivo .jar de Minecraft.")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "El archivo supera el límite de 100 MB.")
    try:
        metadata, languages = parse_mod(raw)
    except ValueError as e:
        raise HTTPException(422, str(e))
    sid = str(uuid.uuid4())
    sessions[sid] = {"metadata": metadata, "languages": languages, "source": file.filename}
    total = sum(len(v) for ns in languages.values() for v in ns.values())
    preview = []
    for ns, langfiles in languages.items():
        for fname, strings in langfiles.items():
            for key, value in list(strings.items())[:100]:
                preview.append({"namespace": ns, "file": fname, "key": key, "value": value})
                if len(preview) >= 100:
                    break
            if len(preview) >= 100: break
        if len(preview) >= 100: break
    return {"session_id": sid, "metadata": metadata, "source": file.filename,
            "namespaces": list(languages.keys()), "files": sum(len(x) for x in languages.values()),
            "strings": total, "preview": preview}

@app.post("/api/translate")
async def translate(payload: dict):
    sid = payload.get("session_id")
    if sid not in sessions:
        raise HTTPException(404, "Sesión no encontrada. Vuelve a subir el mod.")
    session = sessions[sid]
    source_lang = payload.get("source_lang", "en")
    target_lang = payload.get("target_lang", "es")
    # Translate a bounded number of strings to avoid abuse of free public translation endpoints.
    tasks = []
    for ns, langfiles in session["languages"].items():
        for fname, strings in langfiles.items():
            for key, value in strings.items():
                if len(tasks) >= 80:
                    break
                tasks.append((ns, fname, key, value))
            if len(tasks) >= 80: break
        if len(tasks) >= 80: break
    translated = {}
    errors = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for ns, fname, key, value in tasks:
            if len(value) > 500:
                translated.setdefault(ns, {}).setdefault(fname, {})[key] = value
                continue
            try:
                params = {"q": value, "langpair": f"{source_lang}|{target_lang}"}
                r = await client.get("https://api.mymemory.translated.net/get", params=params)
                r.raise_for_status()
                data = r.json()
                result = data.get("responseData", {}).get("translatedText")
                if result and data.get("responseStatus") == 200:
                    translated.setdefault(ns, {}).setdefault(fname, {})[key] = result
                else:
                    translated.setdefault(ns, {}).setdefault(fname, {})[key] = value
            except Exception:
                translated.setdefault(ns, {}).setdefault(fname, {})[key] = value
                errors.append(key)
    # Return a full editable dictionary, preserving all strings. Translation service is best-effort.
    result = {}
    for ns, langfiles in session["languages"].items():
        result[ns] = {}
        for fname, strings in langfiles.items():
            result[ns][fname] = dict(strings)
    for ns, langfiles in translated.items():
        for fname, strings in langfiles.items():
            result[ns][fname].update(strings)
    session["translated"] = result
    session["translated_count"] = sum(len(v) for f in translated.values() for v in f.values())
    return {"translations": result, "translated_count": session["translated_count"],
            "limit": 80, "message": "La traducción automática gratuita es limitada; revisa los resultados antes de descargar."}

@app.post("/api/save")
async def save_translations(payload: dict):
    sid = payload.get("session_id")
    translations = payload.get("translations")
    if sid not in sessions or not isinstance(translations, dict):
        raise HTTPException(400, "Datos de traducción inválidos.")
    # Validate shape and string values, prevent writing arbitrary paths.
    cleaned = {}
    for ns, langfiles in translations.items():
        if ns not in sessions[sid]["languages"] or not isinstance(langfiles, dict):
            continue
        cleaned[ns] = {}
        for fname, strings in langfiles.items():
            if fname not in sessions[sid]["languages"][ns] or not isinstance(strings, dict):
                continue
            cleaned[ns][fname] = {}
            for key, value in strings.items():
                if key in sessions[sid]["languages"][ns][fname] and isinstance(value, str):
                    cleaned[ns][fname][key] = value[:5000]
    sessions[sid]["translated"] = cleaned
    return {"ok": True}

@app.post("/api/download")
async def download_pack(payload: dict):
    sid = payload.get("session_id")
    if sid not in sessions:
        raise HTTPException(404, "Sesión no encontrada.")
    session = sessions[sid]
    translations = payload.get("translations") or session.get("translated") or session["languages"]
    pack_format = payload.get("pack_format", 75)
    try:
        pack_format = int(pack_format)
        if not 1 <= pack_format <= 1000: raise ValueError()
    except Exception:
        raise HTTPException(400, "Formato de paquete inválido.")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.mcmeta", json.dumps({
            "pack": {"pack_format": pack_format,
                     "description": "Traducción al español generada por ModTraductor"}
        }, ensure_ascii=False, indent=2))
        # Merge all language JSON files by namespace into one Spanish file.
        merged = {}
        for ns, langfiles in translations.items():
            if ns not in session["languages"] or not isinstance(langfiles, dict):
                continue
            merged.setdefault(ns, {})
            for fname, strings in langfiles.items():
                if fname not in session["languages"][ns] or not isinstance(strings, dict):
                    continue
                original = session["languages"][ns][fname]
                for key, original_value in original.items():
                    val = strings.get(key, original_value)
                    merged[ns][key] = val if isinstance(val, str) else original_value
        for ns, strings in merged.items():
            z.writestr(f"assets/{ns}/lang/es_es.json",
                       json.dumps(strings, ensure_ascii=False, indent=2))
    out.seek(0)
    filename = "ModTraductor_es_ES.zip"
    return StreamingResponse(out, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

app.mount("/static", StaticFiles(directory="app"), name="static")
