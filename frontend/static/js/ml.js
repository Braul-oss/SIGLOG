/* =========================================================================
   SIG-LOG — pantalla de Machine Learning

   Muestra los modelos ya entrenados y aplica su predicción. No entrena
   nada: entrenar es un proceso de `ml/`, con su semilla y su partición
   reproducibles, no algo que se dispare desde un navegador.
   ========================================================================= */

(function () {
  "use strict";

  // ======================================================================
  // MODELOS
  // ======================================================================
  async function modelos() {
    const zona = document.getElementById("modelos");
    try {
      const r = await SL.api("/ml/modelos");
      const d = r.datos;
      document.getElementById("l-modelos").textContent = d.lectura;

      const tabla = document.createElement("table");
      tabla.className = "table table-sm sl-tabla mb-0";
      tabla.innerHTML = "<thead><tr><th>Modelo</th><th>Tipo</th>" +
        "<th>Escenario</th><th>Algoritmo</th><th>Métricas</th>" +
        "<th class='sl-num'>Entrenamiento</th><th>Binario</th></tr></thead>";

      const cuerpo = document.createElement("tbody");
      d.modelos.forEach(function (m) {
        const metricas = Object.keys(m.metricas).map(function (k) {
          return k.toUpperCase() + " " + SL.numero(m.metricas[k], 3);
        }).join(" · ");
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td><code>" + SL.escapar(m.nombre) + "</code></td>" +
          "<td>" + SL.estado(m.tipo) + "</td>" +
          "<td>" + SL.estado(m.escenario) + "</td>" +
          "<td>" + SL.escapar(m.algoritmo) + "</td>" +
          "<td><small>" + SL.escapar(metricas) + "</small></td>" +
          '<td class="sl-num">' + SL.entero(m.n_entrenamiento) + "</td>" +
          "<td>" + (m.binario_disponible
            ? '<i class="bi bi-check-circle-fill text-success"></i>'
            : '<i class="bi bi-x-circle-fill text-danger" ' +
              'title="Registrado pero sin .joblib en disco"></i>') + "</td>";
        cuerpo.appendChild(tr);
      });
      tabla.appendChild(cuerpo);

      zona.className = "sl-tabla-envoltura";
      zona.innerHTML = "";
      zona.appendChild(tabla);
    } catch (error) {
      zona.textContent = error.message;
    }
  }

  // ======================================================================
  // ENTREGAS EN RIESGO
  // ======================================================================
  async function riesgo() {
    const zona = document.getElementById("riesgo");
    try {
      const r = await SL.api("/ml/entregas-en-riesgo?limite=25");
      const d = r.datos;

      if (!d.entregas.length) {
        zona.className = "sl-vacio";
        zona.innerHTML = '<i class="bi bi-inbox"></i><h3>Sin predicciones</h3>' +
          "<p></p>";
        zona.querySelector("p").textContent = d.lectura;
        return;
      }

      const tabla = document.createElement("table");
      tabla.className = "table table-sm table-hover sl-tabla mb-0";
      tabla.innerHTML = "<thead><tr><th>Entrega</th><th>Cliente</th>" +
        "<th>Estatus</th><th>ETA</th><th class='sl-num'>Probabilidad</th>" +
        "<th class='sl-num'>Minutos</th><th>Riesgo</th></tr></thead>";

      const cuerpo = document.createElement("tbody");
      d.entregas.forEach(function (e) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + SL.escapar(e.folio_entrega) + "</td>" +
          "<td>" + SL.escapar(e.nombre_cliente || "—") + "</td>" +
          "<td>" + SL.estado(e.estatus) + "</td>" +
          "<td>" + SL.hora(e.hora_estimada_llegada) + "</td>" +
          '<td class="sl-num">' + Math.round(e.probabilidad_retraso * 100) + "%</td>" +
          '<td class="sl-num">' + SL.numero(e.retraso_estimado_min) + "</td>" +
          "<td>" + pastillaRiesgo(e.riesgo_retraso) + "</td>";
        cuerpo.appendChild(tr);
      });
      tabla.appendChild(cuerpo);

      const lectura = document.createElement("p");
      lectura.className = "sl-lectura mt-0 mb-3";
      lectura.textContent = d.lectura;

      zona.className = "";
      zona.innerHTML = "";
      zona.appendChild(lectura);
      const envoltura = document.createElement("div");
      envoltura.className = "sl-tabla-envoltura";
      envoltura.appendChild(tabla);
      zona.appendChild(envoltura);
    } catch (error) {
      zona.textContent = error.message;
    }
  }

  function pastillaRiesgo(riesgo) {
    const clase = riesgo === "ALTO" ? "sl-pastilla-mal"
                : riesgo === "MEDIO" ? "sl-pastilla-alerta" : "sl-pastilla-ok";
    return '<span class="sl-pastilla ' + clase + '">' +
           SL.escapar(riesgo || "—") + "</span>";
  }

  // ======================================================================
  // PREDICCIÓN
  // ======================================================================
  async function cargarEntregasPendientes() {
    const select = document.getElementById("entrega");
    if (!select) return;
    try {
      // Solo las que aún no han llegado: sobre una entrega cerrada el
      // servicio responde 409, y ofrecerla sería ofrecer un error.
      const r = await SL.api("/entregas?estatus=PROGRAMADA&pagina=1&tamano=100");
      const filas = r.datos || [];
      select.innerHTML = "";
      if (!filas.length) {
        select.appendChild(new Option("No hay entregas pendientes", ""));
        select.disabled = true;
        return;
      }
      select.appendChild(new Option("— elegir —", ""));
      filas.forEach(function (e) {
        select.appendChild(new Option(
          e.folio_entrega + " · " + (e.nombre_cliente || ""), e.id));
      });
    } catch (error) {
      select.innerHTML = "";
      select.appendChild(new Option("No se pudieron cargar", ""));
    }
  }

  const formulario = document.getElementById("form-prediccion");
  if (formulario) {
    formulario.addEventListener("submit", async function (evento) {
      evento.preventDefault();
      const entrega = document.getElementById("entrega").value;
      if (!entrega) return;

      const zona = document.getElementById("resultado-prediccion");
      zona.innerHTML = '<div class="sl-cargando">Aplicando los modelos…</div>';
      try {
        const r = await SL.api("/ml/predecir-retraso", {
          method: "POST",
          cuerpo: {entrega_id: entrega,
                   guardar: document.getElementById("guardar").checked}
        });
        zona.innerHTML = "";
        zona.appendChild(tarjetaPrediccion(r.datos));
        riesgo();
      } catch (error) {
        zona.innerHTML = '<div class="alert alert-danger py-2 small"></div>';
        zona.firstChild.style.whiteSpace = "pre-line";
        zona.firstChild.textContent = error instanceof SL.ErrorApi
          ? error.completo() : String(error);
      }
    });
  }

  function tarjetaPrediccion(d) {
    const caja = document.createElement("div");
    caja.className = "sl-tarjeta";

    const variables = Object.keys(d.variables).map(function (k) {
      return "<tr><th>" + SL.escapar(k.replace(/_/g, " ")) + "</th><td>" +
             SL.escapar(d.variables[k]) + "</td></tr>";
    }).join("");

    caja.innerHTML =
      "<h6>" + SL.escapar(d.folio_entrega) + " · escenario " +
      SL.estado(d.escenario) + "</h6>" +
      '<div class="d-flex gap-4 mb-3">' +
        '<div><p class="sl-kpi-titulo mb-1">Probabilidad</p>' +
        '<p class="sl-kpi-valor mb-0">' +
        Math.round(d.probabilidad_retraso * 100) + "<small>%</small></p></div>" +
        '<div><p class="sl-kpi-titulo mb-1">Retraso estimado</p>' +
        '<p class="sl-kpi-valor mb-0">' + SL.numero(d.retraso_estimado_min) +
        "<small>min</small></p></div>" +
        '<div><p class="sl-kpi-titulo mb-1">Riesgo</p><p class="mb-0 mt-2">' +
        pastillaRiesgo(d.riesgo) + "</p></div>" +
      "</div>" +
      '<p class="sl-lectura mt-0">' + SL.escapar(d.lectura) + "</p>" +
      '<details class="mt-3"><summary class="small text-body-secondary">' +
      "Vector de variables con el que se predijo</summary>" +
      '<p class="sl-ayuda mt-2">Son las mismas variables, en el mismo orden, ' +
      "con las que se entrenó el modelo. " +
      SL.escapar(d.contexto.motivo_escenario) + "</p>" +
      '<table class="sl-detalle-tabla">' + variables + "</table></details>";
    return caja;
  }

  // ======================================================================
  // CLUSTERS
  // ======================================================================
  async function clusters() {
    const zona = document.getElementById("grupos");
    try {
      const r = await SL.api("/ml/clusters-rutas");
      const d = r.datos;
      document.getElementById("l-clusters").textContent = d.lectura;
      document.getElementById("nota-clusters").textContent =
        d.algoritmo + " en el espacio " + d.espacio + ", con k = " + d.k +
        " y silueta global " + d.silueta_global + ".";

      // Dispersión en el plano PCA: un punto por ruta, color por grupo
      const conjuntos = d.grupos.map(function (g, i) {
        const rutas = d.rutas.filter(function (ruta) {
          return ruta.grupo === g.grupo;
        });
        return {
          label: g.nombre,
          data: rutas.map(function (ruta) {
            return {x: ruta.componente_1, y: ruta.componente_2,
                    codigo: ruta.codigo_ruta};
          }),
          backgroundColor: SL.COLORES.grupos[i % SL.COLORES.grupos.length],
          pointRadius: 6
        };
      });

      new Chart(document.getElementById("g-clusters"), {
        type: "scatter",
        data: {datasets: conjuntos},
        options: {
          plugins: {
            legend: {position: "bottom", labels: {boxWidth: 10, font: {size: 10}}},
            tooltip: {callbacks: {label: function (ctx) {
              return ctx.raw.codigo + " (" + ctx.dataset.label + ")";
            }}}
          },
          scales: {
            x: {title: {display: true, text: "Componente 1"}},
            y: {title: {display: true, text: "Componente 2"}}
          }
        }
      });

      zona.className = "";
      zona.innerHTML = "";
      d.grupos.forEach(function (g, i) {
        const tarjeta = document.createElement("div");
        tarjeta.className = "sl-tarjeta mb-2";
        tarjeta.style.borderLeft = "3px solid " +
          SL.COLORES.grupos[i % SL.COLORES.grupos.length];
        tarjeta.innerHTML =
          "<h6>" + SL.escapar(g.nombre) + " <span class='sl-pastilla " +
          "sl-pastilla-neutra'>" + g.total_rutas + " rutas</span></h6>" +
          '<p class="sl-ayuda mb-2">' + SL.escapar(g.descripcion || "") + "</p>" +
          '<p class="sl-lectura mt-0 mb-2">' +
          SL.escapar(g.recomendacion || "") + "</p>" +
          "<p class='sl-ayuda mb-0'><strong>Rutas:</strong> " +
          SL.escapar(g.rutas.join(", ")) + "</p>";
        zona.appendChild(tarjeta);
      });
    } catch (error) {
      zona.textContent = error.message;
    }
  }

  modelos();
  riesgo();
  clusters();
  if (window.SIGLOG.puedePredecir) cargarEntregasPendientes();
})();
