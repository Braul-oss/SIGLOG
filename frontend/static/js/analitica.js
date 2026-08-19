/* =========================================================================
   SIG-LOG — pantalla de analítica

   Tres consultas agregadas y su lectura. Ninguna cifra se calcula aquí: la
   página pide, formatea y muestra. Si un número hiciera falta y el endpoint
   no lo diera, el sitio de arreglarlo es el servicio, no este archivo — en
   cuanto la interfaz empieza a recalcular, el dashboard y el API dejan de
   contar la misma historia.
   ========================================================================= */

(function () {
  "use strict";

  const UMBRAL = window.SIGLOG.umbral;
  const PERIODO = JSON.parse(
    document.getElementById("datos-periodo").textContent || "{}");
  const ROTULO = PERIODO.etiqueta || "";

  /** Título de dos líneas: qué se mide y en qué periodo se midió. */
  function titulo(texto) {
    return {display: true, text: ROTULO ? [texto, ROTULO] : texto,
            font: {size: 13}, padding: {bottom: 10}};
  }

  const ETIQUETA_ORDEN = {
    volumen: "Rutas por volumen de entregas",
    retraso: "Rutas por retraso medio",
    incidencia: "Rutas por proporción de entregas fuera de hora"
  };
  const EJE_ORDEN = {
    volumen: "Entregas realizadas",
    retraso: "Retraso medio (minutos)",
    incidencia: "Entregas fuera de hora (%)"
  };
  const CAMPO_ORDEN = {
    volumen: "entregas", retraso: "retraso_medio_min",
    incidencia: "pct_retrasadas"
  };

  let graficaRutas = null;

  async function rutas() {
    const top = document.getElementById("top").value;
    const orden = document.getElementById("orden").value;
    const campo = CAMPO_ORDEN[orden];
    try {
      const r = await SL.api("/analitica/rutas-mas-usadas?top=" + top +
                             "&orden=" + orden);
      const filas = r.datos.rutas;
      document.getElementById("l-rutas").textContent = r.datos.lectura;

      if (graficaRutas) graficaRutas.destroy();
      graficaRutas = new Chart(document.getElementById("g-rutas"), {
        type: "bar",
        data: {
          labels: filas.map(function (f) { return f.codigo_ruta; }),
          datasets: [{
            label: EJE_ORDEN[orden],
            data: filas.map(function (f) { return f[campo]; }),
            backgroundColor: filas.map(function (f) {
              return f.sobre_umbral ? SL.COLORES.alerta : SL.COLORES.principal;
            })
          }]
        },
        options: {
          plugins: {
            title: titulo(ETIQUETA_ORDEN[orden]),
            legend: {display: false},
            tooltip: {callbacks: {
              title: function (ctx) {
                const f = filas[ctx[0].dataIndex];
                return f.codigo_ruta + " · " + (f.nombre_ruta || "");
              },
              afterLabel: function (ctx) {
                const f = filas[ctx.dataIndex];
                return ["Entregas: " + SL.entero(f.entregas),
                        "Viajes: " + SL.entero(f.viajes),
                        "Retraso medio: " +
                          SL.numero(f.retraso_medio_min) + " min",
                        "Fuera de hora: " +
                          SL.numero(f.pct_retrasadas, 0) + "%",
                        "Distancia: " + SL.numero(f.distancia_km, 1) + " km"];
              }
            }}
          },
          scales: {
            x: {title: {display: true, text: "Ruta"}},
            y: {beginAtZero: true,
                title: {display: true, text: EJE_ORDEN[orden]},
                ticks: {callback: function (v) { return SL.numero(v, 0); }}}
          }
        }
      });

      const cuerpo = document.getElementById("tabla-rutas");
      cuerpo.innerHTML = "";
      filas.forEach(function (f) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + SL.escapar(f.codigo_ruta) + " <small class='text-body-secondary'>" +
          SL.escapar(f.nombre_ruta || "") + "</small></td>" +
          "<td>" + SL.estado(f.zona) + "</td>" +
          '<td class="sl-num">' + SL.entero(f.entregas) + "</td>" +
          '<td class="sl-num">' + SL.entero(f.viajes) + "</td>" +
          '<td class="sl-num ' + (f.sobre_umbral ? "text-danger fw-semibold" : "") +
          '">' + SL.numero(f.retraso_medio_min) + " min</td>" +
          '<td class="sl-num">' + SL.numero(f.pct_retrasadas) + "%</td>";
        cuerpo.appendChild(tr);
      });
    } catch (error) {
      document.getElementById("l-rutas").textContent = error.message;
    }
  }

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
              type: "line", label: "% acumulado",
              data: filas.map(function (f) { return f.porcentaje_acumulado; }),
              borderColor: "#16202e", backgroundColor: "#16202e",
              yAxisID: "y2", tension: .2, order: 1
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
            x: {title: {display: true, text: "Causa del retraso"},
                ticks: {maxRotation: 35, font: {size: 10}}},
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

  async function saturacion() {
    const cuerpo = document.getElementById("tabla-saturacion");
    try {
      const r = await SL.api("/analitica/saturacion-horaria");
      const d = r.datos;
      document.getElementById("l-saturacion").textContent = d.lectura;

      // Índice franja→día para poder recorrer la tabla por posición
      const celdas = {};
      let maximo = 0;
      d.celdas.forEach(function (c) {
        celdas[c.franja_horaria + "|" + c.dia_semana] = c.entregas;
        if (c.entregas > maximo) maximo = c.entregas;
      });

      cuerpo.innerHTML = "";
      d.por_franja.forEach(function (franja) {
        const tr = document.createElement("tr");
        const esMejor = franja.franja_horaria === d.franja_menor_retraso;

        let html = "<td>" + SL.escapar(
          franja.franja_horaria.replace(/_/g, " ")) +
          (esMejor ? ' <i class="bi bi-star-fill text-success" ' +
                     'title="Franja de menor retraso"></i>' : "") + "</td>";

        for (let dia = 0; dia < 7; dia++) {
          const valor = celdas[franja.franja_horaria + "|" + dia];
          const intensidad = maximo ? (valor || 0) / maximo : 0;
          const fondo = "rgba(214, 39, 40, " + (intensidad * 0.75).toFixed(3) + ")";
          const tinta = intensidad > 0.55 ? "#fff" : "inherit";
          html += "<td>" + (valor === undefined ? "—" :
            '<span class="sl-celda" style="background:' + fondo +
            ";color:" + tinta + '">' + SL.entero(valor) + "</span>") + "</td>";
        }
        html += '<td class="sl-num">' + SL.numero(franja.retraso_medio_min) +
                " min</td>";
        tr.innerHTML = html;
        cuerpo.appendChild(tr);
      });
    } catch (error) {
      cuerpo.innerHTML = '<tr><td colspan="9" class="sl-cargando"></td></tr>';
      cuerpo.querySelector("td").textContent = error.message;
    }
  }

  document.getElementById("top").addEventListener("change", rutas);
  document.getElementById("orden").addEventListener("change", rutas);
  rutas(); causas(); saturacion();
})();
