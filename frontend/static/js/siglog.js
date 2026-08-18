/* =========================================================================
   SIG-LOG — utilidades compartidas de la interfaz

   Sin framework, sin build, sin npm: es lo que el §8.2 descarta. Solo estas
   funciones y Bootstrap.

   El token de sesión NO aparece por ningún lado en este archivo. Viaja en
   una cookie HttpOnly que el navegador adjunta solo, y que el JavaScript no
   puede leer aunque quiera. Esa es justamente la protección: un XSS en esta
   página no podría llevarse la sesión.
   ========================================================================= */

(function (global) {
  "use strict";

  const PREFIJO = (global.SIGLOG && global.SIGLOG.prefijo) || "/api/v1";

  // ======================================================================
  // LLAMADAS AL API
  // ======================================================================

  /**
   * Toda respuesta del API sigue el mismo contrato (§12.2):
   *   éxito → {exito, mensaje, datos, total}
   *   error → {exito, mensaje, codigo_error, detalles}
   *
   * Aprovecharlo aquí significa que un error de negocio llega a la pantalla
   * con el mensaje que escribió el servicio —"El vehículo VEH-003 ya cubre
   * la ruta RUT-007 (RN-04)"— en vez de un "Error 409" que no explica nada.
   */
  async function api(ruta, opciones) {
    const config = Object.assign({
      headers: {"Accept": "application/json"},
      credentials: "same-origin"       // la cookie de sesión
    }, opciones || {});

    if (config.cuerpo !== undefined) {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.cuerpo);
      delete config.cuerpo;
    }

    let respuesta;
    try {
      respuesta = await fetch(PREFIJO + ruta, config);
    } catch (error) {
      throw new ErrorApi("No se pudo contactar con el servidor. " +
        "Comprueba que la API sigue en marcha.", 0, []);
    }

    // 401: la sesión caducó. Volver al formulario es más útil que un aviso,
    // porque nada de lo que haga el usuario va a funcionar hasta que entre.
    if (respuesta.status === 401) {
      global.location.href = "/entrar?destino=" +
        encodeURIComponent(global.location.pathname);
      throw new ErrorApi("La sesión caducó.", 401, []);
    }

    let cuerpo = null;
    try { cuerpo = await respuesta.json(); } catch (e) { cuerpo = null; }

    if (!respuesta.ok) {
      throw new ErrorApi(
        (cuerpo && cuerpo.mensaje) || "Error " + respuesta.status,
        respuesta.status,
        (cuerpo && cuerpo.detalles) || [],
        cuerpo && cuerpo.codigo_error);
    }
    return cuerpo;
  }

  class ErrorApi extends Error {
    constructor(mensaje, estado, detalles, codigo) {
      super(mensaje);
      this.estado = estado;
      this.detalles = detalles || [];
      this.codigo = codigo || "";
    }
    /** Mensaje + los campos concretos que fallaron, si el API los dio. */
    completo() {
      if (!this.detalles.length) return this.message;
      const lineas = this.detalles.map(function (d) {
        if (d && d.campo) return "· " + d.campo + ": " + d.problema;
        if (typeof d === "string") return "· " + d;
        return "· " + JSON.stringify(d);
      });
      return this.message + "\n" + lineas.join("\n");
    }
  }

  // ======================================================================
  // AVISOS
  // ======================================================================
  function avisar(mensaje, tipo) {
    const zona = document.getElementById("sl-avisos");
    if (!zona) { console.log(mensaje); return; }

    const caja = document.createElement("div");
    caja.className = "alert alert-" + (tipo || "info") +
                     " alert-dismissible fade show py-2 small";
    caja.setAttribute("role", "alert");
    caja.innerHTML = '<div style="white-space:pre-line"></div>' +
      '<button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
    caja.firstChild.textContent = mensaje;
    zona.appendChild(caja);

    // Los avisos de éxito se van solos; los errores se quedan hasta que
    // alguien los cierre — un error que desaparece antes de leerse no sirve.
    if (tipo === "success" || tipo === "info") {
      setTimeout(function () {
        caja.classList.remove("show");
        setTimeout(function () { caja.remove(); }, 300);
      }, 5000);
    }
  }

  function avisarError(error) {
    if (error instanceof ErrorApi && error.estado === 401) return;
    avisar(error instanceof ErrorApi ? error.completo() : String(error.message || error),
           "danger");
  }

  // ======================================================================
  // FORMATO
  // ======================================================================
  const NOMBRES_DIA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes",
                       "Sábado", "Domingo"];

  function esVacio(valor) {
    return valor === null || valor === undefined || valor === "";
  }

  function numero(valor, decimales) {
    if (esVacio(valor)) return "—";
    const n = Number(valor);
    if (Number.isNaN(n)) return String(valor);
    return n.toLocaleString("es-MX", {
      minimumFractionDigits: decimales === undefined ? 1 : decimales,
      maximumFractionDigits: decimales === undefined ? 1 : decimales
    });
  }

  function entero(valor) {
    if (esVacio(valor)) return "—";
    const n = Number(valor);
    return Number.isNaN(n) ? String(valor) : n.toLocaleString("es-MX");
  }

  function dinero(valor) {
    if (esVacio(valor)) return "—";
    const n = Number(valor);
    if (Number.isNaN(n)) return String(valor);
    return "$" + n.toLocaleString("es-MX", {minimumFractionDigits: 2,
                                            maximumFractionDigits: 2});
  }

  function aFecha(valor) {
    if (esVacio(valor)) return null;
    const d = new Date(valor);
    return isNaN(d.getTime()) ? null : d;
  }

  function fecha(valor) {
    const d = aFecha(valor);
    return d ? d.toLocaleDateString("es-MX") : "—";
  }

  function fechaHora(valor) {
    const d = aFecha(valor);
    if (!d) return "—";
    return d.toLocaleDateString("es-MX") + " " +
           d.toLocaleTimeString("es-MX", {hour: "2-digit", minute: "2-digit"});
  }

  function hora(valor) {
    if (esVacio(valor)) return "—";
    // Las horas programadas de una ruta llegan como "06:30", no como fecha
    if (typeof valor === "string" && /^\d{1,2}:\d{2}$/.test(valor)) return valor;
    const d = aFecha(valor);
    return d ? d.toLocaleTimeString("es-MX", {hour: "2-digit", minute: "2-digit"})
             : "—";
  }

  /** Minutos con signo: el negativo es adelanto y merece leerse distinto. */
  function minutos(valor) {
    if (esVacio(valor)) return "—";
    const n = Number(valor);
    if (Number.isNaN(n)) return String(valor);
    const texto = (n > 0 ? "+" : "") + numero(n, 1);
    const clase = n > 0 ? "text-danger" : (n < 0 ? "text-success" : "");
    return '<span class="' + clase + '">' + texto + "</span>";
  }

  function booleano(valor) {
    if (esVacio(valor)) return "—";
    const si = valor === true || valor === 1 || valor === "true";
    return si ? '<i class="bi bi-check-circle-fill text-success"></i>'
              : '<i class="bi bi-dash-circle text-body-tertiary"></i>';
  }

  /**
   * Píldora de estado. El color no es decorativo: verde es que la cosa está
   * en orden, rojo que exige intervención. Un estado neutro no se pinta de
   * verde solo por rellenar.
   */
  const ESTADOS_BIEN = ["DISPONIBLE", "ACTIVO", "REALIZADO", "FINALIZADO",
                        "ENTREGADA", "PREVENTIVO", "BAJA"];
  const ESTADOS_MAL = ["VENCIDO", "CANCELADO", "CANCELADA", "NO_ENTREGADA",
                       "ALTA", "CORRECTIVO", "INACTIVO"];
  const ESTADOS_ALERTA = ["EN_MANTENIMIENTO", "PROGRAMADO", "PROGRAMADA",
                          "MEDIA", "PLANEACION"];

  function estado(valor) {
    if (esVacio(valor)) return "—";
    const texto = String(valor);
    let clase = "sl-pastilla-neutra";
    if (ESTADOS_BIEN.indexOf(texto) >= 0) clase = "sl-pastilla-ok";
    else if (ESTADOS_MAL.indexOf(texto) >= 0) clase = "sl-pastilla-mal";
    else if (ESTADOS_ALERTA.indexOf(texto) >= 0) clase = "sl-pastilla-alerta";
    else if (texto === "EN_RUTA" || texto === "EN_CURSO") clase = "sl-pastilla-info";
    const etiqueta = texto.replace(/_/g, " ");
    return '<span class="sl-pastilla ' + clase + '">' +
           escapar(etiqueta) + "</span>";
  }

  function lista(valor) {
    if (!Array.isArray(valor) || !valor.length) return "—";
    return escapar(valor.map(function (v) {
      return typeof v === "string" ? v.slice(0, 3) : v;
    }).join(", "));
  }

  /** Escapa antes de insertar como HTML. Los datos vienen del API, pero
   *  también los captura un humano: nada entra en el DOM sin pasar por aquí. */
  function escapar(texto) {
    if (texto === null || texto === undefined) return "";
    return String(texto)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  const FORMATOS = {
    texto: function (v) { return esVacio(v) ? "—" : escapar(v); },
    numero: numero, entero: entero, dinero: dinero,
    fecha: fecha, fechahora: fechaHora, hora: hora,
    booleano: booleano, estado: estado, lista: lista, minutos: minutos
  };

  function formatear(valor, formato) {
    const fn = FORMATOS[formato || "texto"] || FORMATOS.texto;
    return fn(valor);
  }

  /** Las celdas que llevan HTML propio no deben re-escaparse. */
  const FORMATOS_CON_HTML = ["booleano", "estado", "minutos"];

  // ======================================================================
  // COLORES DE LAS GRÁFICAS
  // ======================================================================
  const COLORES = {
    principal: "#1f4e79", alerta: "#d62728", bien: "#2ca02c",
    aviso: "#ff7f0e", neutro: "#8c9bb0",
    grupos: ["#1f4e79", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
             "#8c564b", "#17becf", "#7f7f7f"]
  };

  global.SL = {
    api: api, ErrorApi: ErrorApi,
    avisar: avisar, avisarError: avisarError,
    formatear: formatear, FORMATOS_CON_HTML: FORMATOS_CON_HTML,
    escapar: escapar, esVacio: esVacio,
    numero: numero, entero: entero, dinero: dinero,
    fecha: fecha, fechaHora: fechaHora, hora: hora, estado: estado,
    NOMBRES_DIA: NOMBRES_DIA, COLORES: COLORES, PREFIJO: PREFIJO
  };
})(window);
