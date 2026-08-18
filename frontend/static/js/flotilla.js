/* =========================================================================
   SIG-LOG — desempeño de la flotilla

   Cada bloque de esta pantalla existe por una pregunta de negocio concreta.
   Ninguna cifra se calcula aquí: todo viene de /analitica/vehiculos, que a
   su vez lee `dim_vehiculo` y `hecho_entrega`.
   ========================================================================= */

(function () {
  "use strict";

  const UMBRAL = window.SIGLOG.umbral;
  const PERIODO = JSON.parse(
    document.getElementById("datos-periodo").textContent || "{}");

  // Cada criterio sabe cómo rotularse. Un eje sin unidad no se interpreta.
  const CRITERIOS = {
    costo: {
      campo: "costo_total", eje: "Costo de operación (MXN)",
      titulo: "Costo de operación por vehículo",
      formato: SL.dinero, color: SL.COLORES.alerta
    },
    combustible: {
      campo: "litros", eje: "Combustible consumido (litros)",
      titulo: "Combustible consumido por vehículo",
      formato: function (v) { return SL.numero(v, 0) + " l"; },
      color: SL.COLORES.aviso
    },
    entregas: {
      campo: "entregas", eje: "Entregas realizadas",
      titulo: "Entregas realizadas por vehículo",
      formato: SL.entero, color: SL.COLORES.principal
    },
    retraso: {
      campo: "retraso_medio_min", eje: "Retraso medio (minutos)",
      titulo: "Retraso medio por vehículo",
      formato: function (v) { return SL.numero(v, 1) + " min"; },
      color: SL.COLORES.alerta
    },
    rendimiento: {
      campo: "rendimiento_real_km_l", eje: "Rendimiento real (km/l)",
      titulo: "Rendimiento real por vehículo",
      formato: function (v) { return SL.numero(v, 2) + " km/l"; },
      color: SL.COLORES.bien
    },
    uso: {
      campo: "km_recorridos", eje: "Distancia recorrida (km)",
      titulo: "Kilometraje por vehículo",
      formato: function (v) { return SL.numero(v, 0) + " km"; },
      color: SL.COLORES.principal
    }
  };

  let grafica = null;
  let dispersion = null;
  let flotillaCompleta = [];

  /** Etiqueta legible de una unidad. El identificador interno no se enseña. */
  function etiqueta(v) {
    return v.codigo_vehiculo;
  }
  function etiquetaLarga(v) {
    return v.codigo_vehiculo + " · " + v.descripcion +
           (v.placa ? " (" + v.placa + ")" : "");
  }

  // ======================================================================
  // GRÁFICA PRINCIPAL
  // ======================================================================
  async function cargar() {
    const criterio = document.getElementById("criterio").value;
    const top = document.getElementById("cuantos").value;
    const cfg = CRITERIOS[criterio];

    try {
      const r = await SL.api("/analitica/vehiculos?orden=" + criterio +
                             "&top=" + top);
      const d = r.datos;
      const filas = d.vehiculos;
      document.getElementById("l-flotilla").textContent = d.lectura;

      if (grafica) grafica.destroy();
      grafica = new Chart(document.getElementById("g-flotilla"), {
        type: "bar",
        data: {
          labels: filas.map(etiqueta),
          datasets: [{
            label: cfg.eje,
            data: filas.map(function (v) { return v[cfg.campo]; }),
            backgroundColor: filas.map(function (v) {
              // El rojo señala lo que exige intervención, no el primer puesto
              if (criterio === "retraso") {
                return v.retraso_medio_min > UMBRAL
                  ? SL.COLORES.alerta : SL.COLORES.principal;
              }
              if (criterio === "rendimiento") {
                return (v.desviacion_rendimiento_pct || 0) < 0
                  ? SL.COLORES.alerta : SL.COLORES.bien;
              }
              return cfg.color;
            })
          }]
        },
        options: {
          plugins: {
            legend: {display: false},
            title: {
              display: true,
              text: [cfg.titulo, PERIODO.etiqueta || ""],
              font: {size: 13}, padding: {bottom: 12}
            },
            tooltip: {callbacks: {
              title: function (ctx) {
                return etiquetaLarga(filas[ctx[0].dataIndex]);
              },
              label: function (ctx) {
                return cfg.eje + ": " + cfg.formato(ctx.raw);
              },
              afterLabel: function (ctx) {
                const v = filas[ctx.dataIndex];
                return [
                  "Entregas: " + SL.entero(v.entregas),
                  "Costo total: " + SL.dinero(v.costo_total),
                  "Retraso medio: " + (v.retraso_medio_min === null
                    ? "—" : SL.numero(v.retraso_medio_min, 1) + " min")
                ];
              }
            }}
          },
          scales: {
            x: {title: {display: true, text: "Vehículo"}},
            y: {
              beginAtZero: criterio !== "rendimiento",
              title: {display: true, text: cfg.eje},
              ticks: {callback: function (v) {
                return criterio === "costo" ? SL.dinero(v) : SL.numero(v, 0);
              }}
            }
          }
        }
      });
    } catch (error) {
      document.getElementById("l-flotilla").textContent = error.message;
    }
  }

  // ======================================================================
  // COSTO FRENTE A TRABAJO
  // ======================================================================
  async function comparativa() {
    try {
      const r = await SL.api("/analitica/vehiculos?orden=costo&top=100");
      const d = r.datos;
      flotillaCompleta = d.vehiculos;
      pintarTabla(flotillaCompleta);

      const maxLitros = Math.max.apply(null,
        flotillaCompleta.map(function (v) { return v.litros; })) || 1;
      const costoMedio = d.totales.costo_medio_por_vehiculo;
      const entregasMedia = d.totales.entregas / (d.flotilla || 1);

      // Ineficientes = por encima del costo medio y por debajo de las
      // entregas medias. Es el cuadrante que interesa, no el ranking.
      const ineficientes = flotillaCompleta.filter(function (v) {
        return v.costo_total > costoMedio && v.entregas < entregasMedia;
      });

      if (dispersion) dispersion.destroy();
      dispersion = new Chart(document.getElementById("g-dispersión"), {
        type: "bubble",
        data: {
          datasets: [
            {
              label: "Cuesta más de lo que trabaja",
              data: ineficientes.map(function (v) {
                return {x: v.entregas, y: v.costo_total,
                        r: 4 + 12 * v.litros / maxLitros, v: v};
              }),
              backgroundColor: "rgba(214,39,40,.65)"
            },
            {
              label: "Dentro de lo esperado",
              data: flotillaCompleta.filter(function (v) {
                return ineficientes.indexOf(v) < 0;
              }).map(function (v) {
                return {x: v.entregas, y: v.costo_total,
                        r: 4 + 12 * v.litros / maxLitros, v: v};
              }),
              backgroundColor: "rgba(31,78,121,.55)"
            }
          ]
        },
        options: {
          plugins: {
            title: {
              display: true,
              text: ["Costo de operación frente a entregas realizadas",
                     PERIODO.etiqueta || ""],
              font: {size: 13}, padding: {bottom: 12}
            },
            legend: {position: "bottom", labels: {boxWidth: 10}},
            tooltip: {callbacks: {
              label: function (ctx) {
                const v = ctx.raw.v;
                return [
                  etiquetaLarga(v),
                  "Entregas: " + SL.entero(v.entregas),
                  "Costo: " + SL.dinero(v.costo_total),
                  "Costo por entrega: " + SL.dinero(v.costo_por_entrega),
                  "Combustible: " + SL.numero(v.litros, 0) + " litros"
                ];
              }
            }}
          },
          scales: {
            x: {title: {display: true, text: "Entregas realizadas"},
                beginAtZero: true},
            y: {title: {display: true, text: "Costo de operación (MXN)"},
                beginAtZero: true,
                ticks: {callback: function (v) { return SL.dinero(v); }}}
          }
        }
      });

      const zona = document.getElementById("l-dispersion");
      if (ineficientes.length) {
        const peor = ineficientes.slice().sort(function (a, b) {
          return b.costo_por_entrega - a.costo_por_entrega;
        })[0];
        zona.textContent =
          ineficientes.length + " de las " + d.flotilla + " unidades gastan " +
          "por encima de la media (" + SL.dinero(costoMedio) + ") y entregan " +
          "por debajo de ella (" + SL.numero(entregasMedia, 0) + " entregas). " +
          "La más desproporcionada es " + etiquetaLarga(peor) + ", con " +
          SL.dinero(peor.costo_por_entrega) + " por entrega frente a los " +
          SL.dinero(d.totales.costo_total / d.totales.entregas) +
          " del promedio de la flotilla.";
      } else {
        zona.textContent =
          "Ninguna unidad gasta por encima de la media entregando por debajo " +
          "de ella: el costo de la flotilla acompaña al trabajo que hace cada " +
          "vehículo.";
      }
    } catch (error) {
      document.getElementById("l-dispersion").textContent = error.message;
    }
  }

  // ======================================================================
  // TABLA
  // ======================================================================
  function pintarTabla(filas) {
    const cuerpo = document.getElementById("tabla-flotilla");
    cuerpo.innerHTML = "";
    filas.forEach(function (v) {
      const tarde = v.retraso_medio_min !== null && v.retraso_medio_min > UMBRAL;
      const flojo = (v.desviacion_rendimiento_pct || 0) < 0;
      const tr = document.createElement("tr");
      tr.innerHTML =
        "<td><strong>" + SL.escapar(v.codigo_vehiculo) + "</strong>" +
          "<br><small class='text-body-secondary'>" +
          SL.escapar(v.descripcion) + " · " + SL.escapar(v.placa) +
        "</small></td>" +
        "<td>" + SL.estado(v.estado_operativo) + "</td>" +
        '<td class="sl-num">' + SL.entero(v.viajes) + "</td>" +
        '<td class="sl-num">' + SL.entero(v.entregas) + "</td>" +
        '<td class="sl-num">' + SL.numero(v.km_recorridos, 0) + "</td>" +
        '<td class="sl-num">' + SL.dinero(v.costo_total) + "</td>" +
        '<td class="sl-num">' + SL.dinero(v.costo_por_entrega) + "</td>" +
        '<td class="sl-num">' + SL.numero(v.litros, 0) + "</td>" +
        '<td class="sl-num ' + (flojo ? "text-danger fw-semibold" : "") + '">' +
          SL.numero(v.rendimiento_real_km_l, 2) +
          "<br><small class='text-body-secondary'>ficha " +
          SL.numero(v.rendimiento_nominal_km_l, 2) + "</small></td>" +
        '<td class="sl-num ' + (tarde ? "text-danger fw-semibold" : "") + '">' +
          (v.retraso_medio_min === null ? "—" :
            SL.numero(v.retraso_medio_min, 1)) +
          "<br><small class='text-body-secondary'>" +
          (v.pct_retrasadas === null ? "" :
            SL.numero(v.pct_retrasadas, 0) + "% tarde") + "</small></td>" +
        '<td class="sl-num">' + SL.entero(v.mantenimientos) + "</td>";
      cuerpo.appendChild(tr);
    });
  }

  // ======================================================================
  // MANTENIMIENTO PENDIENTE
  // ======================================================================
  async function mantenimiento() {
    const zona = document.getElementById("mantenimiento");
    try {
      const r = await SL.api("/mantenimientos/pendientes");
      const d = r.datos;
      const filas = d.vencidos.concat(d.atrasados, d.proximos);

      if (!filas.length) {
        zona.className = "sl-vacio";
        zona.innerHTML = '<i class="bi bi-check-circle"></i>' +
          "<h3>Ninguna unidad pendiente</h3><p></p>";
        zona.querySelector("p").textContent = d.alerta;
        return;
      }

      const etiquetas = {vencidos: ["Vencido", "sl-pastilla-mal"],
                         atrasados: ["Atrasado", "sl-pastilla-alerta"],
                         proximos: ["Próximo", "sl-pastilla-info"]};
      let html = '<p class="sl-lectura mt-0 mb-3">' + SL.escapar(d.alerta) +
                 "</p>";
      html += '<div class="sl-tabla-envoltura"><table class="table table-sm ' +
              'sl-tabla mb-0"><thead><tr><th>Vehículo</th><th>Situación</th>' +
              "<th>Tipo</th><th>Fecha programada</th>" +
              '<th class="text-end">Días de diferencia</th>' +
              "<th>Estado de la unidad</th></tr></thead><tbody>";

      ["vencidos", "atrasados", "proximos"].forEach(function (grupo) {
        d[grupo].forEach(function (m) {
          const et = etiquetas[grupo];
          html += "<tr><td><strong>" + SL.escapar(m.codigo_vehiculo) +
            "</strong> <small class='text-body-secondary'>" +
            SL.escapar(m.placa || "") + "</small></td>" +
            '<td><span class="sl-pastilla ' + et[1] + '">' + et[0] +
            "</span></td>" +
            "<td>" + SL.estado(m.tipo) + "</td>" +
            "<td>" + SL.fecha(m.fecha_programada) + "</td>" +
            '<td class="sl-num">' + SL.entero(m.dias) + "</td>" +
            "<td>" + SL.estado(m.estado_operativo) + "</td></tr>";
        });
      });
      html += "</tbody></table></div>";

      zona.className = "";
      zona.innerHTML = html;
    } catch (error) {
      zona.textContent = error.message;
    }
  }

  document.getElementById("criterio").addEventListener("change", cargar);
  document.getElementById("cuantos").addEventListener("change", cargar);

  if (document.getElementById("g-flotilla")) {
    cargar();
    comparativa();
    mantenimiento();
  }
})();
