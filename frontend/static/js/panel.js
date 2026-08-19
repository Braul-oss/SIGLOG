/* =========================================================================
   SIG-LOG — panel ejecutivo

   Pensado para alguien que no conoce el modelo de datos. Cuatro bloques,
   en orden: qué pasó, cómo evoluciona, dónde están los problemas y por qué
   ocurren.

   Toda gráfica lleva título, ejes rotulados con su unidad y el periodo que
   cubre. Un eje sin unidad obliga a adivinar, y quien adivina se equivoca.

   Ninguna cifra se calcula aquí: todas vienen de /analitica, /mantenimientos
   y /ml.
   ========================================================================= */

(function () {
  "use strict";

  const UMBRAL = window.SIGLOG.umbral;
  const PERIODO = JSON.parse(
    document.getElementById("datos-periodo").textContent || "{}");
  const ROTULO = PERIODO.etiqueta || "";

  /** Título de dos líneas: qué se mide y en qué periodo. */
  function titulo(texto) {
    return {display: true, text: ROTULO ? [texto, ROTULO] : texto,
            font: {size: 13}, padding: {bottom: 10}};
  }

  // ======================================================================
  // 2 · TENDENCIA
  // ======================================================================
  async function tendencia() {
    try {
      const r = await SL.api("/analitica/tendencia?agrupacion=semana");
      const p = r.datos.puntos;
      document.getElementById("l-tendencia").textContent = r.datos.lectura;

      new Chart(document.getElementById("g-tendencia"), {
        // Chart.js exige un tipo en la raíz aunque cada serie declare el
        // suyo: sin él lanza «"undefined" is not a registered controller»
        // y el lienzo queda en blanco. En una gráfica mixta el tipo de la
        // raíz es el de la mayoría —barras— y la línea lo sobrescribe.
        type: "bar",
        data: {
          labels: p.map(function (x) { return x.etiqueta; }),
          datasets: [
            {
              type: "bar", label: "Entregas realizadas",
              data: p.map(function (x) { return x.entregas; }),
              backgroundColor: "rgba(31,78,121,.35)",
              borderColor: SL.COLORES.principal, borderWidth: 1,
              yAxisID: "y", order: 3
            },
            {
              type: "line", label: "Retraso medio (minutos)",
              data: p.map(function (x) { return x.retraso_medio_min; }),
              borderColor: SL.COLORES.alerta,
              backgroundColor: SL.COLORES.alerta,
              yAxisID: "y2", tension: .3, pointRadius: 2, order: 1
            },
            {
              type: "line", label: "Umbral de " + UMBRAL + " minutos",
              data: p.map(function () { return UMBRAL; }),
              borderColor: "#8c9bb0", borderDash: [6, 4], borderWidth: 1.5,
              pointRadius: 0, yAxisID: "y2", order: 2
            }
          ]
        },
        options: {
          interaction: {mode: "index", intersect: false},
          plugins: {
            title: titulo("Entregas y retraso medio por semana"),
            legend: {position: "bottom", labels: {boxWidth: 12}},
            tooltip: {callbacks: {afterBody: function (ctx) {
              const x = p[ctx[0].dataIndex];
              return "Entregas fuera de hora: " + SL.entero(x.retrasadas) +
                     " (" + SL.numero(x.pct_retrasadas, 0) + "%)";
            }}}
          },
          scales: {
            x: {title: {display: true, text: "Semana (inicio)"},
                ticks: {maxRotation: 0, autoSkipPadding: 12}},
            y: {position: "left", beginAtZero: true,
                title: {display: true, text: "Entregas realizadas"},
                ticks: {callback: function (v) { return SL.entero(v); }}},
            y2: {position: "right", beginAtZero: true,
                 grid: {display: false},
                 title: {display: true, text: "Retraso medio (minutos)"},
                 ticks: {callback: function (v) { return SL.numero(v, 0); }}}
          }
        }
      });
    } catch (error) {
      document.getElementById("l-tendencia").textContent = error.message;
    }
  }

  // ======================================================================
  // 3 · PROBLEMAS
  // ======================================================================
  async function rutasConRetraso() {
    try {
      const r = await SL.api("/analitica/rutas-mas-usadas?orden=retraso&top=8");
      const filas = r.datos.rutas;
      document.getElementById("l-rutas-retraso").textContent = r.datos.lectura;

      new Chart(document.getElementById("g-rutas-retraso"), {
        type: "bar",
        data: {
          labels: filas.map(function (f) { return f.codigo_ruta; }),
          datasets: [{
            label: "Retraso medio (minutos)",
            data: filas.map(function (f) { return f.retraso_medio_min; }),
            backgroundColor: filas.map(function (f) {
              return f.sobre_umbral ? SL.COLORES.alerta : SL.COLORES.aviso;
            })
          }]
        },
        options: {
          indexAxis: "y",
          plugins: {
            title: titulo("Rutas con mayor retraso medio"),
            legend: {display: false},
            tooltip: {callbacks: {
              title: function (ctx) {
                const f = filas[ctx[0].dataIndex];
                return f.codigo_ruta + " · " + (f.nombre_ruta || "");
              },
              label: function (ctx) {
                return "Retraso medio: " + SL.numero(ctx.raw, 1) + " min";
              },
              afterLabel: function (ctx) {
                const f = filas[ctx.dataIndex];
                return [
                  "Entregas: " + SL.entero(f.entregas),
                  "Fuera de hora: " + SL.numero(f.pct_retrasadas, 0) + "%",
                  "Zona: " + (f.zona || "—")
                ];
              }
            }}
          },
          scales: {
            x: {beginAtZero: true,
                title: {display: true, text: "Retraso medio (minutos)"}},
            y: {title: {display: true, text: "Ruta"}}
          }
        }
      });
    } catch (error) {
      document.getElementById("l-rutas-retraso").textContent = error.message;
    }
  }

  async function vehiculosCaros() {
    try {
      const r = await SL.api("/analitica/vehiculos?orden=costo&top=8");
      const filas = r.datos.vehiculos;
      document.getElementById("l-vehiculos-costo").textContent = r.datos.lectura;

      new Chart(document.getElementById("g-vehiculos-costo"), {
        type: "bar",
        data: {
          labels: filas.map(function (v) { return v.codigo_vehiculo; }),
          datasets: [
            {
              label: "Combustible (MXN)",
              data: filas.map(function (v) { return v.costo_combustible; }),
              backgroundColor: SL.COLORES.aviso
            },
            {
              label: "Mantenimiento (MXN)",
              data: filas.map(function (v) { return v.costo_mantenimiento; }),
              backgroundColor: SL.COLORES.principal
            }
          ]
        },
        options: {
          indexAxis: "y",
          plugins: {
            title: titulo("Costo de operación por vehículo"),
            legend: {position: "bottom", labels: {boxWidth: 12}},
            tooltip: {callbacks: {
              title: function (ctx) {
                const v = filas[ctx[0].dataIndex];
                return v.codigo_vehiculo + " · " + v.descripcion;
              },
              label: function (ctx) {
                return ctx.dataset.label.replace(" (MXN)", "") + ": " +
                       SL.dinero(ctx.raw);
              },
              afterBody: function (ctx) {
                const v = filas[ctx[0].dataIndex];
                return "Total: " + SL.dinero(v.costo_total) +
                       " · " + SL.entero(v.entregas) + " entregas";
              }
            }}
          },
          scales: {
            x: {stacked: true, beginAtZero: true,
                title: {display: true, text: "Costo acumulado (MXN)"},
                ticks: {callback: function (v) { return SL.dinero(v); }}},
            y: {stacked: true, title: {display: true, text: "Vehículo"}}
          }
        }
      });
    } catch (error) {
      document.getElementById("l-vehiculos-costo").textContent = error.message;
    }
  }

  async function mantenimiento() {
    const zona = document.getElementById("t-mantenimiento");
    try {
      const r = await SL.api("/mantenimientos/pendientes");
      const d = r.datos;
      const filas = d.vencidos.concat(d.atrasados).slice(0, 6);

      let html = "<h6><i class='bi bi-tools'></i> Unidades fuera de operación</h6>";
      html += '<div class="d-flex gap-2 mb-3 flex-wrap">' +
        pastilla("Ya paradas", d.total_vencidos, "mal") +
        pastilla("Por atender hoy", d.total_atrasados, "alerta") +
        pastilla("Próximas", d.total_proximos, "info") + "</div>";
      html += '<p class="sl-lectura mt-0 mb-3">' + SL.escapar(d.alerta) + "</p>";

      if (filas.length) {
        html += '<div class="sl-tabla-envoltura"><table class="table ' +
          'table-sm sl-tabla mb-0"><thead><tr><th>Vehículo</th>' +
          "<th>Situación</th><th class='text-end'>Días de atraso</th>" +
          "</tr></thead><tbody>";
        filas.forEach(function (f) {
          html += "<tr><td><strong>" + SL.escapar(f.codigo_vehiculo) +
            "</strong> <small class='text-body-secondary'>" +
            SL.escapar(f.placa || "") + "</small></td><td>" +
            SL.estado(f.estatus) + '</td><td class="sl-num">' +
            SL.entero(f.dias) + "</td></tr>";
        });
        html += "</tbody></table></div>";
      }
      zona.innerHTML = html;
    } catch (error) {
      zona.querySelector(".sl-cargando").textContent = error.message;
    }
  }

  async function riesgo() {
    const zona = document.getElementById("t-riesgo");
    try {
      const r = await SL.api("/ml/entregas-en-riesgo?limite=6");
      const d = r.datos;
      let html = "<h6><i class='bi bi-clock-history'></i> " +
                 "Entregas con riesgo de llegar tarde</h6>";
      html += '<p class="sl-lectura mt-0 mb-3">' + SL.escapar(d.lectura) + "</p>";

      if (d.entregas.length) {
        html += '<div class="sl-tabla-envoltura"><table class="table ' +
          'table-sm sl-tabla mb-0"><thead><tr><th>Entrega</th>' +
          "<th>Cliente</th><th class='text-end'>Probabilidad de retraso</th>" +
          "</tr></thead><tbody>";
        d.entregas.forEach(function (e) {
          const alto = e.riesgo_retraso === "ALTO";
          html += "<tr><td>" + SL.escapar(e.folio_entrega) + "</td><td>" +
            SL.escapar(e.nombre_cliente || "—") + '</td><td class="sl-num ' +
            (alto ? "text-danger fw-semibold" : "") + '">' +
            Math.round(e.probabilidad_retraso * 100) + "%</td></tr>";
        });
        html += "</tbody></table></div>";
      }
      zona.innerHTML = html;
    } catch (error) {
      zona.querySelector(".sl-cargando").textContent = error.message;
    }
  }

  function pastilla(texto, valor, clase) {
    return '<span class="sl-pastilla sl-pastilla-' + clase + '">' +
           SL.escapar(texto) + ": " + SL.entero(valor) + "</span>";
  }

  // ======================================================================
  // 4 · ANÁLISIS
  // ======================================================================
  async function causas() {
    try {
      const r = await SL.api("/analitica/causas-retraso");
      const filas = r.datos.causas;
      document.getElementById("l-causas").textContent = r.datos.lectura;

      new Chart(document.getElementById("g-causas"), {
        // Chart.js exige un tipo en la raíz aunque cada serie declare el
        // suyo: sin él lanza «"undefined" is not a registered controller»
        // y el lienzo queda en blanco. En una gráfica mixta el tipo de la
        // raíz es el de la mayoría —barras— y la línea lo sobrescribe.
        type: "bar",
        data: {
          labels: filas.map(function (f) {
            return f.causa.replace(/_/g, " ").toLowerCase();
          }),
          datasets: [
            {
              type: "bar", label: "Entregas retrasadas",
              data: filas.map(function (f) { return f.entregas; }),
              backgroundColor: filas.map(function (f) {
                return f.es_vital ? SL.COLORES.alerta : SL.COLORES.neutro;
              }),
              order: 2
            },
            {
              type: "line", label: "Porcentaje acumulado",
              data: filas.map(function (f) { return f.porcentaje_acumulado; }),
              borderColor: "#16202e", backgroundColor: "#16202e",
              yAxisID: "y2", tension: .2, pointRadius: 3, order: 1
            }
          ]
        },
        options: {
          plugins: {
            title: titulo("Causas del retraso, de mayor a menor frecuencia"),
            legend: {position: "bottom", labels: {boxWidth: 12}},
            tooltip: {callbacks: {afterLabel: function (ctx) {
              const f = filas[ctx.dataIndex];
              return "Retraso medio de esta causa: " +
                     SL.numero(f.retraso_medio_min, 1) + " min";
            }}}
          },
          scales: {
            x: {title: {display: true, text: "Causa"},
                ticks: {maxRotation: 35, minRotation: 0, font: {size: 10}}},
            y: {beginAtZero: true,
                title: {display: true, text: "Entregas retrasadas"},
                ticks: {callback: function (v) { return SL.entero(v); }}},
            y2: {position: "right", min: 0, max: 105, grid: {display: false},
                 title: {display: true, text: "Acumulado (%)"},
                 ticks: {callback: function (v) { return v + "%"; }}}
          }
        }
      });
    } catch (error) {
      document.getElementById("l-causas").textContent = error.message;
    }
  }

  async function gruposDeRutas() {
    const zona = document.getElementById("grupos-rutas");
    try {
      const r = await SL.api("/ml/clusters-rutas");
      const d = r.datos;
      zona.className = "";
      zona.innerHTML = "";

      d.grupos.forEach(function (g, i) {
        const caja = document.createElement("div");
        caja.className = "sl-grupo";
        caja.style.borderLeftColor =
          SL.COLORES.grupos[i % SL.COLORES.grupos.length];
        caja.innerHTML =
          "<div class='sl-grupo-cabecera'><strong>" + SL.escapar(g.nombre) +
          "</strong><span class='sl-pastilla sl-pastilla-neutra'>" +
          g.total_rutas + " rutas</span></div>" +
          "<p class='sl-ayuda mb-1'>" + SL.escapar(g.descripcion || "") + "</p>" +
          "<p class='sl-grupo-accion'><i class='bi bi-arrow-right-short'></i>" +
          SL.escapar(g.recomendacion || "") + "</p>";
        zona.appendChild(caja);
      });

      const nota = document.createElement("p");
      nota.className = "sl-ayuda mt-2 mb-0";
      nota.textContent =
        "Los grupos salen de comparar distancia, paradas, velocidad, " +
        "retraso e incidentes de cada ruta. Son una forma de ordenar la " +
        "operación para priorizar, no categorías cerradas: las rutas forman " +
        "un continuo y muchas quedan cerca de la frontera entre dos grupos.";
      zona.appendChild(nota);
    } catch (error) {
      zona.textContent = error.message;
    }
  }

  if (document.getElementById("g-tendencia")) {
    tendencia();
    rutasConRetraso();
    vehiculosCaros();
    mantenimiento();
    riesgo();
    causas();
    gruposDeRutas();
  }
})();
