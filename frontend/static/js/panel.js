/* =========================================================================
   SIG-LOG — panel ejecutivo

   Los KPIs llegan ya pintados desde el servidor. Aquí solo se añaden las
   dos gráficas y las dos alertas operativas, que salen de los endpoints de
   analítica, mantenimiento y ML — nunca de un cálculo propio de la página.
   ========================================================================= */

(function () {
  "use strict";

  const UMBRAL_ALTO = 0.70;

  async function rutas() {
    try {
      const r = await SL.api("/analitica/rutas-mas-usadas?top=8");
      const filas = r.datos.rutas;
      document.getElementById("l-rutas").textContent = r.datos.lectura;

      new Chart(document.getElementById("g-rutas"), {
        type: "bar",
        data: {
          labels: filas.map(function (f) { return f.codigo_ruta; }),
          datasets: [{
            label: "Entregas",
            data: filas.map(function (f) { return f.entregas; }),
            // El rojo no decora: marca la ruta que promedia más retraso del
            // admitido, que es la que exige una decisión.
            backgroundColor: filas.map(function (f) {
              return f.sobre_umbral ? SL.COLORES.alerta : SL.COLORES.principal;
            })
          }]
        },
        options: {
          indexAxis: "y",
          plugins: {
            legend: {display: false},
            tooltip: {callbacks: {afterLabel: function (ctx) {
              const f = filas[ctx.dataIndex];
              return "Retraso medio: " + SL.numero(f.retraso_medio_min) + " min";
            }}}
          },
          scales: {x: {beginAtZero: true}}
        }
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
        data: {
          labels: filas.map(function (f) {
            return f.causa.replace(/_/g, " ");
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
              yAxisID: "y2", tension: .2, pointRadius: 3, order: 1
            }
          ]
        },
        options: {
          plugins: {legend: {display: true, position: "bottom",
                             labels: {boxWidth: 12, font: {size: 10}}}},
          scales: {
            y: {beginAtZero: true},
            y2: {position: "right", min: 0, max: 105, grid: {display: false},
                 ticks: {callback: function (v) { return v + "%"; }}}
          }
        }
      });
    } catch (error) {
      document.getElementById("l-causas").textContent = error.message;
    }
  }

  async function mantenimiento() {
    const zona = document.getElementById("t-mantenimiento");
    try {
      const r = await SL.api("/mantenimientos/pendientes");
      const d = r.datos;
      const filas = d.vencidos.concat(d.atrasados).slice(0, 6);

      let html = '<p class="sl-lectura mt-0 mb-3">' + SL.escapar(d.alerta) + "</p>";
      html += '<div class="d-flex gap-3 mb-3 small">' +
        pastilla("Vencidos", d.total_vencidos, "mal") +
        pastilla("Atrasados", d.total_atrasados, "alerta") +
        pastilla("Próximos", d.total_proximos, "info") + "</div>";

      if (filas.length) {
        html += '<table class="table table-sm sl-tabla mb-0"><tbody>';
        filas.forEach(function (f) {
          html += "<tr><td>" + SL.escapar(f.codigo_vehiculo) + "</td><td>" +
            SL.estado(f.estatus) + '</td><td class="sl-num">' +
            SL.entero(f.dias) + " días</td></tr>";
        });
        html += "</tbody></table>";
      }
      zona.innerHTML = "<h6><i class='bi bi-tools'></i> Mantenimiento pendiente</h6>" + html;
    } catch (error) {
      zona.querySelector(".sl-cargando").textContent = error.message;
    }
  }

  async function riesgo() {
    const zona = document.getElementById("t-riesgo");
    try {
      const r = await SL.api("/ml/entregas-en-riesgo?limite=6");
      const d = r.datos;
      let html = '<p class="sl-lectura mt-0 mb-3">' + SL.escapar(d.lectura) + "</p>";

      if (d.entregas.length) {
        html += '<table class="table table-sm sl-tabla mb-0"><tbody>';
        d.entregas.forEach(function (e) {
          const alto = e.probabilidad_retraso >= UMBRAL_ALTO;
          html += "<tr><td>" + SL.escapar(e.folio_entrega) + "</td><td>" +
            SL.escapar(e.nombre_cliente || "") + '</td><td class="sl-num ' +
            (alto ? "text-danger fw-semibold" : "") + '">' +
            Math.round(e.probabilidad_retraso * 100) + "%</td></tr>";
        });
        html += "</tbody></table>";
      }
      zona.innerHTML = "<h6><i class='bi bi-cpu'></i> Entregas en riesgo</h6>" + html;
    } catch (error) {
      zona.querySelector(".sl-cargando").textContent = error.message;
    }
  }

  function pastilla(texto, valor, clase) {
    return '<span class="sl-pastilla sl-pastilla-' + clase + '">' +
           SL.escapar(texto) + ": " + SL.entero(valor) + "</span>";
  }

  if (document.getElementById("g-rutas")) { rutas(); causas(); }
  if (document.getElementById("t-mantenimiento")) { mantenimiento(); riesgo(); }
})();
