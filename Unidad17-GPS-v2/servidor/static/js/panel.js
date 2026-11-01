/* Panel Unidad 17 · interacciones del panel */
(function () {
  "use strict";

  const $ = (selector, contexto) => (contexto || document).querySelector(selector);
  const $$ = (selector, contexto) => Array.prototype.slice.call((contexto || document).querySelectorAll(selector));

  /* ------------------------------------------------------------------ *
   * Menú lateral en pantallas pequeñas
   * ------------------------------------------------------------------ */
  function iniciarMenu() {
    const boton = $("#btnMenu");
    const velo = $("#fondoMenu");
    if (boton) {
      boton.addEventListener("click", () => document.body.classList.toggle("menu-abierto"));
    }
    if (velo) {
      velo.addEventListener("click", () => document.body.classList.remove("menu-abierto"));
    }
    $$(".nav-item").forEach((enlace) => {
      enlace.addEventListener("click", () => document.body.classList.remove("menu-abierto"));
    });
  }

  /* ------------------------------------------------------------------ *
   * Horas relativas
   * ------------------------------------------------------------------ */
  function relativo(texto) {
    if (!texto) return "—";
    const fecha = new Date(texto);
    if (isNaN(fecha.getTime())) return "—";
    let segundos = Math.floor((Date.now() - fecha.getTime()) / 1000);
    if (segundos < 0) segundos = 0;
    if (segundos < 60) return "ahora";
    if (segundos < 3600) return "hace " + Math.floor(segundos / 60) + " min";
    if (segundos < 86400) return "hace " + Math.floor(segundos / 3600) + " h";
    if (segundos < 2592000) return "hace " + Math.floor(segundos / 86400) + " d";
    return "hace " + Math.floor(segundos / 2592000) + " meses";
  }

  function pintarTiempos() {
    $$("[data-utc]").forEach((elemento) => {
      const texto = elemento.dataset.utc;
      if (!texto) return;
      elemento.textContent = relativo(texto);
      const fecha = new Date(texto);
      if (!isNaN(fecha.getTime())) {
        elemento.title = fecha.toLocaleString();
      }
    });
  }

  /* ------------------------------------------------------------------ *
   * Buscador de la tabla
   * ------------------------------------------------------------------ */
  function normalizar(texto) {
    return (texto || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function iniciarBuscador() {
    const entrada = $("#buscador");
    const tabla = $("#tablaEquipos");
    if (!entrada || !tabla) return;

    const filas = $$("tr[data-equipo]", tabla);
    const contador = $("#contador");
    const filaVacia = $("#filaVacia");

    filas.forEach((fila) => {
      fila.dataset.indice = normalizar(fila.dataset.busqueda || fila.textContent);
    });

    entrada.addEventListener("input", () => {
      const consulta = normalizar(entrada.value);
      let visibles = 0;
      filas.forEach((fila) => {
        const coincide = !consulta || fila.dataset.indice.indexOf(consulta) !== -1;
        fila.hidden = !coincide;
        if (coincide) visibles += 1;
      });
      if (contador) contador.textContent = String(visibles);
      if (filaVacia) filaVacia.hidden = visibles !== 0;
    });
  }

  /* ------------------------------------------------------------------ *
   * Botones de copiar
   * ------------------------------------------------------------------ */
  function copiarTexto(texto) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texto);
    }
    return new Promise((resolve, reject) => {
      try {
        const area = document.createElement("textarea");
        area.value = texto;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        const correcto = document.execCommand("copy");
        document.body.removeChild(area);
        correcto ? resolve() : reject(new Error("copia no disponible"));
      } catch (error) {
        reject(error);
      }
    });
  }

  function iniciarCopiar() {
    $$("[data-copiar]").forEach((boton) => {
      const original = boton.innerHTML;
      boton.addEventListener("click", () => {
        copiarTexto(boton.dataset.copiar || "")
          .then(() => {
            boton.textContent = "Copiado";
            boton.classList.add("copiado");
            window.setTimeout(() => {
              boton.innerHTML = original;
              boton.classList.remove("copiado");
            }, 1600);
          })
          .catch(() => {
            boton.textContent = "No se pudo copiar";
            window.setTimeout(() => { boton.innerHTML = original; }, 1800);
          });
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Mostrar / ocultar contraseña
   * ------------------------------------------------------------------ */
  function iniciarOjo() {
    const boton = $("#verClave");
    const campo = $("#clave");
    if (!boton || !campo) return;
    boton.addEventListener("click", () => {
      const visible = campo.type === "text";
      campo.type = visible ? "password" : "text";
      boton.setAttribute("aria-pressed", visible ? "false" : "true");
      const uso = boton.querySelector("use");
      if (uso) uso.setAttribute("href", visible ? "#i-ojo" : "#i-ojo-off");
      campo.focus();
    });
  }

  /* ------------------------------------------------------------------ *
   * Refresco manual y automático
   * ------------------------------------------------------------------ */
  function iniciarRefresco() {
    const boton = $("#btnRefrescar");
    if (boton) {
      boton.addEventListener("click", () => window.location.reload());
    }

    const tabla = $("#tablaEquipos");
    if (!tabla) return;

    window.setInterval(async () => {
      try {
        const respuesta = await fetch("/api/equipos", {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!respuesta.ok) return;
        const datos = await respuesta.json();
        if (!datos || !Array.isArray(datos.equipos)) return;

        const filas = $$("tr[data-equipo]", tabla);
        if (datos.equipos.length !== filas.length) {
          window.location.reload();
          return;
        }

        datos.equipos.forEach((equipo) => {
          const fila = tabla.querySelector('tr[data-id="' + equipo.id + '"]');
          if (!fila) return;
          const punto = fila.querySelector(".punto-estado");
          if (punto) {
            punto.classList.toggle("en-linea", !!equipo.en_linea);
            punto.classList.toggle("desconectado", !equipo.en_linea);
          }
          const estado = fila.querySelector("[data-estado-texto]");
          if (estado) estado.textContent = equipo.en_linea ? "En línea" : "Sin conexión";
          const tiempo = fila.querySelector("[data-utc]");
          if (tiempo && equipo.ultima_conexion) {
            tiempo.dataset.utc = equipo.ultima_conexion;
            tiempo.textContent = relativo(equipo.ultima_conexion);
          }
        });

        const total = $("#statEnLinea");
        if (total && datos.resumen) total.textContent = String(datos.resumen.en_linea);
      } catch (error) {
        /* silencioso: el panel sigue mostrando los últimos datos */
      }
    }, 45000);
  }

  /* ------------------------------------------------------------------ *
   * Mapas (Leaflet cargado en local)
   * ------------------------------------------------------------------ */
  function elementosPopup(equipo) {
    const caja = document.createElement("div");

    const titulo = document.createElement("strong");
    titulo.textContent = equipo.hostname;
    caja.appendChild(titulo);

    const lugar = document.createElement("div");
    lugar.textContent = [equipo.ciudad, equipo.pais].filter(Boolean).join(", ") || "Sin ciudad";
    caja.appendChild(lugar);

    const meta = document.createElement("small");
    meta.style.display = "block";
    meta.style.color = "#9a9cb8";
    meta.textContent = (equipo.fuente === "gps" ? "GPS de Windows" : "Por IP") +
      (equipo.ultima_texto ? " · " + equipo.ultima_texto : "");
    caja.appendChild(meta);

    const enlace = document.createElement("a");
    enlace.href = "/equipo/" + equipo.id;
    enlace.textContent = "Ver detalle";
    enlace.style.display = "inline-block";
    enlace.style.marginTop = "6px";
    caja.appendChild(enlace);

    return caja;
  }

  function mostrarErrorMapa(mensaje) {
    const caja = $("#mapa-error");
    if (!caja) return;
    caja.hidden = false;
    const texto = $("#mapa-error-texto");
    if (texto) texto.textContent = mensaje;
  }

  function iniciarMapa() {
    const contenedor = $("#mapa");
    if (!contenedor) return;

    let datos = [];

    const fuente = $("#datos-mapa");
    if (fuente) {
      try {
        datos = JSON.parse(fuente.textContent || "[]");
      } catch (error) {
        datos = [];
      }
    }

    const puntos = datos.filter(
      (equipo) => typeof equipo.lat === "number" && typeof equipo.lon === "number"
    );

    const externo = $("#enlace-mapa-externo");
    if (externo && puntos.length) {
      const primero = puntos[0];
      externo.href =
        "https://www.openstreetmap.org/?mlat=" + primero.lat + "&mlon=" + primero.lon +
        "#map=15/" + primero.lat + "/" + primero.lon;
      const ayuda = $("#mapa-error-enlace");
      if (ayuda) ayuda.hidden = false;
    }

    if (!puntos.length) {
      contenedor.hidden = true;
      mostrarErrorMapa("Ningún equipo ha reportado coordenadas todavía.");
      return;
    }
    if (!window.L) {
      contenedor.hidden = true;
      mostrarErrorMapa("No se pudo cargar el mapa interactivo (falta Leaflet).");
      return;
    }

    const mapa = L.map(contenedor, {
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });

    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        maxNativeZoom: 16,
        maxZoom: 19,
        attribution:
          'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
      }
    ).addTo(mapa);

    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
      { maxNativeZoom: 16, maxZoom: 19 }
    ).addTo(mapa);

    const marcadores = {};

    if (contenedor.dataset.vista === "global" && mapa.zoomControl) {
      mapa.zoomControl.setPosition("bottomleft");
    }

    puntos.forEach((equipo) => {
      const icono = L.divIcon({
        className: "marcador " + (equipo.en_linea ? "" : "marcador-offline"),
        html: "<span></span>",
        iconSize: [16, 16],
        iconAnchor: [8, 8],
        popupAnchor: [0, -10],
      });

      const marcador = L.marker([equipo.lat, equipo.lon], { icon: icono }).addTo(mapa);
      marcador.bindPopup(elementosPopup(equipo));
      marcadores[String(equipo.id)] = marcador;
    });

    if (puntos.length === 1) {
      mapa.setView([puntos[0].lat, puntos[0].lon], 13);
    } else {
      const limites = L.latLngBounds(puntos.map((equipo) => [equipo.lat, equipo.lon]));
      mapa.fitBounds(limites, { padding: [50, 50], maxZoom: 12 });
    }

    $$("[data-ir-a]").forEach((boton) => {
      boton.addEventListener("click", () => {
        const marcador = marcadores[boton.dataset.irA];
        if (!marcador) return;
        mapa.flyTo(marcador.getLatLng(), 14, { duration: 0.8 });
        marcador.openPopup();
      });
    });

    window.setTimeout(() => mapa.invalidateSize(), 220);
    window.setTimeout(() => mapa.invalidateSize(), 900);
    window.addEventListener("resize", () => mapa.invalidateSize());
    window.addEventListener("load", () => mapa.invalidateSize());
  }

  /* ------------------------------------------------------------------ *
   * Arranque
   * ------------------------------------------------------------------ */
  function iniciar() {
    pintarTiempos();
    window.setInterval(pintarTiempos, 30000);

    iniciarMenu();
    iniciarBuscador();
    iniciarCopiar();
    iniciarOjo();
    iniciarRefresco();
    iniciarMapa();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
