#!/usr/bin/env python3
"""
Descargador de portadas de álbumes
==================================
Busca álbumes en MusicBrainz y descarga sus portadas desde Cover Art Archive
en la mayor calidad disponible.

Dependencias:  pip install requests pillow
"""
from __future__ import annotations

import io
import csv
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import requests
from PIL import Image, ImageOps, ImageTk
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_NAME = "Descargador de portadas"
APP_VERSION = "4.0"

MB_URL = "https://musicbrainz.org/ws/2/release-group/"
CAA_LISTADO = "https://coverartarchive.org/release-group/{mbid}"
CAA_MINIATURA = "https://coverartarchive.org/release-group/{mbid}/front-{size}"
MB_WEB = "https://musicbrainz.org/release-group/{mbid}"
REALESRGAN_RELEASES = "https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0"

# .............................................................................
#  Configuración
# .............................................................................
QUE_DESCARGAR = ["Solo frontal", "Frontal y trasera", "Todas las imágenes"]
TAMANOS = ["Original", "1200 px", "500 px", "250 px"]
FORMATOS = ["Original", "JPG", "PNG"]
SI_EXISTE = ["Renombrar", "Omitir", "Sobrescribir"]
TIPOS_BUSQUEDA = {"Todos": None, "Álbumes": "album", "EPs": "ep", "Singles": "single"}

DEFAULTS = {
    "directorio": str(Path.home() / "Pictures" / "Portadas"),
    "email": "",
    "plantilla": "{artista} - {album}",
    "subcarpeta_artista": False,
    "que_descargar": QUE_DESCARGAR[0],
    "tamano": TAMANOS[0],
    "formato": FORMATOS[0],
    "si_existe": SI_EXISTE[0],
    "tema": "claro",
    "max_resultados": 50,
    "descargas_simultaneas": 3,
    "abrir_al_terminar": False,
    "geometria": "1220x800",
    # Ampliación con IA (Real-ESRGAN)
    "ia_activa": False,
    "ia_objetivo": 4000,
    "ia_exe": "",
    "ia_modelo": "realesrgan-x4plus",
    "ia_gpu": 0,
    "ia_tile": 0,
    "ia_guardar_original": True,
    "modo_impresion": False,
}
MODELOS_IA = ["realesrgan-x4plus", "realesrgan-x4plus-anime"]
OBJETIVOS_IA = ["2000", "3000", "4000", "5000", "6000"]
PRESETS_SALIDA = {
    "Poster 30 cm": {
        "formato": "JPG", "ia_activa": True, "ia_objetivo": 4000,
        "ia_guardar_original": False, "modo_impresion": True,
    },
    "Archivo maestro": {
        "formato": "PNG", "ia_activa": True, "ia_objetivo": 4000,
        "ia_guardar_original": True, "modo_impresion": False,
    },
    "Portada digital": {
        "formato": "JPG", "ia_activa": False, "ia_objetivo": 2000,
        "ia_guardar_original": False, "modo_impresion": False,
    },
    "Vinilo 12 pulgadas": {
        "formato": "JPG", "ia_activa": True, "ia_objetivo": 4000,
        "ia_guardar_original": True, "modo_impresion": True,
    },
}


def directorio_config() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "DescargadorPortadas"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Config(dict):
    ARCHIVO = directorio_config() / "config.json"

    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            guardado = json.loads(self.ARCHIVO.read_text(encoding="utf-8"))
            self.update({k: v for k, v in guardado.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def guardar(self):
        try:
            self.ARCHIVO.write_text(
                json.dumps(dict(self), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass


# .............................................................................
#  Modelo y utilidades
# .............................................................................
TIPOS_ES = {"Album": "Álbum", "Single": "Single", "EP": "EP", "Broadcast": "Emisión", "Other": "Otro"}
IMAGENES_ES = {
    "Front": "Frontal", "Back": "Trasera", "Booklet": "Librillo", "Medium": "Disco",
    "Tray": "Bandeja", "Obi": "Obi", "Spine": "Lomo", "Track": "Lista de temas",
    "Liner": "Interior", "Sticker": "Sticker", "Poster": "Póster",
    "Watermark": "Marca de agua", "Raw/Unedited": "Sin editar", "Other": "Otra",
}
ESTADOS = {
    "ok": "OK Descargada",
    "omitido": "Omitida (ya existe)",
    "sin_portada": "Sin portada",
    "no_encontrado": "No encontrado",
    "error": "Error",
    "cancelado": "Cancelada",
}
RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
              *(f"LPT{i}" for i in range(1, 10))}


class Cancelado(Exception):
    pass


class SinPortada(Exception):
    pass


@dataclass
class Album:
    mbid: str
    artista: str
    titulo: str
    tipo: str = ""
    anio: str = ""
    origen: str | None = None  # id de fila en la pestaña Lote

    @classmethod
    def desde_mb(cls, rg: dict) -> "Album":
        artista = "".join(
            a.get("name", "") + a.get("joinphrase", "") for a in rg.get("artist-credit", [])
        )
        tipo = TIPOS_ES.get(rg.get("primary-type", ""), rg.get("primary-type", ""))
        secundarios = rg.get("secondary-types") or []
        if secundarios:
            tipo = f"{tipo} · {', '.join(s.lower() for s in secundarios)}" if tipo else ", ".join(secundarios)
        return cls(
            mbid=rg["id"],
            artista=artista or "(desconocido)",
            titulo=rg.get("title", "(sin título)"),
            tipo=tipo,
            anio=(rg.get("first-release-date") or "")[:4],
        )


def limpiar_nombre(texto: str, max_len: int = 120) -> str:
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    if texto.upper() in RESERVADOS:
        texto = f"_{texto}"
    return texto[:max_len].rstrip(" .") or "sin_nombre"


class _Vacio(dict):
    def __missing__(self, _clave):
        return ""


def nombre_base(plantilla: str, album: Album) -> str:
    datos = _Vacio(artista=album.artista, album=album.titulo, anio=album.anio,
                   tipo=album.tipo, mbid=album.mbid)
    try:
        s = plantilla.format_map(datos)
    except (ValueError, IndexError, KeyError, AttributeError):
        s = f"{album.artista} - {album.titulo}"
    s = re.sub(r"\(\s*\)|\[\s*\]", "", s)          # quita "()" si no hay año
    s = re.sub(r"\s+-\s*$|^\s*-\s+", "", s.strip())  # quita guiones colgados
    return limpiar_nombre(s)


def ruta_libre(ruta: Path) -> Path:
    if not ruta.exists():
        return ruta
    n = 1
    while True:
        candidata = ruta.with_name(f"{ruta.stem} ({n}){ruta.suffix}")
        if not candidata.exists():
            return candidata
        n += 1


def escribir_atomico(destino: Path, datos: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    tmp.write_bytes(datos)
    os.replace(tmp, destino)


def convertir(datos: bytes, formato: str) -> tuple[bytes, str]:
    """Devuelve (bytes, extensión). 'Original' conserva el archivo tal cual."""
    img = Image.open(io.BytesIO(datos))
    fmt_origen = (img.format or "").upper()
    ext_origen = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}.get(fmt_origen, ".jpg")

    if formato == "Original":
        return datos, ext_origen
    if formato == "JPG":
        if fmt_origen == "JPEG":
            return datos, ".jpg"
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            fondo = Image.new("RGB", img.size, "white")
            fondo.paste(img, mask=img.split()[-1])
            img = fondo
        else:
            img = img.convert("RGB")
        salida = io.BytesIO()
        img.save(salida, "JPEG", quality=95, subsampling=0, optimize=True)
        return salida.getvalue(), ".jpg"
    if fmt_origen == "PNG":
        return datos, ".png"
    salida = io.BytesIO()
    img.save(salida, "PNG", optimize=True)
    return salida.getvalue(), ".png"


def preparar_para_impresion(datos: bytes, formato: str) -> tuple[bytes, str]:
    """Guarda la imagen con metadatos de 300 DPI sin recortarla ni deformarla."""
    with Image.open(io.BytesIO(datos)) as imagen:
        imagen.load()
        origen = (imagen.format or "").upper()
        if formato == "JPG" or (formato == "Original" and origen == "JPEG"):
            salida = io.BytesIO()
            imagen.convert("RGB").save(salida, "JPEG", quality=95, subsampling=0,
                                        optimize=True, dpi=(300, 300))
            return salida.getvalue(), ".jpg"
        salida = io.BytesIO()
        imagen.save(salida, "PNG", optimize=True, dpi=(300, 300))
        return salida.getvalue(), ".png"


def tamano_legible(n: int) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1024
    return f"{n} B"


def datos_impresion(imagen: Image.Image) -> dict:
    """Calcula la información de impresión para un poster de 29.7 cm a 300 DPI."""
    ancho, alto = imagen.size
    lado_minimo = min(ancho, alto)
    dpi = lado_minimo / (29.7 / 2.54)
    return {
        "dim": f"{ancho}x{alto}",
        "dpi": round(dpi),
        "cuadrada": ancho == alto,
        "calidad": "apta" if lado_minimo >= 3508 else "inferior al mínimo",
    }


def huella_imagen(datos: bytes) -> str:
    """Genera una huella visual estable sin agregar dependencias externas."""
    with Image.open(io.BytesIO(datos)) as imagen:
        miniatura = ImageOps.fit(imagen.convert("L"), (32, 32), Image.Resampling.LANCZOS)
        return hashlib.sha256(miniatura.tobytes()).hexdigest()


def inspeccionar_archivo(ruta: Path) -> dict:
    try:
        datos = ruta.read_bytes()
        with Image.open(io.BytesIO(datos)) as imagen:
            informe = datos_impresion(imagen)
        informe["huella"] = huella_imagen(datos)
        informe["bytes"] = len(datos)
        return informe
    except (OSError, ValueError):
        return {}


def ruta_duplicada(historial: list[dict], huella: str, ruta: Path) -> str:
    if not huella:
        return ""
    for entrada in reversed(historial):
        if entrada.get("huella") == huella and entrada.get("ruta") != str(ruta):
            return entrada.get("ruta", "")
    return ""


def mensaje_error(e: Exception) -> str:
    if isinstance(e, requests.ConnectionError):
        return "Sin conexión con el servidor. Revisá tu internet."
    if isinstance(e, requests.Timeout):
        return "El servidor tardó demasiado en responder."
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"El servidor respondió con error {e.response.status_code}."
    return str(e) or e.__class__.__name__


def abrir_ruta(ruta: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(ruta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(ruta)])
        else:
            subprocess.Popen(["xdg-open", str(ruta)])
    except Exception as e:
        messagebox.showerror("No se pudo abrir", str(e))


def mostrar_en_carpeta(ruta: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(ruta)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(ruta)])
        else:
            subprocess.Popen(["xdg-open", str(ruta.parent)])
    except Exception as e:
        messagebox.showerror("No se pudo abrir", str(e))


def acortar(texto: str, n: int = 55) -> str:
    return texto if len(texto) <= n else "" + texto[-(n - 1):]


# .............................................................................
#  Acceso a MusicBrainz / Cover Art Archive
# .............................................................................
class Cliente:
    def __init__(self, email: str):
        self.session = requests.Session()
        reintentos = Retry(
            total=3, backoff_factor=1.0, respect_retry_after_header=True,
            status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "HEAD"),
        )
        adaptador = HTTPAdapter(max_retries=reintentos, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adaptador)
        self.session.mount("http://", adaptador)
        self.set_email(email)

        self._mb_lock = threading.Lock()
        self._mb_ultimo = 0.0
        self._cache_lock = threading.Lock()
        self._cache_listado: dict[str, list[dict] | None] = {}

    def set_email(self, email: str) -> None:
        contacto = email.strip() or "configured locally in the application"
        self.session.headers["User-Agent"] = f"DescargadorPortadas/{APP_VERSION} ({contacto})"

    # MusicBrainz permite como máximo 1 petición por segundo
    def _esperar_mb(self) -> None:
        with self._mb_lock:
            espera = 1.1 - (time.monotonic() - self._mb_ultimo)
            if espera > 0:
                time.sleep(espera)
            self._mb_ultimo = time.monotonic()

    def _consulta_mb(self, query: str, limite: int, offset: int) -> tuple[int, list[dict]]:
        self._esperar_mb()
        r = self.session.get(
            MB_URL,
            params={"query": query, "fmt": "json", "limit": limite, "offset": offset},
            timeout=20,
        )
        r.raise_for_status()
        datos = r.json()
        return datos.get("count", 0), datos.get("release-groups", [])

    @staticmethod
    def _frase(t: str) -> str:
        return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _terminos(t: str) -> str:
        return " AND ".join(re.findall(r"\w+", t, re.UNICODE))

    def buscar(self, artista: str, album: str, tipo: str | None = None,
               limite: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
        def armar(f_album, f_artista):
            partes = []
            if album:
                partes.append(f"releasegroup:{f_album(album)}")
            if artista:
                partes.append(f"artist:{f_artista(artista)}")
            if tipo:
                partes.append(f"primarytype:{tipo}")
            return " AND ".join(partes)

        total, lista = self._consulta_mb(armar(self._frase, self._frase), limite, offset)
        if not lista and offset == 0:
            # Segundo intento, más permisivo: palabras sueltas en vez de frase exacta
            envolver = lambda t: f"({self._terminos(t)})" if self._terminos(t) else self._frase(t)
            total, lista = self._consulta_mb(armar(envolver, envolver), limite, offset)
        return total, lista

    def listado(self, mbid: str) -> list[dict] | None:
        """Todas las imágenes del álbum (frente primero) o None si no tiene."""
        with self._cache_lock:
            if mbid in self._cache_listado:
                return self._cache_listado[mbid]
        r = self.session.get(CAA_LISTADO.format(mbid=mbid), timeout=20)
        if r.status_code == 404:
            imagenes = None
        else:
            r.raise_for_status()
            imagenes = r.json().get("images") or None
            if imagenes:
                imagenes.sort(key=lambda i: (not i.get("front"), not i.get("back")))
        with self._cache_lock:
            self._cache_listado[mbid] = imagenes
        return imagenes

    def miniatura(self, mbid: str, size: int = 250) -> bytes | None:
        r = self.session.get(CAA_MINIATURA.format(mbid=mbid, size=size), timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def bytes_de(self, url: str, cancelar: threading.Event | None = None) -> bytes:
        with self.session.get(url, stream=True, timeout=(10, 60)) as r:
            r.raise_for_status()
            buf = bytearray()
            for trozo in r.iter_content(65536):
                if cancelar is not None and cancelar.is_set():
                    raise Cancelado()
                buf.extend(trozo)
        return bytes(buf)


def url_para_tamano(img: dict, tamano: str) -> str:
    if tamano == "Original":
        return img["image"]
    clave = tamano.split()[0]
    return img.get("thumbnails", {}).get(clave) or img["image"]


def url_preview(img: dict) -> str:
    t = img.get("thumbnails", {})
    return t.get("500") or t.get("large") or t.get("250") or t.get("small") or img["image"]


def etiqueta_imagen(img: dict) -> str:
    tipos = img.get("types") or ["Other"]
    return " + ".join(IMAGENES_ES.get(t, t) for t in tipos)


def puntuacion_imagen(img: dict) -> tuple[int, int, int]:
    tipos = set(img.get("types") or [])
    try:
        ancho = int(img.get("width", 0))
        alto = int(img.get("height", 0))
        pixeles = ancho * alto
    except (TypeError, ValueError):
        ancho = alto = 0
        pixeles = 0
    cuadrada = int(ancho > 0 and ancho == alto)
    sin_marca = int(not img.get("watermark") and "Watermark" not in tipos)
    return cuadrada, sin_marca, pixeles


def mejor_imagen(imgs: list[dict], tipo: str) -> dict | None:
    candidatas = [img for img in imgs if img.get(tipo)]
    return max(candidatas, key=puntuacion_imagen) if candidatas else None


def elegir_imagenes(imgs: list[dict], modo: str) -> list[dict]:
    if modo == "Todas las imágenes":
        return list(imgs)
    frente = mejor_imagen(imgs, "front") or max(imgs, key=puntuacion_imagen)
    elegidas = [frente]
    if modo == "Frontal y trasera":
        atras = mejor_imagen(imgs, "back")
        if atras is not None and atras is not frente:
            elegidas.append(atras)
    return elegidas


def entradas_lote(texto: str) -> list[tuple[str, str, str, str]]:
    """Lee líneas Artista - Álbum o CSV con columnas artista y álbum."""
    lineas = [linea for linea in texto.splitlines() if linea.strip() and not linea.lstrip().startswith("#")]
    if not lineas:
        return []
    separador = re.compile(r"\s+[-–—]\s+|\s*[|;\t]\s*")
    csv_mode = any(delimitador in lineas[0] for delimitador in (",", ";", "\t"))
    if not csv_mode:
        resultado = []
        for i, linea in enumerate(lineas):
            partes = separador.split(linea, maxsplit=1)
            resultado.append((f"l{i}", linea, partes[0].strip(), partes[1].strip())
                             if len(partes) == 2 and all(x.strip() for x in partes)
                             else (f"l{i}", linea, "", ""))
        return resultado

    try:
        dialecto = csv.Sniffer().sniff("\n".join(lineas[:5]), delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    filas = list(csv.reader(lineas, dialecto))
    encabezado = {celda.strip().lower() for celda in (filas[0] if filas else [])}
    tiene_encabezado = bool(encabezado & {"artista", "artist", "album", "álbum"})
    inicio = 1 if tiene_encabezado else 0
    resultado = []
    for i, fila in enumerate(filas[inicio:], start=inicio):
        artista, album = (fila[0].strip(), fila[1].strip()) if len(fila) >= 2 else ("", "")
        original = " | ".join(fila)
        resultado.append((f"l{i}", original, artista, album))
    return resultado


# "?"? Ampliación con IA (Real-ESRGAN ncnn-vulkan) "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?
_LOCK_IA = threading.Lock()  # una sola ampliación a la vez: la GPU no se comparte bien


def buscar_exe(ruta_cfg: str = "") -> Path | None:
    """Localiza realesrgan-ncnn-vulkan(.exe) en la ruta configurada o junto al script."""
    nombres = ["realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan"]
    candidatos: list[Path] = []
    if ruta_cfg:
        p = Path(ruta_cfg)
        candidatos.append(p)
        if p.is_dir():
            candidatos += [p / n for n in nombres]
    try:
        base = Path(__file__).resolve().parent
        raiz = base.parent
        carpetas = [
            base, raiz, base / "realesrgan", raiz / "realesrgan",
            *sorted(x for x in base.glob("realesrgan*") if x.is_dir()),
            *sorted(x for x in raiz.glob("realesrgan*") if x.is_dir()),
        ]
        for d in carpetas:
            candidatos += [d / n for n in nombres]
    except NameError:
        pass
    en_path = shutil.which("realesrgan-ncnn-vulkan")
    if en_path:
        candidatos.append(Path(en_path))
    existentes = [c for c in candidatos if c.is_file()]
    # Se prefiere una instalación que tenga la carpeta «models» (sin ella no funciona)
    return next((c for c in existentes if (c.parent / "models").is_dir()),
                existentes[0] if existentes else None)


def archivos_modelo(exe: Path, modelo: str) -> tuple[Path, Path]:
    """Devuelve los archivos del modelo para la escala x4 que usa la aplicación."""
    nombre = modelo
    if modelo == "realesr-animevideov3":
        nombre += "-x4"
    carpeta = exe.parent / "models"
    return carpeta / f"{nombre}.param", carpeta / f"{nombre}.bin"


def validar_instalacion_ia(exe: Path, modelo: str) -> None:
    if not exe.is_file():
        raise FileNotFoundError(f"No se encontró el ejecutable de Real-ESRGAN: {exe}")
    if not exe.parent.joinpath("models").is_dir():
        raise FileNotFoundError(f"Falta la carpeta models junto a Real-ESRGAN: {exe.parent}")
    param, pesos = archivos_modelo(exe, modelo)
    faltantes = [str(p.name) for p in (param, pesos) if not p.is_file()]
    if faltantes:
        raise FileNotFoundError(
            f"Faltan archivos del modelo {modelo}: {', '.join(faltantes)}"
        )


def ejecutar_realesrgan(exe: Path, entrada: Path, salida: Path, modelo: str, gpu: int,
                        tile: int, cancelar: threading.Event) -> None:
    validar_instalacion_ia(exe, modelo)
    cmd = [str(exe), "-i", str(entrada), "-o", str(salida), "-n", modelo, "-s", "4",
           "-m", str(exe.parent / "models"), "-g", str(gpu), "-t", str(tile)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sin ventana de consola en Windows
    log = salida.with_suffix(".log")
    with open(log, "wb") as f:
        proc = subprocess.Popen(cmd, cwd=str(exe.parent), stdout=f, stderr=subprocess.STDOUT,
                                creationflags=flags)
        inicio = time.monotonic()
        while proc.poll() is None:
            if cancelar.is_set():
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise Cancelado()
            if time.monotonic() - inicio > 1800:
                proc.kill()
                raise RuntimeError("La ampliación tardó más de 30 minutos y se detuvo.")
            time.sleep(0.2)
    if proc.returncode != 0 or not salida.is_file() or salida.stat().st_size == 0:
        try:
            cola = log.read_text(errors="ignore").strip().splitlines()[-3:]
        except OSError:
            cola = []
        detalle = " ".join(cola)[:500] or "no se generó una salida válida"
        raise RuntimeError("Real-ESRGAN falló: " + detalle)


def ampliar_ia(datos: bytes, snap: dict, cancelar: threading.Event,
               progreso=None) -> bytes | None:
    """Amplía con IA hasta que el lado mayor mida `ia_objetivo`. Devuelve PNG o None."""
    objetivo = int(snap["ia_objetivo"])
    if objetivo < 1:
        raise ValueError("El objetivo de ampliación debe ser mayor que cero.")
    with Image.open(io.BytesIO(datos)) as im:
        im.load()
        actual = im.convert("RGB")
    if max(actual.size) >= objetivo:
        return None  # ya es suficientemente grande: nunca se reduce ni se toca

    exe = Path(snap["ia_exe"])
    with _LOCK_IA, tempfile.TemporaryDirectory(prefix="portadas_ia_") as tmp:
        tmp = Path(tmp)
        pasada = 0
        while True:
            pasada += 1
            entrada, salida = tmp / f"in{pasada}.png", tmp / f"out{pasada}.png"
            actual.save(entrada)
            if progreso:
                progreso(f"ampliando con IA (pasada {pasada}, {actual.width}x{actual.height} -> x4)...")
            ejecutar_realesrgan(exe, entrada, salida, snap["ia_modelo"], int(snap["ia_gpu"]),
                                int(snap["ia_tile"]), cancelar)
            with Image.open(salida) as im:
                actual = im.convert("RGB")
            # Si con una pasada queda a menos de x2 del objetivo, el resto se completa con
            # Lanczos (mucho más rápido); si no, hace falta una segunda pasada de IA.
            if max(actual.size) >= objetivo / 2 or pasada >= 2:
                break

    lado = max(actual.size)
    if lado != objetivo:
        f = objetivo / lado
        actual = actual.resize((max(1, round(actual.width * f)), max(1, round(actual.height * f))),
                               Image.LANCZOS)
    salida = io.BytesIO()
    actual.save(salida, "PNG", optimize=False)
    return salida.getvalue()


def procesar_album(cliente: Cliente, album: Album, snap: dict,
                   cancelar: threading.Event, progreso=None) -> list[dict]:
    """Descarga las imágenes de un álbum. Devuelve una lista de resultados."""
    imgs = cliente.listado(album.mbid)
    if not imgs:
        raise SinPortada()

    elegidas = elegir_imagenes(imgs, snap["que_descargar"])
    base = nombre_base(snap["plantilla"], album)

    carpeta = Path(snap["directorio"])
    if snap["subcarpeta_artista"]:
        carpeta /= limpiar_nombre(album.artista)
    if len(elegidas) > 1:
        carpeta /= base  # varias imágenes: una carpeta por álbum

    usar_ia = bool(snap["ia_activa"] and snap["ia_exe"])
    extra_ia = f" (IA {int(snap['ia_objetivo'])}px)"
    ext_ia = ".jpg" if snap["formato"] == "JPG" else ".png"

    resultados, usados = [], Counter()
    for img in elegidas:
        if cancelar.is_set():
            raise Cancelado()

        if len(elegidas) == 1:
            sufijo = ""
        else:
            tipo = etiqueta_imagen(img)
            usados[tipo] += 1
            sufijo = f" - {tipo}" + (f" {usados[tipo]}" if usados[tipo] > 1 else "")

        url = img["image"] if usar_ia else url_para_tamano(img, snap["tamano"])
        datos = cliente.bytes_de(url, cancelar)

        # (bytes, texto extra del nombre, ¿es ampliada?)
        versiones: list[tuple[bytes, str, bool]] = [(datos, "", False)]
        if usar_ia:
            destino_ia = carpeta / f"{base}{sufijo}{extra_ia}{ext_ia}"
            if not (snap["si_existe"] == "Omitir" and destino_ia.exists()):
                ampliada = ampliar_ia(datos, snap, cancelar, progreso)
                if ampliada is not None:
                    versiones = [(ampliada, extra_ia, True)]
                    if snap["ia_guardar_original"]:
                        versiones.insert(0, (datos, "", False))

        for contenido, extra, es_ia in versiones:
            contenido, ext = convertir(contenido, snap["formato"])
            if snap["modo_impresion"]:
                contenido, ext = preparar_para_impresion(contenido, snap["formato"])
            destino = carpeta / f"{base}{sufijo}{extra}{ext}"

            if destino.exists():
                if snap["si_existe"] == "Omitir":
                    resultados.append({"ruta": destino, "omitido": True, "dim": None,
                                       "bytes": 0, "ia": es_ia})
                    continue
                if snap["si_existe"] == "Renombrar":
                    destino = ruta_libre(destino)

            with Image.open(io.BytesIO(contenido)) as im:
                dim = im.size
                informe = datos_impresion(im)
            huella = huella_imagen(contenido)
            escribir_atomico(destino, contenido)
            resultados.append({"ruta": destino, "omitido": False, "dim": dim,
                               "bytes": len(contenido), "ia": es_ia,
                               "dpi": informe["dpi"], "cuadrada": informe["cuadrada"],
                               "calidad": informe["calidad"], "huella": huella})
    return resultados


# .............................................................................
#  Temas
# .............................................................................
PALETAS = {
    "claro": dict(bg="#f3f4f6", surface="#ffffff", fg="#1f2328", muted="#6b7280",
                  accent="#2563eb", accent_hover="#1d4ed8", accent_fg="#ffffff",
                  border="#d5d9df", sel="#dbe7ff", sel_fg="#0b1f4d", hover="#e8ebf0"),
    "oscuro": dict(bg="#1b1c1f", surface="#26282c", fg="#e8e8e8", muted="#9aa0a6",
                   accent="#4f8cff", accent_hover="#6a9dff", accent_fg="#ffffff",
                   border="#3a3d43", sel="#34486b", sel_fg="#ffffff", hover="#33363c"),
}


