/* =========================================================================
   SIG-LOG — pantalla genérica de módulo

   Una sola pantalla sirve a los diez módulos. Lo que cambia entre ellos
   —columnas, filtros, campos y acciones— llega descrito desde
   `backend/vistas/catalogo.py` en el <script type="application/json">.

   Escribir diez pantallas casi iguales habría multiplicado por diez
   cualquier corrección de la tabla o del formulario.

   Nada de aquí valida reglas de negocio: eso lo hace el servicio, y su
   respuesta 409 llega con el mensaje ya redactado. Lo único que hace esta
   página es enseñarlo.
   ========================================================================= */

(function () {
  "use strict";

  const M = JSON.parse(document.getElementById("datos-modulo").textContent);
  const PUEDE = window.SIGLOG.puedeEscribir;

  const estado = {pagina: 1, tamano: 25, total: 0, filas: [], filtros: {}};
  // Dos cachés distintas sobre los mismos recursos: los desplegables del
  // formulario necesitan una lista ordenada, y las columnas un índice por
  // identificador. Compartir la clave haría que una pisara a la otra.
  const cacheOpciones = {};          // recurso → [{id, texto}]
  const cacheIndice = {};            // recurso → {id: {etiqueta, detalle}}

  const cuerpo = document.getElementById("cuerpo");
  const conteo = document.getElementById("conteo");
  const modalForm = new bootstrap.Modal(document.getElementById("modal-formulario"));
  const modalDetalle = new bootstrap.Modal(document.getElementById("modal-detalle"));

  // ======================================================================
  // LISTADO
  // ======================================================================
  function parametros() {
    const p = new URLSearchParams();
    p.set("pagina", estado.pagina);
    p.set("tamano", estado.tamano);
    Object.keys(estado.filtros).forEach(function (clave) {
      const valor = estado.filtros[clave];
      if (valor !== "" && valor !== null && valor !== undefined && valor !== false) {
        p.set(clave, valor);
      }
    });
    return p.toString();
  }

  /**
   * Precarga los catálogos que las columnas de tipo "referencia" necesitan.
   *
   * Un identificador interno no le dice nada a nadie: la tabla tiene que
   * enseñar «VEH-001 · Hino Serie 300». Se piden una vez y se reutilizan
   * para todas las filas.
   */
  async function precargarReferencias() {
    const pendientes = M.columnas.filter(function (c) {
      return c.formato === "referencia" && c.recurso && !cacheIndice[c.recurso];
    });
    for (const columna of pendientes) {
      try {
        const r = await SL.api(columna.recurso + "?pagina=1&tamano=200");
        const indice = {};
        (r.datos || []).forEach(function (d) {
          indice[d.id] = {
            etiqueta: d[columna.etiqueta_opcion] || d.id,
            detalle: [d.marca, d.modelo].filter(Boolean).join(" ") ||
                     d.nombre || d.nombre_completo || "",
            extra: columna.detalle_opcion ? d[columna.detalle_opcion] : ""
          };
        });
        cacheIndice[columna.recurso] = indice;
      } catch (error) {
        cacheIndice[columna.recurso] = {};   // se degrada al identificador
      }
    }
  }

  function celdaReferencia(valor, columna) {
    if (SL.esVacio(valor)) return "—";
    const indice = cacheIndice[columna.recurso] || {};
    const ref = indice[valor];
    if (!ref) {
      // El catálogo no lo tiene (dado de baja, o fuera de las 200 primeras).
      // Se enseña el identificador, pero atenuado y avisando de qué es.
      return '<small class="text-body-tertiary" title="Identificador ' +
             'interno; el registro no está en el catálogo activo">' +
             SL.escapar(String(valor).slice(-6)) + "</small>";
    }
    let html = "<strong>" + SL.escapar(ref.etiqueta) + "</strong>";
    if (ref.detalle) {
      html += '<br><small class="text-body-secondary">' +
              SL.escapar(ref.detalle) +
              (ref.extra ? " · " + SL.escapar(ref.extra) : "") + "</small>";
    }
    return html;
  }

  async function cargar() {
    cuerpo.innerHTML = '<tr><td colspan="' + (M.columnas.length + 1) +
                       '" class="sl-cargando">Cargando…</td></tr>';
    try {
      await precargarReferencias();
      const r = await SL.api(M.recurso + "?" + parametros());
      estado.filas = r.datos || [];
      estado.total = r.total || 0;
      pintar();
    } catch (error) {
      cuerpo.innerHTML = '<tr><td colspan="' + (M.columnas.length + 1) +
        '" class="sl-cargando text-danger"></td></tr>';
      cuerpo.querySelector("td").textContent = error.message;
      SL.avisarError(error);
    }
  }

  function pintar() {
    if (!estado.filas.length) {
      cuerpo.innerHTML = '<tr><td colspan="' + (M.columnas.length + 1) +
        '" class="sl-cargando">Ningún registro coincide con el filtro.</td></tr>';
      conteo.textContent = "0 registros";
      actualizarPaginacion();
      return;
    }

    cuerpo.innerHTML = "";
    estado.filas.forEach(function (fila) {
      const tr = document.createElement("tr");

      M.columnas.forEach(function (columna) {
        const td = document.createElement("td");
        const valor = fila[columna.campo];
        // `formatear` y `celdaReferencia` escapan lo que insertan
        td.innerHTML = columna.formato === "referencia"
          ? celdaReferencia(valor, columna)
          : SL.formatear(valor, columna.formato);
        if (["numero", "entero", "dinero", "minutos"].indexOf(columna.formato) >= 0) {
          td.className = "sl-num";
        }
        tr.appendChild(td);
      });

      tr.appendChild(celdaAcciones(fila));
      cuerpo.appendChild(tr);
    });

    const desde = (estado.pagina - 1) * estado.tamano + 1;
    const hasta = desde + estado.filas.length - 1;
    conteo.textContent = desde + "–" + hasta + " de " +
                         SL.entero(estado.total) + " registros";
    actualizarPaginacion();
  }

  function celdaAcciones(fila) {
    const td = document.createElement("td");
    td.className = "sl-acciones";

    td.appendChild(boton("Ver", "bi-eye", "outline-secondary", function () {
      verDetalle(fila);
    }));

    // Las acciones llegan ya recortadas por el servidor: si están aquí,
    // este rol puede ejecutarlas, aunque no pueda dar de alta ni editar.
    (M.acciones || []).forEach(function (accion) {
      if (!accion.por_fila) return;
      td.appendChild(boton(accion.etiqueta, accion.icono || "bi-lightning",
        accion.estilo, function () { ejecutar(accion, fila); }));
    });

    if (!PUEDE) return td;

    if (M.campos_edicion && M.campos_edicion.length) {
      td.appendChild(boton("Editar", "bi-pencil", "outline-primary", function () {
        abrirFormulario({
          titulo: "Editar",
          campos: M.campos_edicion,
          descripcion: "",
          valores: fila,
          enviar: function (datos) {
            return SL.api(M.recurso + "/" + fila.id,
                          {method: "PUT", cuerpo: datos});
          }
        });
      }));
    }

    if (M.permite_baja) {
      td.appendChild(boton("Baja", "bi-trash", "outline-danger", function () {
        // Baja lógica: el documento no se borra. Si se borrara, el
        // histórico que alimenta al ETL perdería filas hacia atrás.
        if (!confirm("¿Dar de baja este registro? Queda inactivo, no se borra."))
          return;
        SL.api(M.recurso + "/" + fila.id, {method: "DELETE"})
          .then(function (r) { SL.avisar(r.mensaje, "success"); cargar(); })
          .catch(SL.avisarError);
      }));
    }
    return td;
  }

  function boton(titulo, icono, estilo, alPulsar) {
    const b = document.createElement("button");
    b.className = "btn btn-" + (estilo || "outline-secondary");
    b.title = titulo;
    b.innerHTML = '<i class="bi ' + icono + '"></i>';
    b.addEventListener("click", alPulsar);
    return b;
  }

  function actualizarPaginacion() {
    document.getElementById("btn-anterior").disabled = estado.pagina <= 1;
    document.getElementById("btn-siguiente").disabled =
      estado.pagina * estado.tamano >= estado.total;
  }

  // ======================================================================
  // DETALLE
  // ======================================================================
  function verDetalle(fila) {
    document.getElementById("detalle-titulo").textContent =
      fila.folio_entrega || fila.folio_viaje || fila.folio_incidente ||
      fila.folio_carga || fila.folio_mantenimiento || fila.codigo_cliente ||
      fila.codigo_vehiculo || fila.codigo_operador || fila.codigo_ruta ||
      fila.usuario || "Detalle";

    // Los identificadores internos no encabezan el detalle: van al final,
    // plegados. Quien mira una ficha quiere los datos, no las claves
    // foráneas; el identificador solo hace falta para depurar o para
    // llamar al API a mano.
    const esIdentificador = function (clave) {
      return clave === "id" || /_id$/.test(clave);
    };
    const principales = Object.keys(fila).filter(function (k) {
      return !esIdentificador(k);
    });
    const identificadores = Object.keys(fila).filter(esIdentificador);

    const construir = function (claves) {
      const tabla = document.createElement("table");
      tabla.className = "sl-detalle-tabla";
      claves.forEach(function (clave) {
        const tr = document.createElement("tr");
        const th = document.createElement("th");
        th.textContent = clave.replace(/_/g, " ");
        const td = document.createElement("td");
        const valor = fila[clave];
        if (valor && typeof valor === "object") {
          const pre = document.createElement("pre");
          pre.textContent = JSON.stringify(valor, null, 2);
          td.appendChild(pre);
        } else {
          td.textContent = SL.esVacio(valor) ? "—" : String(valor);
        }
        tr.appendChild(th); tr.appendChild(td);
        tabla.appendChild(tr);
      });
      return tabla;
    };

    const contenedor = document.getElementById("detalle-cuerpo");
    contenedor.innerHTML = "";
    contenedor.appendChild(construir(principales));

    if (identificadores.length) {
      const plegado = document.createElement("details");
      plegado.className = "mt-3";
      const resumen = document.createElement("summary");
      resumen.className = "small text-body-secondary";
      resumen.textContent = "Identificadores internos";
      plegado.appendChild(resumen);
      plegado.appendChild(construir(identificadores));
      contenedor.appendChild(plegado);
    }
    modalDetalle.show();
  }

  // ======================================================================
  // FORMULARIOS
  // ======================================================================
  let envioActual = null;

  function abrirFormulario(config) {
    document.getElementById("modal-titulo").textContent = config.titulo;
    const desc = document.getElementById("modal-descripcion");
    desc.textContent = config.descripcion || "";
    desc.classList.toggle("d-none", !config.descripcion);
    ocultarError();

    const form = document.getElementById("modal-form");
    form.innerHTML = "";
    (config.campos || []).forEach(function (campo) {
      form.appendChild(construirCampo(campo, (config.valores || {})[campo.nombre]));
    });
    if (!config.campos || !config.campos.length) {
      form.innerHTML = '<p class="text-body-secondary small mb-0">' +
        "Esta acción no necesita datos adicionales.</p>";
    }

    envioActual = config.enviar;
    modalForm.show();
    cargarReferencias(form);
  }

  function construirCampo(campo, valor) {
    const caja = document.createElement("div");
    caja.className = "sl-campo";

    if (campo.tipo === "objeto") {
      const conjunto = document.createElement("fieldset");
      conjunto.className = "sl-subformulario";
      conjunto.dataset.objeto = campo.nombre;
      const leyenda = document.createElement("legend");
      leyenda.textContent = campo.etiqueta;
      conjunto.appendChild(leyenda);
      const rejilla = document.createElement("div");
      rejilla.className = "sl-rejilla-campos";
      campo.subcampos.forEach(function (sub) {
        rejilla.appendChild(construirCampo(sub, (valor || {})[sub.nombre]));
      });
      conjunto.appendChild(rejilla);
      return conjunto;
    }

    if (campo.tipo === "grupo") return construirGrupo(campo, valor);

    const etiqueta = document.createElement("label");
    etiqueta.className = "form-label";
    etiqueta.textContent = campo.etiqueta + (campo.requerido ? " *" : "");
    caja.appendChild(etiqueta);

    let control;
    if (campo.tipo === "select" || campo.tipo === "ref") {
      control = document.createElement("select");
      control.className = "form-select form-select-sm";
      if (campo.multiple) { control.multiple = true; control.size = 5; }
      if (campo.tipo === "ref") {
        control.dataset.recurso = campo.recurso;
        control.dataset.etiqueta = campo.etiqueta_opcion;
        control.innerHTML = '<option value="">Cargando…</option>';
      } else {
        if (!campo.multiple) control.appendChild(new Option("— elegir —", ""));
        campo.opciones.forEach(function (opcion) {
          control.appendChild(new Option(opcion.replace(/_/g, " "), opcion));
        });
      }
    } else if (campo.tipo === "textarea") {
      control = document.createElement("textarea");
      control.className = "form-control form-control-sm";
      control.rows = 2;
    } else if (campo.tipo === "checkbox") {
      caja.className = "sl-campo form-check";
      etiqueta.className = "form-check-label";
      control = document.createElement("input");
      control.type = "checkbox";
      control.className = "form-check-input";
      caja.innerHTML = "";
      caja.appendChild(control);
      caja.appendChild(etiqueta);
    } else {
      control = document.createElement("input");
      control.className = "form-control form-control-sm";
      control.type = ({date: "date", datetime: "datetime-local", time: "time",
                       number: "number", password: "password"})[campo.tipo] || "text";
      if (campo.tipo === "number") control.step = campo.paso || "any";
    }

    control.name = campo.nombre;
    control.dataset.tipo = campo.tipo;
    if (campo.requerido) control.required = true;

    if (valor !== undefined && valor !== null) {
      if (campo.tipo === "checkbox") control.checked = !!valor;
      else if (campo.tipo === "ref") {
        // Un desplegable de referencia todavía no tiene opciones: se
        // rellenan después, contra el API. Asignarle el valor ahora no
        // haría nada, así que se guarda y `cargarReferencias` lo restaura
        // cuando las opciones ya existen. Sin esto, editar un registro
        // perdería en silencio la ruta o el vehículo ya elegidos.
        control.dataset.valor = valor;
      }
      else if (campo.tipo === "date" && typeof valor === "string")
        control.value = valor.slice(0, 10);
      else if (campo.tipo === "datetime" && typeof valor === "string")
        control.value = valor.slice(0, 16);
      else if (campo.multiple && Array.isArray(valor)) {
        Array.from(control.options).forEach(function (o) {
          o.selected = valor.indexOf(o.value) >= 0;
        });
      } else control.value = valor;
    }

    if (campo.tipo !== "checkbox") caja.appendChild(control);
    if (campo.ayuda) {
      const ayuda = document.createElement("p");
      ayuda.className = "sl-ayuda";
      ayuda.textContent = campo.ayuda;
      caja.appendChild(ayuda);
    }
    return caja;
  }

  /** Lista repetible: direcciones de un cliente, paradas de una ruta. */
  function construirGrupo(campo, valor) {
    const conjunto = document.createElement("fieldset");
    conjunto.className = "sl-subformulario";
    conjunto.dataset.grupo = campo.nombre;

    const leyenda = document.createElement("legend");
    leyenda.textContent = campo.etiqueta;
    conjunto.appendChild(leyenda);

    if (campo.ayuda) {
      const ayuda = document.createElement("p");
      ayuda.className = "sl-ayuda mb-2";
      ayuda.textContent = campo.ayuda;
      conjunto.appendChild(ayuda);
    }

    const lista = document.createElement("div");
    conjunto.appendChild(lista);

    function agregar(datos) {
      const item = document.createElement("div");
      item.className = "sl-repetible";
      item.dataset.item = "1";

      const cabecera = document.createElement("div");
      cabecera.className = "sl-repetible-cabecera";
      const numero = document.createElement("span");
      cabecera.appendChild(numero);
      const quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "btn btn-sm btn-outline-danger";
      quitar.innerHTML = '<i class="bi bi-x-lg"></i>';
      quitar.addEventListener("click", function () { item.remove(); renumerar(); });
      cabecera.appendChild(quitar);
      item.appendChild(cabecera);

      const rejilla = document.createElement("div");
      rejilla.className = "sl-rejilla-campos";
      campo.subcampos.forEach(function (sub) {
        rejilla.appendChild(construirCampo(sub, (datos || {})[sub.nombre]));
      });
      item.appendChild(rejilla);
      lista.appendChild(item);
      renumerar();
      cargarReferencias(item);
    }

    function renumerar() {
      Array.from(lista.children).forEach(function (item, i) {
        item.querySelector(".sl-repetible-cabecera span").textContent =
          campo.etiqueta + " " + (i + 1);
      });
    }

    const anadir = document.createElement("button");
    anadir.type = "button";
    anadir.className = "btn btn-sm btn-outline-primary";
    anadir.innerHTML = '<i class="bi bi-plus-lg"></i> Añadir';
    anadir.addEventListener("click", function () { agregar(null); });
    conjunto.appendChild(anadir);

    if (Array.isArray(valor) && valor.length) valor.forEach(agregar);
    else agregar(null);
    return conjunto;
  }

  /**
   * Rellena los `select` que se alimentan de otro recurso.
   *
   * Se piden 200 registros y se cachea por recurso: son catálogos —rutas,
   * vehículos, operadores— y volver a pedirlos por cada parada de una ruta
   * sería una petición por fila.
   */
  async function cargarReferencias(raiz) {
    const selects = raiz.querySelectorAll("select[data-recurso]");
    for (const select of selects) {
      const recurso = select.dataset.recurso;
      const etiqueta = select.dataset.etiqueta;
      const valorPrevio = select.dataset.valor || "";
      try {
        if (!cacheOpciones[recurso]) {
          const r = await SL.api(recurso + "?pagina=1&tamano=200");
          cacheOpciones[recurso] = (r.datos || []).map(function (d) {
            return {
              id: d.id,
              texto: (d[etiqueta] || d.id) +
                     (d.nombre ? " — " + d.nombre :
                      d.nombre_completo ? " — " + d.nombre_completo :
                      d.placa ? " — " + d.placa : "")
            };
          });
        }
        const opciones = cacheOpciones[recurso];
        select.innerHTML = "";
        select.appendChild(new Option(
          select.hasAttribute("required") ? "— elegir —" : "— ninguno —", ""));
        opciones.forEach(function (o) {
          select.appendChild(new Option(o.texto, o.id));
        });
        if (valorPrevio) select.value = valorPrevio;
      } catch (error) {
        select.innerHTML = "";
        select.appendChild(new Option("No se pudo cargar " + recurso, ""));
      }
    }
  }

  /**
   * Recoge el formulario respetando la forma que espera el API.
   *
   * Los vacíos se omiten en vez de mandarse como "". No es lo mismo: una
   * cadena vacía es un valor que Pydantic rechaza, y omitir el campo deja
   * que se aplique su valor por omisión, que es lo que el usuario quiere
   * decir cuando deja algo en blanco.
   */
  function recoger(contenedor) {
    const datos = {};

    Array.from(contenedor.children).forEach(function (nodo) {
      if (nodo.dataset && nodo.dataset.grupo) {
        const items = nodo.querySelectorAll('[data-item="1"]');
        const lista = [];
        items.forEach(function (item) {
          const sub = recoger(item.querySelector(".sl-rejilla-campos"));
          if (Object.keys(sub).length) lista.push(sub);
        });
        if (lista.length) datos[nodo.dataset.grupo] = lista;
        return;
      }
      if (nodo.dataset && nodo.dataset.objeto) {
        const sub = recoger(nodo.querySelector(".sl-rejilla-campos"));
        if (Object.keys(sub).length) datos[nodo.dataset.objeto] = sub;
        return;
      }
      const control = nodo.querySelector ?
        nodo.querySelector("input, select, textarea") : null;
      if (!control || !control.name) return;

      const tipo = control.dataset.tipo;
      if (tipo === "checkbox") { datos[control.name] = control.checked; return; }

      if (control.multiple) {
        const elegidos = Array.from(control.selectedOptions).map(function (o) {
          return o.value;
        }).filter(Boolean);
        if (elegidos.length) datos[control.name] = elegidos;
        return;
      }

      const valor = (control.value || "").trim();
      if (valor === "") return;
      if (tipo === "number") datos[control.name] = Number(valor);
      else if (tipo === "datetime") datos[control.name] = valor;
      else datos[control.name] = valor;
    });

    return datos;
  }

  function mostrarError(mensaje) {
    const caja = document.getElementById("modal-error");
    caja.textContent = mensaje;
    caja.style.whiteSpace = "pre-line";
    caja.classList.remove("d-none");
  }
  function ocultarError() {
    document.getElementById("modal-error").classList.add("d-none");
  }

  document.getElementById("modal-enviar").addEventListener("click", async function () {
    const form = document.getElementById("modal-form");
    if (!form.checkValidity()) { form.reportValidity(); return; }
    ocultarError();

    const boton = this;
    boton.disabled = true;
    try {
      const respuesta = await envioActual(recoger(form));
      modalForm.hide();
      SL.avisar(respuesta.mensaje || "Operación realizada.", "success");
      cargar();
      cargarResumen();
    } catch (error) {
      // El 409 trae el texto de la regla que se violó, escrito por el
      // servicio. Se muestra dentro del formulario, junto a los datos que
      // hay que corregir, no como aviso flotante.
      mostrarError(error instanceof SL.ErrorApi ? error.completo() : String(error));
    } finally {
      boton.disabled = false;
    }
  });

  // ======================================================================
  // ACCIONES
  // ======================================================================
  function rutaAccion(accion, fila) {
    // Una acción puede apuntar a otro recurso ("/../ml/predecir-retraso"):
    // es el caso de predecir el retraso de una entrega, que vive en /ml.
    if (accion.ruta.indexOf("/../") === 0) return accion.ruta.slice(3);
    return M.recurso + accion.ruta.replace("{id}", fila ? fila.id : "");
  }

  function ejecutar(accion, fila) {
    if (accion.confirmar && !confirm(accion.confirmar)) return;

    if (accion.metodo === "GET") {
      SL.api(rutaAccion(accion, fila))
        .then(function (r) { verDetalle(r.datos); })
        .catch(SL.avisarError);
      return;
    }

    // La predicción necesita la entrega en el cuerpo, no en la ruta
    const extra = accion.clave === "predecir" && fila
      ? {entrega_id: fila.id} : {};

    abrirFormulario({
      titulo: accion.etiqueta + (fila ? " · " + etiquetaDe(fila) : ""),
      descripcion: accion.descripcion,
      campos: accion.campos,
      // Las acciones que REEMPLAZAN una lista llegan con la lista actual.
      // Presentarla vacía donde el servicio espera la completa invitaría a
      // borrar sin querer todo lo que había.
      valores: (accion.precargar && fila) ? fila : {},
      enviar: function (datos) {
        return SL.api(rutaAccion(accion, fila), {
          method: accion.metodo,
          cuerpo: Object.assign({}, extra, datos)
        });
      }
    });
  }

  function etiquetaDe(fila) {
    return fila.folio_entrega || fila.folio_viaje || fila.folio_incidente ||
           fila.folio_mantenimiento || fila.codigo_vehiculo ||
           fila.codigo_ruta || fila.codigo_operador || fila.usuario || "";
  }

  // ======================================================================
  // RESUMEN
  // ======================================================================
  async function cargarResumen() {
    const zona = document.getElementById("resumen");
    if (!zona) return;
    try {
      const r = await SL.api(M.recurso + M.resumen);
      zona.className = "";
      zona.innerHTML = "";

      const lectura = document.createElement("p");
      lectura.className = "sl-lectura mb-3 mt-0";
      lectura.textContent = r.mensaje || "";
      zona.appendChild(lectura);

      const rejilla = document.createElement("div");
      rejilla.className = "sl-rejilla-2";
      Object.keys(r.datos || {}).forEach(function (clave) {
        const valor = r.datos[clave];
        if (valor === null || typeof valor === "string") return;
        const tarjeta = document.createElement("div");
        tarjeta.className = "sl-tarjeta";
        const titulo = document.createElement("h6");
        titulo.textContent = clave.replace(/_/g, " ");
        tarjeta.appendChild(titulo);
        tarjeta.appendChild(cuerpoResumen(valor));
        rejilla.appendChild(tarjeta);
      });
      zona.appendChild(rejilla);
    } catch (error) {
      zona.className = "sl-cargando";
      zona.textContent = "No se pudo cargar el resumen: " + error.message;
    }
  }

  function cuerpoResumen(valor) {
    if (typeof valor === "number") {
      const p = document.createElement("p");
      p.className = "sl-kpi-valor mb-0";
      p.textContent = SL.entero(valor);
      return p;
    }
    if (Array.isArray(valor)) {
      const tabla = document.createElement("table");
      tabla.className = "sl-detalle-tabla";
      valor.slice(0, 10).forEach(function (item) {
        const tr = document.createElement("tr");
        const th = document.createElement("th");
        const td = document.createElement("td");
        if (item && typeof item === "object") {
          const claves = Object.keys(item);
          th.textContent = String(item[claves[0]]);
          td.textContent = claves.slice(1).map(function (k) {
            return k.replace(/_/g, " ") + ": " + item[k];
          }).join(" · ");
        } else { th.textContent = String(item); }
        tr.appendChild(th); tr.appendChild(td);
        tabla.appendChild(tr);
      });
      return tabla;
    }
    const tabla = document.createElement("table");
    tabla.className = "sl-detalle-tabla";
    Object.keys(valor || {}).forEach(function (clave) {
      const tr = document.createElement("tr");
      const th = document.createElement("th");
      th.textContent = clave.replace(/_/g, " ");
      const td = document.createElement("td");
      const dato = valor[clave];
      td.textContent = (dato && typeof dato === "object")
        ? JSON.stringify(dato) : String(dato);
      tr.appendChild(th); tr.appendChild(td);
      tabla.appendChild(tr);
    });
    return tabla;
  }

  // ======================================================================
  // ARRANQUE
  // ======================================================================
  const formFiltros = document.getElementById("filtros");
  formFiltros.addEventListener("submit", function (evento) {
    evento.preventDefault();
    estado.filtros = {};
    M.filtros.forEach(function (filtro) {
      const control = document.getElementById("f-" + filtro.nombre);
      if (!control) return;
      estado.filtros[filtro.nombre] = control.type === "checkbox"
        ? control.checked : control.value;
    });
    estado.pagina = 1;
    cargar();
  });
  document.getElementById("btn-limpiar").addEventListener("click", function () {
    setTimeout(function () {
      estado.filtros = {}; estado.pagina = 1; cargar();
    }, 0);
  });

  document.getElementById("btn-anterior").addEventListener("click", function () {
    if (estado.pagina > 1) { estado.pagina--; cargar(); }
  });
  document.getElementById("btn-siguiente").addEventListener("click", function () {
    if (estado.pagina * estado.tamano < estado.total) { estado.pagina++; cargar(); }
  });

  const btnAlta = document.getElementById("btn-alta");
  if (btnAlta) {
    btnAlta.addEventListener("click", function () {
      abrirFormulario({
        titulo: M.etiqueta_alta,
        descripcion: "",
        campos: M.campos_alta,
        valores: {},
        enviar: function (datos) {
          return SL.api(M.recurso, {method: "POST", cuerpo: datos});
        }
      });
    });
  }

  document.querySelectorAll("[data-accion-global]").forEach(function (boton) {
    const accion = (M.acciones || []).find(function (a) {
      return a.clave === boton.dataset.accionGlobal;
    });
    if (accion) boton.addEventListener("click", function () { ejecutar(accion, null); });
  });

  cargarReferencias(formFiltros);
  cargar();
  cargarResumen();
})();
