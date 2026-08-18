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

  let graficaRutas = null;

  async function rutas() {
    const top = document.getElementById("top").value;
    try {
      const r = await SL.api("/analitica/rutas-mas-usadas?top=" + top);
      const filas = r.datos.rutas;
      document.getElementById("l-rutas").textContent = r.datos.lectura;

      if (graficaRutas) graficaRutas.destroy();
      graficaRutas = new Chart(document.getElementById("g-rutas"), {
        type: "bar",
        data: {
          labels: filas.map(function (f) { return f.codigo_ruta; }),
          datasets: [{
            label: "Entregas",
            data: filas.map(function (f) { return f.entregas; }),
            backgroundColor: filas.map(function (f) {
              return f.sobre_umbral ? SL.COLORES.alerta : SL.COLORES.principal;
            })
          }]
        },
        options: {
          plugins: {
            legend: {display: false},
            tooltip: {callbacks: {afterLabel: function (ctx) {
              const f = filas[ctx.dataIndex];
              return ["Retraso medio: " + SL.numero(f.retraso_medio_min) + " min",
                      "Viajes: " + SL.entero(f.viajes)];
            }}}
          },
          scales: {y: {beginAtZero: true}}
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
        data: {
          labels: filas.map(function (f) { return f.causa.replace(/_/g, " "); }),
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
          plugins: {legend: {position: "bottom", labels: {boxWidth: 12}}},
          scales: {
            y: {beginAtZero: true, title: {display: true, text: "Entregas"}},
            y2: {position: "right", min: 0, max: 105, grid: {display: false},
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
  rutas(); causas(); saturacion();
})();
