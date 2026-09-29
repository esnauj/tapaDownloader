

# .............................................................................
#  Aplicación
# .............................................................................
from .core import *


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = Config()
        self.cliente = Cliente(self.cfg["email"])
        self.esc = max(1.0, root.winfo_fpixels("1i") / 96)
        self.thumb = int(56 * self.esc)
        self.tam_preview = int(400 * self.esc)

        root.title(f"{APP_NAME}")
        root.geometry(self.cfg["geometria"])
        root.minsize(int(1000 * self.esc), int(640 * self.esc))

        # Comunicación hilos ' interfaz
        self._cola_ui: queue.Queue = queue.Queue()

        # Estado de búsqueda
        self.albums: dict[str, Album] = {}
        self.thumbs: dict[str, ImageTk.PhotoImage] = {}
        self.offset = 0
        self.total_mb = 0
        self._ultima_busqueda: tuple = ("", "", None)
        self._tok_busqueda = 0

        # Estado de vista previa
        self._iid_prev: str | None = None
        self._album_prev: Album | None = None
        self._imgs_prev: list[dict] = []
        self._idx_prev = 0
        self._tok_prev = 0
        self._foto_prev = None
        self._cache_prev: dict[str, Image.Image] = {}

        # Estado de descargas
        self.pool_min = ThreadPoolExecutor(max_workers=4)
        self.pool: ThreadPoolExecutor | None = None
        self._pool_n = 0
        self.cancelar = threading.Event()
        self.total = self.hechos = self.pend = 0
        self.contadores: Counter = Counter()

        # Historial
        self.archivo_historial = directorio_config() / "historial.json"
        self.historial: list[dict] = self._leer_historial()

        self._tk_widgets: list[tk.Widget] = []
        self._menus: list[tk.Menu] = []

        self._crear_estilos()
        self._construir_menu()
        self._construir_ui()
        self.aplicar_tema()
        self._cargar_historial_en_tabla()

        self.root.after(40, self._bombear_ui)
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.e_artista.focus_set()

    # ------------------------------------------------------------ infraestructura
    def ui(self, fn, *args):
        """Programa una llamada en el hilo de la interfaz (seguro desde otros hilos)."""
        self._cola_ui.put((fn, args))

    def _bombear_ui(self):
        try:
            while True:
                fn, args = self._cola_ui.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(40, self._bombear_ui)

    def hilo(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def cerrar(self):
        self.cancelar.set()
        self.cfg["geometria"] = self.root.geometry()
        self.cfg.guardar()
        self.pool_min.shutdown(wait=False, cancel_futures=True)
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    # ------------------------------------------------------------------- estilos
    def _crear_estilos(self):
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        tkfont.nametofont("TkTextFont").configure(size=10)
        self.f_base = base
        familia = base.actual("family")
        self.f_titulo = tkfont.Font(family=familia, size=13, weight="bold")
        self.f_chico = tkfont.Font(family=familia, size=9)

    def aplicar_tema(self):
        p = PALETAS[self.cfg["tema"]]
        self.p = p
        s = self.style
        self.root.configure(bg=p["bg"])

        s.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["surface"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["bg"], focuscolor=p["accent"], insertcolor=p["fg"])
        s.configure("TFrame", background=p["bg"])
        s.configure("Card.TFrame", background=p["surface"])
        s.configure("TLabel", background=p["bg"], foreground=p["fg"])
        s.configure("Card.TLabel", background=p["surface"], foreground=p["fg"])
        s.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
        s.configure("CardMuted.TLabel", background=p["surface"], foreground=p["muted"], font=self.f_chico)
        s.configure("Title.TLabel", background=p["surface"], foreground=p["fg"], font=self.f_titulo)

        s.configure("TButton", background=p["surface"], foreground=p["fg"], padding=(12, 6),
                    borderwidth=1, relief="flat", bordercolor=p["border"])
        s.map("TButton", background=[("disabled", p["bg"]), ("active", p["hover"])],
              foreground=[("disabled", p["muted"])])
        s.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    bordercolor=p["accent"], padding=(14, 7), font=self.f_base)
        s.map("Accent.TButton", background=[("disabled", p["border"]), ("active", p["accent_hover"])],
              foreground=[("disabled", p["muted"])], bordercolor=[("disabled", p["border"])])
        s.configure("Nav.TButton", padding=(8, 2))

        s.configure("TEntry", fieldbackground=p["surface"], foreground=p["fg"], padding=6,
                    bordercolor=p["border"])
        s.map("TEntry", bordercolor=[("focus", p["accent"])])
        s.configure("TCombobox", fieldbackground=p["surface"], background=p["surface"],
                    foreground=p["fg"], arrowcolor=p["fg"], padding=5, bordercolor=p["border"])
        s.map("TCombobox", fieldbackground=[("readonly", p["surface"])],
              foreground=[("readonly", p["fg"])], bordercolor=[("focus", p["accent"])])
        s.configure("TSpinbox", fieldbackground=p["surface"], foreground=p["fg"], padding=5,
                    arrowcolor=p["fg"], background=p["surface"])
        self.root.option_add("*TCombobox*Listbox.background", p["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])

        s.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
        s.map("TCheckbutton", background=[("active", p["bg"])])

        s.configure("Treeview", background=p["surface"], fieldbackground=p["surface"],
                    foreground=p["fg"], rowheight=self.thumb + 10, borderwidth=0,
                    bordercolor=p["border"])
        s.map("Treeview", background=[("selected", p["sel"])], foreground=[("selected", p["sel_fg"])])
        s.configure("Treeview.Heading", background=p["bg"], foreground=p["muted"], relief="flat",
                    padding=(8, 6), borderwidth=0, font=self.f_base)
        s.map("Treeview.Heading", background=[("active", p["hover"])])
        s.configure("Compact.Treeview", rowheight=int(26 * self.esc))
        s.map("Compact.Treeview", background=[("selected", p["sel"])],
              foreground=[("selected", p["sel_fg"])])

        s.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(18, 9),
                    borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", p["surface"])],
              foreground=[("selected", p["accent"])])

        s.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
        s.configure("TLabelframe.Label", background=p["bg"], foreground=p["muted"])
        s.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["border"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"])
        s.configure("TScrollbar", background=p["border"], troughcolor=p["bg"], arrowcolor=p["fg"],
                    bordercolor=p["bg"], relief="flat")
        s.map("TScrollbar", background=[("active", p["muted"])])
        s.configure("TPanedwindow", background=p["bg"])
        s.configure("Sash", background=p["bg"])

        # Widgets de Tk clásico
        for w in self._tk_widgets:
            if isinstance(w, tk.Text):
                w.configure(bg=p["surface"], fg=p["fg"], insertbackground=p["fg"],
                            selectbackground=p["sel"], selectforeground=p["sel_fg"],
                            highlightbackground=p["border"], highlightcolor=p["accent"])
        for m in self._menus:
            m.configure(bg=p["surface"], fg=p["fg"], activebackground=p["accent"],
                        activeforeground=p["accent_fg"], borderwidth=0)

        if hasattr(self, "tree"):
            for t in (self.tree,):
                t.tag_configure("sin", foreground=p["muted"])
            self.ph_thumb_img = Image.new("RGB", (self.thumb, self.thumb), p["border"])
            self.ph_thumb = ImageTk.PhotoImage(self.ph_thumb_img)
            for iid in self.tree.get_children():
                if iid not in self.thumbs:
                    self.tree.item(iid, image=self.ph_thumb)

    def alternar_tema(self):
        self.cfg["tema"] = "oscuro" if self.cfg["tema"] == "claro" else "claro"
        self.cfg.guardar()
        self.aplicar_tema()

    # ---------------------------------------------------------------------- menú
    def _construir_menu(self):
        barra = tk.Menu(self.root)
        self._menus.append(barra)

        m_archivo = tk.Menu(barra, tearoff=False)
        m_archivo.add_command(label="Carpeta de descarga", command=self.cambiar_directorio)
        m_archivo.add_command(label="Abrir carpeta de descarga", command=self.abrir_directorio)
        m_archivo.add_separator()
        m_archivo.add_command(label="Ajustes", accelerator="Ctrl+,", command=self.abrir_ajustes)
        m_archivo.add_separator()
        m_archivo.add_command(label="Salir", command=self.cerrar)
        barra.add_cascade(label="Archivo", menu=m_archivo)

        m_ver = tk.Menu(barra, tearoff=False)
        m_ver.add_command(label="Alternar tema claro / oscuro", accelerator="Ctrl+T",
                          command=self.alternar_tema)
        barra.add_cascade(label="Ver", menu=m_ver)

        m_ayuda = tk.Menu(barra, tearoff=False)
        m_ayuda.add_command(label="Atajos de teclado", command=self.mostrar_atajos)
        m_ayuda.add_command(label="Acerca de", command=self.acerca_de)
        barra.add_cascade(label="Ayuda", menu=m_ayuda)

        self._menus.extend([m_archivo, m_ver, m_ayuda])
        self.root.configure(menu=barra)

        self.root.bind("<Control-f>", lambda e: self.e_artista.focus_set())
        self.root.bind("<Control-d>", lambda e: self.descargar_seleccion())
        self.root.bind("<Control-t>", lambda e: self.alternar_tema())
        self.root.bind("<Control-comma>", lambda e: self.abrir_ajustes())

    def mostrar_atajos(self):
        messagebox.showinfo("Atajos de teclado", (
            "Ctrl+F        Ir al campo de búsqueda\n"
            "Enter          Buscar\n"
            "Ctrl+A        Seleccionar todos los resultados\n"
            "Ctrl+D        Descargar la selección\n"
            "Ctrl+T        Cambiar tema claro/oscuro\n"
            "Ctrl+,        Ajustes\n"
            "Clic derecho  Menú contextual del resultado\n\n"
            "Tip: Shift+clic o Ctrl+clic para elegir varios álbumes."))

    def acerca_de(self):
        messagebox.showinfo("Acerca de", f"{APP_NAME} {APP_VERSION}\n\n"
                            "Datos: MusicBrainz\nImágenes: Cover Art Archive")

    # ------------------------------------------------------------- construcción UI
    def _construir_ui(self):
        self._barra_estado()  # se empaqueta primero para que nunca quede fuera de la ventana
        contenedor = ttk.Frame(self.root, padding=(14, 12, 14, 0))
        contenedor.pack(fill="both", expand=True)

        self._panel_opciones(contenedor)
        self.notebook = ttk.Notebook(contenedor)
        self.notebook.pack(fill="both", expand=True)

        t_buscar = ttk.Frame(self.notebook, padding=14)
        t_lote = ttk.Frame(self.notebook, padding=14)
        t_act = ttk.Frame(self.notebook, padding=14)
        t_col = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(t_buscar, text="  Buscar  ")
        self.notebook.add(t_lote, text="  Lote  ")
        self.notebook.add(t_act, text="  Actividad  ")
        self.notebook.add(t_col, text="  Colección  ")
        self._tab_buscar(t_buscar)
        self._tab_lote(t_lote)
        self._tab_actividad(t_act)
        self._tab_coleccion(t_col)

    # ---- pestaña Buscar
    def _tab_buscar(self, parent):
        barra = ttk.Frame(parent, style="Card.TFrame")
        barra.pack(fill="x", pady=(0, 12))
        barra.columnconfigure(0, weight=1)
        barra.columnconfigure(1, weight=1)

        ttk.Label(barra, text="Artista", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(barra, text="Álbum", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(barra, text="Tipo", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.v_artista, self.v_album = tk.StringVar(), tk.StringVar()
        self.e_artista = ttk.Entry(barra, textvariable=self.v_artista)
        self.e_album = ttk.Entry(barra, textvariable=self.v_album)
        self.e_artista.grid(row=1, column=0, sticky="ew")
        self.e_album.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        self.v_tipo = tk.StringVar(value="Todos")
        ttk.Combobox(barra, textvariable=self.v_tipo, values=list(TIPOS_BUSQUEDA),
                     state="readonly", width=10).grid(row=1, column=2, padx=(10, 0))
        self.btn_buscar = ttk.Button(barra, text="Buscar", style="Accent.TButton",
                                     command=lambda: self.buscar())
        self.btn_buscar.grid(row=1, column=3, padx=(10, 0))
        for e in (self.e_artista, self.e_album):
            e.bind("<Return>", lambda _e: self.buscar())

        panel = ttk.PanedWindow(parent, orient="horizontal")
        panel.pack(fill="both", expand=True)

        # Izquierda: resultados
        izq = ttk.Frame(panel)
        panel.add(izq, weight=3)

        marco = ttk.Frame(izq, style="Card.TFrame")
        marco.pack(fill="both", expand=True)
        columnas = ("artista", "album", "tipo", "anio", "estado")
        self.tree = ttk.Treeview(marco, columns=columnas, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=self.thumb + 24, stretch=False)
        for col, texto, ancho, estira in (
            ("artista", "Artista", 170, True), ("album", "Álbum", 240, True),
            ("tipo", "Tipo", 100, False), ("anio", "Año", 55, False), ("estado", "Portada", 110, False),
        ):
            self.tree.heading(col, text=texto, anchor="w")
            self.tree.column(col, width=ancho, stretch=estira, anchor="w")
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.al_seleccionar)
        self.tree.bind("<Double-1>", lambda e: self.descargar_seleccion())
        self.tree.bind("<Control-a>", lambda e: (self.seleccionar_todo(), "break")[1])
        for ev in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.tree.bind(ev, self._menu_contextual)

        self.menu_ctx = tk.Menu(self.root, tearoff=False)
        self._menus.append(self.menu_ctx)
        self.menu_ctx.add_command(label="Descargar", command=self.descargar_seleccion)
        self.menu_ctx.add_command(label="Copiar URL de la imagen original", command=self.copiar_url)
        self.menu_ctx.add_command(label="Abrir en MusicBrainz", command=self.abrir_musicbrainz)

        pie = ttk.Frame(izq)
        pie.pack(fill="x", pady=(10, 0))
        self.v_contador = tk.StringVar(value="Buscá un artista o un álbum para empezar.")
        ttk.Label(pie, textvariable=self.v_contador, style="Muted.TLabel").pack(side="left")
        self.btn_desc = ttk.Button(pie, text="Descargar selección", style="Accent.TButton",
                                   command=self.descargar_seleccion, state="disabled")
        self.btn_desc.pack(side="right")
        self.btn_comparar = ttk.Button(pie, text="Comparar seleccionadas",
                           command=self.comparar_seleccion, state="disabled")
        self.btn_comparar.pack(side="right", padx=8)
        ttk.Button(pie, text="Seleccionar todo", command=self.seleccionar_todo).pack(side="right", padx=8)
        self.btn_mas = ttk.Button(pie, text="Cargar más", command=lambda: self.buscar(anexar=True),
                                  state="disabled")
        self.btn_mas.pack(side="right")

        # Derecha: vista previa
        der = ttk.Frame(panel, style="Card.TFrame", padding=16)
        panel.add(der, weight=2)
        # Los controles se empaquetan desde abajo para que nunca queden tapados por la imagen
        self.lbl_prev = ttk.Label(der, style="Card.TLabel", anchor="center", justify="center",
                                  text="Elegí un resultado\npara ver la portada")
        self.v_titulo = tk.StringVar()
        self.v_meta = tk.StringVar()
        self.v_impresion = tk.StringVar()
        self.v_nav = tk.StringVar(value="")

        acciones = ttk.Frame(der, style="Card.TFrame")
        acciones.pack(side="bottom", pady=(12, 0))
        self.btn_guardar_como = ttk.Button(acciones, text="Guardar como",
                                           command=self.guardar_como, state="disabled")
        self.btn_guardar_como.pack(side="left")
        ttk.Button(acciones, text="MusicBrainz", command=self.abrir_musicbrainz).pack(side="left", padx=(8, 0))

        ttk.Label(der, textvariable=self.v_meta, style="CardMuted.TLabel", justify="center").pack(side="bottom")
        ttk.Label(der, textvariable=self.v_impresion, style="CardMuted.TLabel", justify="center").pack(side="bottom")
        ttk.Label(der, textvariable=self.v_titulo, style="Title.TLabel", wraplength=self.tam_preview,
                  justify="center").pack(side="bottom", pady=(12, 0))

        nav = ttk.Frame(der, style="Card.TFrame")
        nav.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_ant = ttk.Button(nav, text="<", style="Nav.TButton", width=3,
                                  command=lambda: self._navegar(-1), state="disabled")
        self.btn_sig = ttk.Button(nav, text=">", style="Nav.TButton", width=3,
                                  command=lambda: self._navegar(1), state="disabled")
        self.btn_ant.pack(side="left")
        ttk.Label(nav, textvariable=self.v_nav, style="CardMuted.TLabel", anchor="center").pack(
            side="left", fill="x", expand=True)
        self.btn_sig.pack(side="right")

        self.lbl_prev.pack(fill="both", expand=True)

    # ---- pestaña Lote
    def _tab_lote(self, parent):
        ttk.Label(parent, style="Muted.TLabel", text=(
            "Un álbum por línea con el formato  Artista - Álbum   "
            "(ej.: Pink Floyd - The Dark Side of the Moon).  Las líneas que empiezan con # se ignoran."
        )).pack(anchor="w", pady=(0, 10))

        panel = ttk.PanedWindow(parent, orient="horizontal")
        panel.pack(fill="both", expand=True)

        izq = ttk.Frame(panel)
        panel.add(izq, weight=2)
        marco = ttk.Frame(izq)
        marco.pack(fill="both", expand=True)
        self.txt_lote = tk.Text(marco, wrap="none", undo=True, relief="flat", borderwidth=0,
                                highlightthickness=1, padx=10, pady=8, font=self.f_base)
        self._tk_widgets.append(self.txt_lote)
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.txt_lote.yview)
        self.txt_lote.configure(yscrollcommand=sb.set)
        self.txt_lote.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        botones = ttk.Frame(izq)
        botones.pack(fill="x", pady=(10, 0))
        ttk.Button(botones, text="Abrir archivo .txt", command=self.abrir_archivo_lote).pack(side="left")
        ttk.Button(botones, text="Limpiar", command=lambda: self.txt_lote.delete("1.0", "end")).pack(
            side="left", padx=8)
        ttk.Button(botones, text="Procesar lote", style="Accent.TButton",
                   command=self.procesar_lote).pack(side="right")
        ttk.Button(botones, text="Reintentar errores", command=self.reintentar_lote).pack(
            side="right", padx=8)

        der = ttk.Frame(panel, style="Card.TFrame")
        panel.add(der, weight=3)
        self.lote_tree = ttk.Treeview(der, columns=("entrada", "resultado", "estado"), show="headings",
                                      style="Compact.Treeview", selectmode="browse")
        for col, texto, ancho in (("entrada", "Línea", 220), ("resultado", "Coincidencia", 260),
                                  ("estado", "Estado", 150)):
            self.lote_tree.heading(col, text=texto, anchor="w")
            self.lote_tree.column(col, width=ancho, anchor="w")
        sb2 = ttk.Scrollbar(der, orient="vertical", command=self.lote_tree.yview)
        self.lote_tree.configure(yscrollcommand=sb2.set)
        self.lote_tree.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

    # ---- pestaña Actividad
    def _tab_actividad(self, parent):
        marco = ttk.Frame(parent, style="Card.TFrame")
        marco.pack(fill="both", expand=True)
        cols = ("hora", "artista", "album", "estado", "detalle", "resolucion", "dpi", "ruta")
        self.act_tree = ttk.Treeview(marco, columns=cols, show="headings", style="Compact.Treeview",
                                     selectmode="browse")
        for col, texto, ancho, estira in (
            ("hora", "Fecha", 120, False), ("artista", "Artista", 150, False),
            ("album", "Álbum", 200, False), ("estado", "Estado", 140, False),
            ("detalle", "Detalle", 260, False), ("resolucion", "Resolución", 90, False),
            ("dpi", "DPI", 55, False), ("ruta", "Archivo", 300, True),
        ):
            self.act_tree.heading(col, text=texto, anchor="w")
            self.act_tree.column(col, width=ancho, anchor="w", stretch=estira)
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.act_tree.yview)
        self.act_tree.configure(yscrollcommand=sb.set)
        self.act_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.act_tree.bind("<Double-1>", lambda e: self._abrir_actividad())

        pie = ttk.Frame(parent)
        pie.pack(fill="x", pady=(10, 0))
        ttk.Button(pie, text="Abrir imagen", command=self._abrir_actividad).pack(side="left")
        ttk.Button(pie, text="Mostrar en carpeta", command=lambda: self._abrir_actividad(True)).pack(
            side="left", padx=8)
        ttk.Button(pie, text="Limpiar historial", command=self.limpiar_historial).pack(side="right")

    def _tab_coleccion(self, parent):
        encabezado = ttk.Frame(parent)
        encabezado.pack(fill="x", pady=(0, 10))
        self.v_coleccion = tk.StringVar(value="Escaneá la carpeta de descarga para ver sus imágenes.")
        ttk.Label(encabezado, textvariable=self.v_coleccion, style="Muted.TLabel").pack(side="left")
        ttk.Button(encabezado, text="Actualizar", command=self.refrescar_coleccion).pack(side="right")

        marco = ttk.Frame(parent, style="Card.TFrame")
        marco.pack(fill="both", expand=True)
        cols = ("archivo", "resolucion", "dpi", "calidad", "ruta")
        self.col_tree = ttk.Treeview(marco, columns=cols, show="headings", style="Compact.Treeview")
        for col, texto, ancho, estira in (
            ("archivo", "Archivo", 250, False), ("resolucion", "Resolución", 90, False),
            ("dpi", "DPI", 55, False), ("calidad", "Calidad", 150, False),
            ("ruta", "Ruta", 420, True),
        ):
            self.col_tree.heading(col, text=texto, anchor="w")
            self.col_tree.column(col, width=ancho, stretch=estira, anchor="w")
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.col_tree.yview)
        self.col_tree.configure(yscrollcommand=sb.set)
        self.col_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.col_tree.bind("<Double-1>", lambda _e: self.abrir_coleccion())
        self._coleccion_resultados = []

        pie = ttk.Frame(parent)
        pie.pack(fill="x", pady=(10, 0))
        ttk.Button(pie, text="Abrir imagen", command=self.abrir_coleccion).pack(side="left")
        ttk.Button(pie, text="Mostrar carpeta", command=lambda: self.abrir_coleccion(True)).pack(
            side="left", padx=8)

    def refrescar_coleccion(self):
        carpeta = Path(self.cfg["directorio"])
        self.v_coleccion.set(f"Escaneando {carpeta}")

        def trabajo():
            try:
                resultados = self._escanear_coleccion(carpeta)
            except Exception as e:
                self.ui(self._error_coleccion, e)
            else:
                self.ui(self._mostrar_coleccion, resultados)

        self.hilo(trabajo)

    @staticmethod
    def _escanear_coleccion(carpeta: Path) -> list[dict]:
        extensiones = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        resultados = []
        if not carpeta.is_dir():
            return resultados
        for ruta in carpeta.rglob("*"):
            if ruta.is_file() and ruta.suffix.lower() in extensiones:
                informe = inspeccionar_archivo(ruta)
                if informe:
                    resultados.append({"ruta": ruta, **informe})
        return sorted(resultados, key=lambda x: str(x["ruta"]).lower())

    def _mostrar_coleccion(self, resultados):
        self.col_tree.delete(*self.col_tree.get_children())
        for i, dato in enumerate(resultados):
            self.col_tree.insert("", "end", iid=str(i), values=(
                dato["ruta"].name, dato["dim"], dato["dpi"], dato["calidad"], str(dato["ruta"])))
        self._coleccion_resultados = resultados
        self.v_coleccion.set(f"{len(resultados)} imágenes encontradas en {self.cfg['directorio']}")

    def _error_coleccion(self, error):
        self.v_coleccion.set(f"No se pudo escanear la colección: {mensaje_error(error)}")

    def abrir_coleccion(self, carpeta=False):
        sel = self.col_tree.selection()
        if not sel:
            return
        ruta = self._coleccion_resultados[int(sel[0])]["ruta"]
        (mostrar_en_carpeta if carpeta else abrir_ruta)(ruta)

    # ---- panel de opciones + barra de estado
    def _panel_opciones(self, parent):
        marco = ttk.LabelFrame(parent, text=" Opciones de descarga ", padding=(12, 8, 12, 10))
        marco.pack(fill="x", side="bottom", pady=(10, 0))
        self.v_opciones = {}

        def combo(col, texto, clave, valores, ancho):
            ttk.Label(marco, text=texto).grid(row=0, column=col * 2, sticky="w", padx=(0 if col == 0 else 16, 6))
            var = tk.StringVar(value=self.cfg[clave])
            self.v_opciones[clave] = var
            var.trace_add("write", lambda *_: (self.cfg.__setitem__(clave, var.get()), self.cfg.guardar()))
            ttk.Combobox(marco, textvariable=var, values=valores, state="readonly",
                         width=ancho).grid(row=0, column=col * 2 + 1)

        combo(0, "Descargar", "que_descargar", QUE_DESCARGAR, 18)
        combo(1, "Tamaño", "tamano", TAMANOS, 9)
        combo(2, "Formato", "formato", FORMATOS, 9)
        combo(3, "Si ya existe", "si_existe", SI_EXISTE, 12)

        # Fila de ampliación con IA
        ia = ttk.Frame(marco)
        ia.grid(row=1, column=0, columnspan=9, sticky="ew", pady=(10, 0))
        self.v_ia = tk.BooleanVar(value=self.cfg["ia_activa"])
        ttk.Checkbutton(ia, text="Ampliar con IA las portadas menores a", variable=self.v_ia,
                        command=self._al_activar_ia).pack(side="left")
        self.v_ia_obj = tk.StringVar(value=str(self.cfg["ia_objetivo"]))
        self.v_ia_obj.trace_add("write", lambda *_: self._guardar_objetivo_ia())
        ttk.Combobox(ia, textvariable=self.v_ia_obj, values=OBJETIVOS_IA, width=6).pack(
            side="left", padx=(8, 4))
        ttk.Label(ia, text="px", style="Muted.TLabel").pack(side="left")
        ttk.Label(ia, text="   (se usa la imagen original; las que ya son grandes no se tocan)",
                  style="Muted.TLabel").pack(side="left")
        self.v_modo_impresion = tk.BooleanVar(value=self.cfg["modo_impresion"])
        ttk.Checkbutton(ia, text="Lista para imprimir (300 DPI)",
                variable=self.v_modo_impresion,
                command=self._alternar_modo_impresion).pack(side="left", padx=(14, 0))

        fila = ttk.Frame(marco)
        fila.grid(row=2, column=0, columnspan=9, sticky="ew", pady=(10, 0))
        ttk.Label(fila, text="Carpeta").pack(side="left", padx=(0, 12))
        self.v_dir = tk.StringVar(value=acortar(self.cfg["directorio"]))
        ttk.Label(fila, textvariable=self.v_dir, style="Muted.TLabel").pack(side="left")
        ttk.Button(fila, text="Ajustes", command=self.abrir_ajustes).pack(side="right")
        ttk.Button(fila, text="Abrir", command=self.abrir_directorio).pack(side="right", padx=6)
        ttk.Button(fila, text="Cambiar", command=self.cambiar_directorio).pack(side="right")
        marco.columnconfigure(8, weight=1)

    def _barra_estado(self):
        barra = ttk.Frame(self.root, padding=(14, 8, 14, 10))
        barra.pack(fill="x", side="bottom")
        self.v_estado = tk.StringVar(value="Listo.")
        ttk.Label(barra, textvariable=self.v_estado, style="Muted.TLabel").pack(side="left")
        self.btn_cancel = ttk.Button(barra, text="Cancelar", command=self.cancelar_descargas, state="disabled")
        self.btn_cancel.pack(side="right")
        self.v_prog = tk.StringVar(value="")
        ttk.Label(barra, textvariable=self.v_prog, style="Muted.TLabel", width=8, anchor="e").pack(
            side="right", padx=(0, 8))
        self.barra = ttk.Progressbar(barra, length=int(220 * self.esc), mode="determinate", maximum=1)
        self.barra.pack(side="right", padx=(0, 8))

    # ............................................................... carpeta / ajustes
    def cambiar_directorio(self):
        carpeta = filedialog.askdirectory(title="Carpeta de descarga",
                                          initialdir=self.cfg["directorio"] if Path(self.cfg["directorio"]).exists() else str(Path.home()))
        if carpeta:
            self.cfg["directorio"] = carpeta
            self.cfg.guardar()
            self.v_dir.set(acortar(carpeta))
            self.v_estado.set(f"Carpeta de descarga: {carpeta}")

    def _guardar_objetivo_ia(self):
        try:
            v = int(self.v_ia_obj.get())
        except ValueError:
            return
        if 500 <= v <= 16000:
            self.cfg["ia_objetivo"] = v
            self.cfg.guardar()

    def _alternar_modo_impresion(self):
        self.cfg["modo_impresion"] = self.v_modo_impresion.get()
        self.cfg.guardar()

    def aplicar_preset(self, nombre):
        preset = PRESETS_SALIDA.get(nombre)
        if not preset:
            return
        self.cfg.update(preset)
        for clave, valor in preset.items():
            variable = self.v_opciones.get(clave)
            if variable is not None:
                variable.set(valor)
        self.v_ia.set(preset["ia_activa"])
        self.v_ia_obj.set(str(preset["ia_objetivo"]))
        self.v_modo_impresion.set(preset["modo_impresion"])
        self.cfg.guardar()
        self.v_estado.set(f"Preset aplicado: {nombre}")

    def abrir_directorio(self):
        d = Path(self.cfg["directorio"])
        d.mkdir(parents=True, exist_ok=True)
        abrir_ruta(d)

    def abrir_ajustes(self, pestana: int = 0):
        p = self.p
        win = tk.Toplevel(self.root)
        win.title("Ajustes")
        win.configure(bg=p["bg"])
        win.transient(self.root)
        win.resizable(False, False)

        cont = ttk.Frame(win, padding=(16, 16, 16, 14))
        cont.pack(fill="both", expand=True)
        nb = ttk.Notebook(cont)
        nb.pack(fill="both", expand=True)
        f = ttk.Frame(nb, padding=18)
        g = ttk.Frame(nb, padding=18)
        nb.add(f, text="  General  ")
        nb.add(g, text="  Ampliación con IA  ")
        nb.select(pestana)
        f.columnconfigure(1, weight=1)
        g.columnconfigure(1, weight=1)

        # ---------------- General
        v_dir = tk.StringVar(value=self.cfg["directorio"])
        v_plantilla = tk.StringVar(value=self.cfg["plantilla"])
        v_sub = tk.BooleanVar(value=self.cfg["subcarpeta_artista"])
        v_simult = tk.IntVar(value=self.cfg["descargas_simultaneas"])
        v_max = tk.IntVar(value=self.cfg["max_resultados"])
        v_abrir = tk.BooleanVar(value=self.cfg["abrir_al_terminar"])
        v_email = tk.StringVar(value=self.cfg["email"])
        v_ej = tk.StringVar()
        v_preset = tk.StringVar(value="Elegir preset")

        ttk.Label(f, text="Carpeta de descarga").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_dir, width=48).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(f, text="Examinar", command=lambda: v_dir.set(
            filedialog.askdirectory(parent=win, initialdir=v_dir.get()) or v_dir.get())).grid(row=0, column=2)

        ttk.Label(f, text="Nombre del archivo").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_plantilla).grid(row=1, column=1, columnspan=2, sticky="ew", padx=8)
        ttk.Label(f, style="Muted.TLabel", text="Variables:  {artista}  {album}  {anio}  {tipo}").grid(
            row=2, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Label(f, textvariable=v_ej, style="Muted.TLabel").grid(row=3, column=1, columnspan=2,
                                                                    sticky="w", padx=8, pady=(0, 6))

        def actualizar_ejemplo(*_):
            demo = Album("x", "Pink Floyd", "The Dark Side of the Moon", "Álbum", "1973")
            v_ej.set("Ejemplo:  " + nombre_base(v_plantilla.get() or "{artista} - {album}", demo) + ".jpg")
        v_plantilla.trace_add("write", actualizar_ejemplo)
        actualizar_ejemplo()

        ttk.Checkbutton(f, text="Crear una subcarpeta por artista", variable=v_sub).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(f, text="Abrir la carpeta al terminar las descargas", variable=v_abrir).grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8, pady=4)

        ttk.Label(f, text="Descargas simultáneas").grid(row=6, column=0, sticky="w", pady=6)
        ttk.Spinbox(f, from_=1, to=8, textvariable=v_simult, width=6).grid(row=6, column=1, sticky="w", padx=8)
        ttk.Label(f, text="Resultados por búsqueda").grid(row=7, column=0, sticky="w", pady=6)
        ttk.Spinbox(f, from_=10, to=100, increment=10, textvariable=v_max, width=6).grid(
            row=7, column=1, sticky="w", padx=8)

        ttk.Label(f, text="Tu email (User-Agent)").grid(row=8, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_email).grid(row=8, column=1, columnspan=2, sticky="ew", padx=8)
        ttk.Label(f, style="Muted.TLabel",
                  text="MusicBrainz pide identificar a las aplicaciones que usan su API.").grid(
            row=9, column=1, columnspan=2, sticky="w", padx=8)

        ttk.Label(f, text="Preset de salida").grid(row=10, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=v_preset, values=list(PRESETS_SALIDA), state="readonly",
                     width=28).grid(row=10, column=1, sticky="w", padx=8)
        ttk.Button(f, text="Aplicar", command=lambda: self.aplicar_preset(v_preset.get())).grid(
            row=10, column=2, padx=8)

        # ---------------- Ampliación con IA
        v_exe = tk.StringVar(value=self.cfg["ia_exe"])
        v_modelo = tk.StringVar(value=self.cfg["ia_modelo"])
        v_orig = tk.BooleanVar(value=self.cfg["ia_guardar_original"])
        v_gpu = tk.IntVar(value=self.cfg["ia_gpu"])
        v_tile = tk.IntVar(value=self.cfg["ia_tile"])
        v_det = tk.StringVar()
        v_res = tk.StringVar()

        ttk.Label(g, style="Muted.TLabel", justify="left", text=(
            "Usa Real-ESRGAN (ncnn-vulkan), que funciona con tu Radeon RX 570 sin CUDA.\n"
            "Bajá «realesrgan-ncnn-vulkan-20220424-windows.zip» (página de Real-ESRGAN,\n"
            "versión v0.2.5.0): trae el .exe y la carpeta «models». Descomprimilo junto a\n"
            "portadas.py, o indicá acá dónde está el .exe.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(g, text="Ejecutable").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(g, textvariable=v_exe, width=46).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(g, text="Examinar", command=lambda: v_exe.set(
            filedialog.askopenfilename(parent=win, title="realesrgan-ncnn-vulkan.exe",
                                       filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")])
            or v_exe.get())).grid(row=1, column=2)
        ttk.Label(g, textvariable=v_det, style="Muted.TLabel").grid(
            row=2, column=1, columnspan=2, sticky="w", padx=8)

        def detectar(*_):
            exe = buscar_exe(v_exe.get().strip())
            if exe is None:
                v_det.set("No encontrado todavía.")
            else:
                try:
                    validar_instalacion_ia(exe, v_modelo.get())
                except FileNotFoundError as e:
                    v_det.set(f"Error: {e}")
                else:
                    v_det.set(f"OK Detectado: {acortar(str(exe), 60)}")
        v_exe.trace_add("write", detectar)
        detectar()

        ttk.Label(g, text="Modelo").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(g, textvariable=v_modelo, values=MODELOS_IA, state="readonly", width=28).grid(
            row=3, column=1, sticky="w", padx=8)
        ttk.Label(g, style="Muted.TLabel", text="«x4plus» para portadas con fotos o arte; «anime» para ilustración plana.").grid(
            row=4, column=1, columnspan=2, sticky="w", padx=8)

        ttk.Checkbutton(g, text="Conservar también la imagen original sin ampliar",
                        variable=v_orig).grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=8)

        ttk.Label(g, text="GPU").grid(row=6, column=0, sticky="w", pady=6)
        ttk.Spinbox(g, from_=0, to=7, textvariable=v_gpu, width=6).grid(row=6, column=1, sticky="w", padx=8)
        ttk.Label(g, style="Muted.TLabel",
                  text="0 = primera GPU. Si tu equipo tiene además gráfica integrada y usa la incorrecta, probá con 1.").grid(
            row=7, column=1, columnspan=2, sticky="w", padx=8)

        ttk.Label(g, text="Tile").grid(row=8, column=0, sticky="w", pady=6)
        ttk.Spinbox(g, from_=0, to=1000, increment=50, textvariable=v_tile, width=6).grid(
            row=8, column=1, sticky="w", padx=8)
        ttk.Label(g, style="Muted.TLabel",
                  text="0 = automático. Si da error de memoria de video, probá 200 (o 100).").grid(
            row=9, column=1, columnspan=2, sticky="w", padx=8)

        def probar():
            exe = buscar_exe(v_exe.get().strip())
            if exe is None:
                v_res.set("Primero indicá dónde está realesrgan-ncnn-vulkan.exe.")
                return
            v_res.set("Probando con una imagen de 128 px")
            modelo, gpu, tile = v_modelo.get(), int(v_gpu.get() or 0), int(v_tile.get() or 0)

            def trabajo():
                try:
                    validar_instalacion_ia(exe, modelo)
                    inicio = time.monotonic()
                    with tempfile.TemporaryDirectory(prefix="portadas_test_") as tmp:
                        ent, sal = Path(tmp) / "in.png", Path(tmp) / "out.png"
                        Image.linear_gradient("L").resize((128, 128)).convert("RGB").save(ent)
                        ejecutar_realesrgan(exe, ent, sal, modelo, gpu, tile, threading.Event())
                        with Image.open(sal) as im:
                            w = im.width
                    self.ui(v_res.set, f"OK Funciona: 128 -> {w} px en {time.monotonic() - inicio:.1f} s")
                except Exception as e:
                    self.ui(v_res.set, f"Error: {mensaje_error(e)}")
            self.hilo(trabajo)

        botones_ia = ttk.Frame(g)
        botones_ia.grid(row=10, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Button(botones_ia, text="Probar instalación", command=probar).pack(side="left")
        ttk.Button(botones_ia, text="Abrir página de descarga",
                   command=lambda: webbrowser.open(REALESRGAN_RELEASES)).pack(side="left", padx=8)
        ttk.Label(g, textvariable=v_res, style="Muted.TLabel", wraplength=520, justify="left").grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # ---------------- Guardar
        def guardar():
            try:
                simult = max(1, min(8, int(v_simult.get())))
                maxr = max(10, min(100, int(v_max.get())))
                gpu = max(0, min(7, int(v_gpu.get())))
                tile = max(0, int(v_tile.get()))
            except (ValueError, tk.TclError):
                messagebox.showwarning("Ajustes", "Revisá los valores numéricos.", parent=win)
                return
            if not v_dir.get().strip() or not v_plantilla.get().strip():
                messagebox.showwarning("Ajustes", "La carpeta y el nombre no pueden estar vacíos.", parent=win)
                return
            self.cfg.update(directorio=v_dir.get().strip(), plantilla=v_plantilla.get().strip(),
                            subcarpeta_artista=v_sub.get(), descargas_simultaneas=simult,
                            max_resultados=maxr, abrir_al_terminar=v_abrir.get(),
                            email=v_email.get().strip() or DEFAULTS["email"],
                            ia_exe=v_exe.get().strip(), ia_modelo=v_modelo.get(),
                            ia_guardar_original=v_orig.get(), ia_gpu=gpu, ia_tile=tile)
            self.cfg.guardar()
            self.cliente.set_email(self.cfg["email"])
            self.v_dir.set(acortar(self.cfg["directorio"]))
            win.destroy()

        pie = ttk.Frame(cont)
        pie.pack(fill="x", pady=(14, 0))
        ttk.Button(pie, text="Guardar", style="Accent.TButton", command=guardar).pack(side="right")
        ttk.Button(pie, text="Cancelar", command=win.destroy).pack(side="right", padx=(0, 8))

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()

    # ................................................................... búsqueda
    def buscar(self, anexar: bool = False):
        if anexar:
            artista, album, tipo = self._ultima_busqueda
        else:
            artista, album = self.v_artista.get().strip(), self.v_album.get().strip()
            tipo = TIPOS_BUSQUEDA.get(self.v_tipo.get())
            if not artista and not album:
                messagebox.showwarning("Faltan datos", "Escribí al menos un artista o un álbum.")
                return
            self._ultima_busqueda = (artista, album, tipo)
            self._tok_busqueda += 1
            self.offset = 0
        tok = self._tok_busqueda
        offset, limite = self.offset, self.cfg["max_resultados"]

        self.btn_buscar.config(state="disabled")
        self.btn_mas.config(state="disabled")
        self.v_estado.set("Buscando en MusicBrainz")

        def trabajo():
            try:
                total, lista = self.cliente.buscar(artista, album, tipo, limite, offset)
                self.ui(self._resultados, tok, total, lista, anexar)
            except Exception as e:
                self.ui(self._error_busqueda, tok, e)
        self.hilo(trabajo)

    def _error_busqueda(self, tok, e):
        if tok != self._tok_busqueda:
            return
        self.btn_buscar.config(state="normal")
        self.v_estado.set(f"Error: {mensaje_error(e)}")
        messagebox.showerror("No se pudo buscar", mensaje_error(e))

    def _resultados(self, tok, total, lista, anexar):
        if tok != self._tok_busqueda:
            return
        self.btn_buscar.config(state="normal")
        if not anexar:
            self.tree.delete(*self.tree.get_children())
            self.albums.clear()
            self.thumbs.clear()
            self._reset_preview()
            self.al_seleccionar()

        self.offset += len(lista)
        self.total_mb = total
        for rg in lista:
            a = Album.desde_mb(rg)
            if a.mbid in self.albums:
                continue
            self.albums[a.mbid] = a
            self.tree.insert("", "end", iid=a.mbid, image=self.ph_thumb,
                             values=(a.artista, a.titulo, a.tipo, a.anio, "Cargando"))
            self.pool_min.submit(self._cargar_min, a.mbid, tok)

        n = len(self.albums)
        if n == 0:
            self.v_contador.set("Sin resultados. Probá con otro nombre o sin el tipo.")
            self.v_estado.set("No se encontraron álbumes.")
        else:
            self.v_contador.set(f"{n} de {total} resultados")
            self.v_estado.set("Elegí uno o varios álbumes (Ctrl/Shift+clic) y descargalos.")
            if not anexar:
                primero = self.tree.get_children()[0]
                self.tree.selection_set(primero)
                self.tree.focus(primero)
        self.btn_mas.config(state="normal" if self.offset < total else "disabled")

    def _cargar_min(self, mbid, tok):
        if tok != self._tok_busqueda:
            return
        try:
            datos = self.cliente.miniatura(mbid)
            pil = None
            if datos:
                pil = ImageOps.fit(Image.open(io.BytesIO(datos)).convert("RGB"), (self.thumb, self.thumb))
        except Exception:
            pil = False
        self.ui(self._min_lista, mbid, tok, pil)

    def _min_lista(self, mbid, tok, pil):
        if tok != self._tok_busqueda or not self.tree.exists(mbid):
            return
        if pil is None:
            self.tree.set(mbid, "estado", "Sin portada")
            self.tree.item(mbid, tags=("sin",))
        elif pil is False:
            self.tree.set(mbid, "estado", "Error")
        else:
            foto = ImageTk.PhotoImage(pil)
            self.thumbs[mbid] = foto
            self.tree.item(mbid, image=foto)
            self.tree.set(mbid, "estado", "Disponible")

    def seleccionar_todo(self):
        self.tree.selection_set(self.tree.get_children())

    # ---------------------------------------------------------- menú contextual
    def _menu_contextual(self, event):
        fila = self.tree.identify_row(event.y)
        if not fila:
            return
        if fila not in self.tree.selection():
            self.tree.selection_set(fila)
        self.tree.focus(fila)
        self.menu_ctx.tk_popup(event.x_root, event.y_root)
        return "break"

    def _album_foco(self) -> Album | None:
        iid = self.tree.focus() or (self.tree.selection() or [None])[-1]
        return self.albums.get(iid) if iid else None

    def abrir_musicbrainz(self):
        a = self._album_prev or self._album_foco()
        if a:
            webbrowser.open(MB_WEB.format(mbid=a.mbid))

    def copiar_url(self):
        a = self._album_foco()
        if not a:
            return

        def trabajo():
            try:
                imgs = self.cliente.listado(a.mbid)
                self.ui(self._copiar, imgs[0]["image"] if imgs else None)
            except Exception as e:
                self.ui(self.v_estado.set, f"Error: {mensaje_error(e)}")
        self.hilo(trabajo)

    def _copiar(self, url):
        if not url:
            self.v_estado.set("Este álbum no tiene portada.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.v_estado.set("URL de la imagen copiada al portapapeles.")

    # ------------------------------------------------------------- vista previa
    def _reset_preview(self):
        self._iid_prev = None
        self._album_prev = None
        self._imgs_prev = []
        self._tok_prev += 1
        self._foto_prev = None
        self.lbl_prev.config(image="", text="Elegí un resultado\npara ver la portada")
        self.v_titulo.set("")
        self.v_meta.set("")
        self.v_impresion.set("")
        self.v_nav.set("")
        for b in (self.btn_ant, self.btn_sig, self.btn_guardar_como):
            b.config(state="disabled")

    def al_seleccionar(self, _evento=None):
        sel = self.tree.selection()
        n = len(sel)
        self.btn_desc.config(text=f"Descargar selección ({n})" if n else "Descargar selección",
                             state="normal" if n else "disabled")
        self.btn_comparar.config(state="normal" if 2 <= n <= 6 else "disabled")
        if not sel:
            return
        foco = self.tree.focus()
        iid = foco if foco in sel else sel[-1]
        if iid == self._iid_prev:
            return
        self._iid_prev = iid
        self._mostrar_album(self.albums[iid])

    def comparar_seleccion(self):
        seleccion = self.tree.selection()
        if not 2 <= len(seleccion) <= 6:
            return
        albums = [self.albums[iid] for iid in seleccion]
        self.v_estado.set(f"Comparando {len(albums)} releases")

        def trabajo():
            comparacion = []
            try:
                for album in albums:
                    imagenes = self.cliente.listado(album.mbid) or []
                    imagen = mejor_imagen(imagenes, "front") or (imagenes[0] if imagenes else None)
                    if imagen is None:
                        comparacion.append((album, None, None))
                        continue
                    datos = self.cliente.bytes_de(url_preview(imagen))
                    with Image.open(io.BytesIO(datos)) as portada:
                        vista = portada.convert("RGB")
                        vista.thumbnail((180, 180), Image.Resampling.LANCZOS)
                        vista.load()
                    comparacion.append((album, imagen, vista))
                self.ui(self._mostrar_comparacion, comparacion)
            except Exception as e:
                self.ui(self.v_estado.set, f"Error al comparar: {mensaje_error(e)}")

        self.hilo(trabajo)

    def _mostrar_comparacion(self, comparacion):
        ventana = tk.Toplevel(self.root)
        ventana.title("Comparar releases")
        ventana.transient(self.root)
        ventana.configure(bg=self.p["bg"])
        ventana.geometry(f"{min(1180, max(620, 230 * len(comparacion)))}x430")

        panel = ttk.Frame(ventana, padding=16)
        panel.pack(fill="both", expand=True)
        fotos = []
        for album, imagen, vista in comparacion:
            tarjeta = ttk.Frame(panel, style="Card.TFrame", padding=10)
            tarjeta.pack(side="left", fill="both", expand=True, padx=5)
            if vista is None:
                ttk.Label(tarjeta, text="Sin portada disponible", anchor="center").pack(
                    fill="x", pady=(20, 30))
            else:
                foto = ImageTk.PhotoImage(vista)
                fotos.append(foto)
                ttk.Label(tarjeta, image=foto).pack(pady=(0, 8))
            ttk.Label(tarjeta, text=album.titulo, style="Title.TLabel", wraplength=190,
                      justify="center").pack(fill="x")
            if imagen is None:
                meta = "Sin imagen en Cover Art Archive"
            else:
                ancho, alto = imagen.get("width"), imagen.get("height")
                resolucion = f"{ancho}x{alto}" if ancho and alto else "Resolución desconocida"
                meta = f"{album.anio or 'Año desconocido'} · {album.tipo or 'Tipo desconocido'}\n{resolucion}"
            ttk.Label(tarjeta, text=meta, style="CardMuted.TLabel", justify="center").pack(
                fill="x", pady=(4, 8))
            if imagen is not None:
                iid = next((key for key, value in self.albums.items() if value is album), None)
                ttk.Button(tarjeta, text="Elegir este", command=lambda key=iid: self._elegir_comparado(
                    ventana, key)).pack()
        ventana._fotos = fotos
        self.v_estado.set("Comparación lista.")

    def _elegir_comparado(self, ventana, iid):
        if iid is not None and self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self.al_seleccionar()
        ventana.destroy()

    def _mostrar_album(self, a: Album):
        self._album_prev = a
        self._imgs_prev = []
        self._tok_prev += 1
        tok = self._tok_prev
        self.v_titulo.set(a.titulo)
        self.v_meta.set(" · ".join(x for x in (a.artista, a.anio, a.tipo) if x))
        self.v_nav.set("")
        for b in (self.btn_ant, self.btn_sig, self.btn_guardar_como):
            b.config(state="disabled")
        self.lbl_prev.config(image="", text="Cargando portada")
        self._foto_prev = None

        def trabajo():
            try:
                imgs = self.cliente.listado(a.mbid)
                self.ui(self._imagenes_listas, tok, imgs)
            except Exception as e:
                self.ui(self._error_preview, tok, e)
        self.hilo(trabajo)

    def _imagenes_listas(self, tok, imgs):
        if tok != self._tok_prev:
            return
        if not imgs:
            self.lbl_prev.config(image="", text="Este álbum no tiene\nportada disponible.")
            return
        self._imgs_prev = imgs
        self._idx_prev = 0
        self._mostrar_imagen()

    def _navegar(self, delta):
        if self._imgs_prev:
            self._idx_prev = (self._idx_prev + delta) % len(self._imgs_prev)
            self._mostrar_imagen()

    def _mostrar_imagen(self):
        img = self._imgs_prev[self._idx_prev]
        n = len(self._imgs_prev)
        self.v_nav.set(f"{etiqueta_imagen(img)}   ·   {self._idx_prev + 1} de {n}")
        ancho, alto = img.get("width"), img.get("height")
        if ancho and alto:
            dpi = round(min(ancho, alto) / (29.7 / 2.54))
            calidad = "apta para 300 DPI" if min(ancho, alto) >= 3508 else "inferior a 300 DPI"
            forma = "cuadrada" if ancho == alto else "no cuadrada"
            self.v_impresion.set(f"Original: {ancho}x{alto} - {dpi} DPI - {forma} - {calidad}")
        else:
            self.v_impresion.set("Resolución original no informada por Cover Art Archive")
        multiples = "normal" if n > 1 else "disabled"
        self.btn_ant.config(state=multiples)
        self.btn_sig.config(state=multiples)
        self.btn_guardar_como.config(state="normal")

        self._tok_prev += 1
        tok = self._tok_prev
        url = url_preview(img)
        if url in self._cache_prev:
            self._poner_preview(tok, self._cache_prev[url])
            return
        self.lbl_prev.config(image="", text="Cargando portada")

        def trabajo():
            try:
                datos = self.cliente.bytes_de(url)
                pil = Image.open(io.BytesIO(datos)).convert("RGB")
                pil.thumbnail((self.tam_preview, self.tam_preview), Image.LANCZOS)
                if len(self._cache_prev) > 40:
                    self._cache_prev.clear()
                self._cache_prev[url] = pil
                self.ui(self._poner_preview, tok, pil)
            except Exception as e:
                self.ui(self._error_preview, tok, e)
        self.hilo(trabajo)

    def _poner_preview(self, tok, pil):
        if tok != self._tok_prev:
            return
        self._foto_prev = ImageTk.PhotoImage(pil)
        self.lbl_prev.config(image=self._foto_prev, text="")

    def _error_preview(self, tok, e):
        if tok != self._tok_prev:
            return
        self.lbl_prev.config(image="", text="No se pudo cargar\nla imagen.")
        self.v_estado.set(f"Error: {mensaje_error(e)}")

    def guardar_como(self):
        if not self._imgs_prev or not self._album_prev:
            return
        img, alb = self._imgs_prev[self._idx_prev], self._album_prev
        snap = self.snapshot()
        if not self._ia_ok(snap):
            return
        url = img["image"]
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        if snap["ia_activa"]:
            ext = ".png"
        sufijo = "" if img.get("front") else f" - {etiqueta_imagen(img)}"
        ruta = filedialog.asksaveasfilename(
            title="Guardar imagen", initialdir=self.cfg["directorio"] if Path(self.cfg["directorio"]).exists() else str(Path.home()),
            initialfile=nombre_base(self.cfg["plantilla"], alb) + sufijo + ext,
            defaultextension=ext, filetypes=[("Imagen", f"*{ext}"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        self.v_estado.set("Descargando imagen original")

        def trabajo():
            try:
                datos = self.cliente.bytes_de(url)
                if snap["ia_activa"]:
                    ampliada = ampliar_ia(
                        datos, snap, self.cancelar,
                        lambda mensaje: self.ui(self.v_estado.set, mensaje),
                    )
                    if ampliada is not None:
                        datos = ampliada
                    extension = Path(ruta).suffix.lower()
                    if extension in (".jpg", ".jpeg"):
                        datos, _ = convertir(datos, "JPG")
                    elif extension == ".png":
                        datos, _ = convertir(datos, "PNG")
                    if snap["modo_impresion"]:
                        formato_salida = "JPG" if extension in (".jpg", ".jpeg") else "PNG"
                        datos, _ = preparar_para_impresion(datos, formato_salida)
                escribir_atomico(Path(ruta), datos)
                self.ui(self.v_estado.set, f"Guardada en: {ruta}")
            except Exception as e:
                self.ui(self.v_estado.set, f"Error: {mensaje_error(e)}")
        self.hilo(trabajo)

    # ........................................................... cola de descargas
    def snapshot(self) -> dict:
        snap = {k: self.cfg[k] for k in (
            "directorio", "plantilla", "subcarpeta_artista", "que_descargar", "tamano", "formato",
            "si_existe", "ia_activa", "ia_objetivo", "ia_modelo", "ia_gpu", "ia_tile",
            "ia_guardar_original", "modo_impresion")}
        exe = buscar_exe(self.cfg["ia_exe"]) if self.cfg["ia_activa"] else None
        snap["ia_exe"] = str(exe) if exe else ""
        return snap

    def _ia_ok(self, snap: dict) -> bool:
        """Evita empezar una descarga con IA activada pero sin Real-ESRGAN disponible."""
        if not snap["ia_activa"]:
            return True
        if not snap["ia_exe"]:
            mensaje = "La ampliación con IA está activada pero no encuentro Real-ESRGAN."
        else:
            try:
                validar_instalacion_ia(Path(snap["ia_exe"]), snap["ia_modelo"])
            except (FileNotFoundError, OSError) as e:
                mensaje = str(e)
            else:
                return True
        if messagebox.askyesno("Real-ESRGAN no disponible", mensaje + "\n\n¿Querés abrir los ajustes para configurarlo?"):
                self.abrir_ajustes(1)
        return False

    def _al_activar_ia(self):
        if self.v_ia.get():
            exe = buscar_exe(self.cfg["ia_exe"])
            try:
                if exe is None:
                    raise FileNotFoundError("No se encontró el ejecutable de Real-ESRGAN.")
                validar_instalacion_ia(exe, self.cfg["ia_modelo"])
            except (FileNotFoundError, OSError) as e:
                self.v_ia.set(False)
                if messagebox.askyesno("Real-ESRGAN no disponible", f"{e}\n\n¿Querés abrir los ajustes para configurarlo?"):
                    self.abrir_ajustes(1)
                return
        self.cfg["ia_activa"] = self.v_ia.get()
        self.cfg.guardar()

    def _get_pool(self) -> ThreadPoolExecutor:
        n = int(self.cfg["descargas_simultaneas"])
        if self.pool is None or self._pool_n != n:
            if self.pool:
                self.pool.shutdown(wait=False)
            self.pool = ThreadPoolExecutor(max_workers=n)
            self._pool_n = n
        return self.pool

    def _reservar(self, n: int):
        if self.pend <= 0:
            self.total = self.hechos = 0
            self.contadores = Counter()
            self.cancelar.clear()
        self.total += n
        self.pend += n
        self.btn_cancel.config(state="normal")
        self._progreso()

    def _submit(self, album: Album, snap: dict):
        self._get_pool().submit(self._job, album, snap)

    def descargar_seleccion(self):
        sel = self.tree.selection()
        if not sel:
            return
        albums = [self.albums[i] for i in sel]
        snap = self.snapshot()
        if not self._ia_ok(snap):
            return
        try:
            Path(snap["directorio"]).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Carpeta no válida", str(e))
            return
        self._reservar(len(albums))
        for a in albums:
            self._submit(a, snap)

    def cancelar_descargas(self):
        self.cancelar.set()
        self.v_estado.set("Cancelando")

    def _job(self, album: Album, snap: dict):
        if self.cancelar.is_set():
            self.ui(self._job_terminado, album, "cancelado", "", None)
            return
        etiqueta = f"{album.artista} - {album.titulo}"
        self.ui(self.v_estado.set, f"Descargando: {etiqueta}")
        try:
            res = procesar_album(self.cliente, album, snap, self.cancelar,
                                 lambda m: self.ui(self.v_estado.set, f"{etiqueta}: {m}"))
            nuevos = [r for r in res if not r["omitido"]]
            if not nuevos:
                self.ui(self._job_terminado, album, "omitido", "El archivo ya existía", res[0]["ruta"])
            else:
                principal = next((r for r in nuevos if r["ia"]), nuevos[0])
                w, h = principal["dim"]
                peso = tamano_legible(sum(r["bytes"] for r in nuevos))
                extra = f"{len(nuevos)} archivos · " if len(nuevos) > 1 else ""
                marca = " · ampliada con IA" if principal["ia"] else ""
                modo = " · lista para imprimir" if snap["modo_impresion"] else ""
                cuadrada = "" if principal["cuadrada"] else " · no cuadrada"
                calidad = "" if principal["calidad"] == "apta" else " · inferior a 3508 px"
                detalle = (f"{extra}{w}x{h} - {principal['dpi']} DPI - {peso}"
                           f"{marca}{modo}{cuadrada}{calidad}")
                self.ui(self._job_terminado, album, "ok", detalle,
                        principal["ruta"])
        except Cancelado:
            self.ui(self._job_terminado, album, "cancelado", "", None)
        except SinPortada:
            self.ui(self._job_terminado, album, "sin_portada", "No hay imágenes en Cover Art Archive", None)
        except Exception as e:
            self.ui(self._job_terminado, album, "error", mensaje_error(e), None)

    def _job_terminado(self, album: Album, estado: str, detalle: str, ruta: Path | None):
        self.hechos += 1
        self.pend -= 1
        self.contadores[estado] += 1
        self._progreso()
        self._registrar(album, estado, detalle, ruta)
        if album.origen and self.lote_tree.exists(album.origen):
            self.lote_tree.set(album.origen, "estado", ESTADOS[estado])
            if estado not in ("no_encontrado", "cancelado"):
                self.lote_tree.set(album.origen, "resultado", f"{album.artista} - {album.titulo}")
        if self.pend <= 0:
            self._finalizar()

    def _progreso(self):
        self.barra.config(maximum=max(self.total, 1), value=self.hechos)
        self.v_prog.set(f"{self.hechos}/{self.total}")

    def _finalizar(self):
        c = self.contadores
        etiquetas = (("ok", "descargadas"), ("omitido", "omitidas"), ("sin_portada", "sin portada"),
                     ("no_encontrado", "no encontradas"), ("error", "con error"), ("cancelado", "canceladas"))
        partes = [f"{c[k]} {t}" for k, t in etiquetas if c[k]]
        prefijo = "Cancelado" if c["cancelado"] else "Listo"
        self.v_estado.set(f"{prefijo} · " + ", ".join(partes) if partes else prefijo)
        self.btn_cancel.config(state="disabled")
        self.cancelar.clear()
        if c["ok"]:
            self.root.bell()
            if self.cfg["abrir_al_terminar"]:
                self.abrir_directorio()

    # ................................................................... lote
    def abrir_archivo_lote(self):
        ruta = filedialog.askopenfilename(title="Lista de álbumes",
                                          filetypes=[("Texto", "*.txt *.csv"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            texto = Path(ruta).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("No se pudo leer el archivo", str(e))
            return
        self.txt_lote.delete("1.0", "end")
        self.txt_lote.insert("1.0", texto)

    def procesar_lote(self):
        self.lote_tree.delete(*self.lote_tree.get_children())
        validas: list[tuple[str, str, str]] = []
        for iid, original, artista, titulo in entradas_lote(self.txt_lote.get("1.0", "end")):
            if artista and titulo:
                validas.append((iid, artista, titulo))
                self.lote_tree.insert("", "end", iid=iid, values=(original, "", "En cola"))
            else:
                self.lote_tree.insert("", "end", iid=iid, values=(original, "", "Formato inválido"))
        if not validas:
            messagebox.showinfo("Lote", "No hay líneas válidas. Usá el formato  Artista - Álbum.")
            return

        snap = self.snapshot()
        if not self._ia_ok(snap):
            return
        try:
            Path(snap["directorio"]).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Carpeta no válida", str(e))
            return
        self._lote_validas = validas
        self._lote_snap = snap
        self._reservar(len(validas))
        self.hilo(lambda: self._resolver_lote(validas, snap))

    def reintentar_lote(self):
        if not hasattr(self, "_lote_validas"):
            return
        estados = {self.lote_tree.set(iid, "estado") for iid in self.lote_tree.get_children()}
        if not any(estado.startswith(("Error", "Sin portada", "No encontrado")) for estado in estados):
            messagebox.showinfo("Lote", "No hay filas con error para reintentar.")
            return
        fallidas = [linea for linea in self._lote_validas
                    if self.lote_tree.exists(linea[0])
                    and self.lote_tree.set(linea[0], "estado").startswith(("Error", "Sin portada", "No encontrado"))]
        if not fallidas:
            messagebox.showinfo("Lote", "No hay filas válidas con error para reintentar.")
            return
        snap = self._lote_snap
        self._reservar(len(fallidas))
        for iid, _artista, _titulo in fallidas:
            self._lote_estado(iid, "En cola")
        self.hilo(lambda: self._resolver_lote(fallidas, snap))

    def _resolver_lote(self, lineas, snap):
        for iid, artista, titulo in lineas:
            stub = Album("", artista, titulo, origen=iid)
            if self.cancelar.is_set():
                self.ui(self._job_terminado, stub, "cancelado", "", None)
                continue
            try:
                self.ui(self._lote_estado, iid, "Buscando")
                _, resultados = self.cliente.buscar(artista, titulo, None, 6, 0)
                elegido = None
                for rg in resultados:
                    a = Album.desde_mb(rg)
                    if self.cliente.listado(a.mbid):
                        a.origen = iid
                        elegido = a
                        break
                if elegido is None:
                    estado = "sin_portada" if resultados else "no_encontrado"
                    detalle = "Ninguna coincidencia tiene portada" if resultados else "Sin coincidencias"
                    self.ui(self._job_terminado, stub, estado, detalle, None)
                else:
                    self.ui(self._lote_estado, iid, "Descargando")
                    self.ui(self._submit, elegido, snap)
            except Exception as e:
                self.ui(self._job_terminado, stub, "error", mensaje_error(e), None)

    def _lote_estado(self, iid, texto):
        if self.lote_tree.exists(iid):
            self.lote_tree.set(iid, "estado", texto)

    # ............................................................. actividad
    def _leer_historial(self) -> list[dict]:
        try:
            datos = json.loads(self.archivo_historial.read_text(encoding="utf-8"))
            return datos if isinstance(datos, list) else []
        except (OSError, ValueError):
            return []

    def _guardar_historial(self):
        try:
            self.archivo_historial.write_text(
                json.dumps(self.historial[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _cargar_historial_en_tabla(self):
        for e in self.historial[-300:]:
            self.act_tree.insert("", 0, values=(e["hora"], e["artista"], e["album"],
                                                e["estado"], e["detalle"], e.get("resolucion", ""),
                                                e.get("dpi", ""), e["ruta"]))

    def _registrar(self, album: Album, estado: str, detalle: str, ruta: Path | None):
        informe = inspeccionar_archivo(ruta) if ruta else {}
        duplicado = ruta_duplicada(self.historial, informe.get("huella", ""), ruta) if ruta else ""
        if duplicado:
            detalle += f" · duplicada de {acortar(duplicado, 45)}"
        e = {"hora": datetime.now().strftime("%d/%m/%Y %H:%M"), "artista": album.artista,
             "album": album.titulo, "estado": ESTADOS[estado], "detalle": detalle,
             "ruta": str(ruta) if ruta else "", "resolucion": informe.get("dim", ""),
             "dpi": informe.get("dpi", ""), "calidad": informe.get("calidad", ""),
             "cuadrada": informe.get("cuadrada", ""), "huella": informe.get("huella", ""),
             "duplicada_de": duplicado}
        self.historial.append(e)
        self.historial = self.historial[-300:]
        self.act_tree.insert("", 0, values=(e["hora"], e["artista"], e["album"],
                            e["estado"], e["detalle"], e["resolucion"],
                            e["dpi"], e["ruta"]))
        hijos = self.act_tree.get_children()
        if len(hijos) > 300:
            self.act_tree.delete(hijos[-1])
        self._guardar_historial()

    def _abrir_actividad(self, carpeta: bool = False):
        sel = self.act_tree.selection()
        if not sel:
            return
        ruta = self.act_tree.set(sel[0], "ruta")
        if not ruta or not Path(ruta).exists():
            messagebox.showinfo("Archivo no disponible", "Ese archivo ya no existe o nunca se guardó.")
            return
        (mostrar_en_carpeta if carpeta else abrir_ruta)(Path(ruta))

    def limpiar_historial(self):
        if messagebox.askyesno("Limpiar historial", "¿Borrar todo el historial de actividad?"):
            self.act_tree.delete(*self.act_tree.get_children())
            self.historial.clear()
            self._guardar_historial()


# .............................................................................
def main():
    if sys.platform.startswith("win"):
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()


