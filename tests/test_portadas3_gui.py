import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import portadas_gui as app


class Portadas3Tests(unittest.TestCase):
    def test_nombre_base_limpia_datos_invalidos(self):
        album = app.Album("mbid", "AC/DC", "Back:In Black", anio="1980")
        nombre = app.nombre_base("{artista} - {album} ({anio})", album)
        self.assertEqual(nombre, "ACDC - BackIn Black (1980)")

    def test_convertir_a_jpg_conserva_dimensiones(self):
        imagen = Image.new("RGB", (320, 240), "navy")
        entrada = io.BytesIO()
        imagen.save(entrada, "PNG")

        datos, extension = app.convertir(entrada.getvalue(), "JPG")

        self.assertEqual(extension, ".jpg")
        with Image.open(io.BytesIO(datos)) as salida:
            self.assertEqual(salida.format, "JPEG")
            self.assertEqual(salida.size, (320, 240))

    def test_validar_modelo_real_esrgan(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            exe = carpeta / "realesrgan-ncnn-vulkan.exe"
            modelos = carpeta / "models"
            modelos.mkdir()
            exe.touch()
            (modelos / "realesrgan-x4plus.param").touch()
            (modelos / "realesrgan-x4plus.bin").touch()

            app.validar_instalacion_ia(exe, "realesrgan-x4plus")

    def test_validar_modelo_falla_si_faltan_pesos(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            exe = carpeta / "realesrgan-ncnn-vulkan.exe"
            (carpeta / "models").mkdir()
            exe.touch()

            with self.assertRaises(FileNotFoundError):
                app.validar_instalacion_ia(exe, "realesrgan-x4plus")

    def test_datos_impresion_marca_portada_apta(self):
        informe = app.datos_impresion(Image.new("RGB", (4000, 4000)))

        self.assertEqual(informe["dpi"], 342)
        self.assertTrue(informe["cuadrada"])
        self.assertEqual(informe["calidad"], "apta")

    def test_huella_detecta_imagen_visualmente_igual(self):
        primera = io.BytesIO()
        segunda = io.BytesIO()
        Image.new("RGB", (200, 200), "red").save(primera, "PNG")
        Image.new("RGB", (100, 100), "red").save(segunda, "PNG")

        self.assertEqual(app.huella_imagen(primera.getvalue()), app.huella_imagen(segunda.getvalue()))

    def test_escanear_coleccion_encuentra_imagenes(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            Image.new("RGB", (4000, 4000), "black").save(carpeta / "portada.png")

            resultados = app.App._escanear_coleccion(carpeta)

            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]["dim"], "4000x4000")

    def test_ruta_duplicada_usa_huella_del_historial(self):
        historial = [{"ruta": "anterior.png", "huella": "abc"}]

        duplicada = app.ruta_duplicada(historial, "abc", Path("nueva.png"))

        self.assertEqual(duplicada, "anterior.png")

    def test_elegir_imagenes_prioriza_frontal_cuadrada(self):
        imagenes = [
            {"image": "rectangular", "front": True, "width": 5000, "height": 3000},
            {"image": "cuadrada", "front": True, "width": 3000, "height": 3000},
        ]

        elegida = app.elegir_imagenes(imagenes, "Solo frontal")

        self.assertEqual(elegida[0]["image"], "cuadrada")

    def test_elegir_imagenes_descarta_marca_de_agua_antes_de_resolucion(self):
        imagenes = [
            {"image": "marca", "front": True, "width": 5000, "height": 5000,
             "watermark": True},
            {"image": "limpia", "front": True, "width": 4000, "height": 4000},
        ]

        elegida = app.elegir_imagenes(imagenes, "Solo frontal")

        self.assertEqual(elegida[0]["image"], "limpia")

    def test_entradas_lote_lee_csv_con_encabezado(self):
        entradas = app.entradas_lote("artista,album\nPink Floyd,The Wall\n")

        self.assertEqual(entradas, [("l1", "Pink Floyd | The Wall", "Pink Floyd", "The Wall")])

    def test_entradas_lote_conserva_formato_texto(self):
        entradas = app.entradas_lote("Pink Floyd - The Wall\n")

        self.assertEqual(entradas[0][2:], ("Pink Floyd", "The Wall"))


if __name__ == "__main__":
    unittest.main()
