// Consola de simulación: plano del parking y control de las instancias SITL.
//
// Sin framework a propósito. Es una herramienta de banco de un solo fichero, y
// el portal ya arrastra su propio admin.js; meter aquí una dependencia más
// obligaría a mantener dos cadenas de construcción para el mismo TFG.

const CAMPOS = ["n_drones", "pad_layout", "pad_cols", "pad_spacing_m",
                "pad_heading_deg", "pad_separation_m", "vertiport_capacity",
                "takeoff_gap_s"];

// Un color por turno de despegue. Los mismos que declara console.css.
const COLORES_TANDA = ["#2b6cb0", "#b7791f", "#2f855a", "#6b46c1",
                       "#b83280", "#4a5568"];

const $ = (id) => document.getElementById(id);
const colorTanda = (t) => COLORES_TANDA[t % COLORES_TANDA.length];

// Plaza sobre la que está el foco, o null. Con muchos pads el dibujo se
// satura de líneas; enfocar una plaza deja ver de quién depende ESA.
let foco = null;
let ultimoParking = null;

// El navegador recarga console.js del disco, pero el Python sigue en memoria:
// tras tocar sim.py, la página nueva habla con una API vieja y revienta con un
// «Cannot read properties of undefined» que no dice nada. Se comprueba que la
// respuesta trae lo que esta versión necesita y se pide el reinicio.
function compatible(parking) {
  if (parking && Array.isArray(parking.tandas)) return true;
  $("veredicto").hidden = false;
  $("veredicto").innerHTML =
    `<strong>La consola está sirviendo una versión antigua.</strong>
     <span class="detalle">El proceso de Python se quedó con el código de
     antes. Ciérralo con Ctrl+C y vuelve a lanzar
     <code>python -m simtools</code>.</span>`;
  return false;
}

function formacion() {
  const datos = {};
  for (const campo of CAMPOS) {
    const elemento = $(campo);
    datos[campo] = elemento.type === "number" ? Number(elemento.value) : elemento.value;
  }
  datos.categorias = categoriasElegidas();
  return datos;
}

// ── Flota ──────────────────────────────────────────────────────────────
//
// Un desplegable por dron. Se reconstruye al cambiar el número de drones y
// conserva lo ya elegido: perder las categorías cada vez que se toca el
// contador obligaría a repasarlas todas para mover una plaza.
let categorias = [];          // catálogo, lo manda el servidor
let seleccion = [];           // una categoría por dron
let flotaIds = [];            // drones que existen en la base de datos, en orden

function categoriasElegidas() {
  return seleccion.slice(0, Number($("n_drones").value) || 0);
}

// El quinto dron en adelante entra como ligero, no rotando el catálogo:
// ampliar la flota no debería meter pesados sin que nadie lo pida.
const PREDETERMINADAS = ["ligero", "ligero", "medio", "pesado"];
const porDefecto = (indice) => PREDETERMINADAS[indice] || "ligero";

function pintarFlota() {
  const total = Number($("n_drones").value) || 0;
  const caja = $("flota");
  caja.innerHTML = "";
  if (!categorias.length) return;

  for (let k = 0; k < total; k++) {
    if (!seleccion[k]) seleccion[k] = porDefecto(k);
    const fila = document.createElement("div");
    fila.className = "dron-fila";
    const opciones = categorias
      .map((c) => `<option value="${c}"${c === seleccion[k] ? " selected" : ""}>
                     ${c[0].toUpperCase()}${c.slice(1)}</option>`)
      .join("");
    // Los que ya existen llevan su nombre real y un botón para quitarlos; los
    // que se añaden al subir el contador no existen hasta «Aplicar».
    const id = flotaIds[k];
    const quitar = id && flotaIds.length > 1
      ? `<button class="quitar secundario" data-id="${id}"
           title="Quitar ${id} y parar su instancia">✕</button>`
      : "";
    fila.innerHTML = `
      <span class="dron-nombre">
        <span class="dron-punto" style="background:${colorDe(k)}"></span>
        ${id || `Dron-${k + 1}`}${id ? "" : ' <span class="nuevo">nuevo</span>'}
      </span>
      <select data-dron="${k}">${opciones}</select>${quitar}`;
    caja.appendChild(fila);
  }

  for (const boton of caja.querySelectorAll("button.quitar")) {
    boton.addEventListener("click", () => conBoton(boton, "…", async () => {
      const id = boton.dataset.id;
      await pedir(`/api/flota/${encodeURIComponent(id)}`, { method: "DELETE" });
      mensaje(`${id} quitado de la flota y su instancia parada. Los demás siguen igual.`);
      await refrescar();
    }));
  }

  for (const select of caja.querySelectorAll("select")) {
    select.addEventListener("change", (evento) => {
      seleccion[Number(evento.target.dataset.dron)] = evento.target.value;
    });
  }
}

// Color de la plaza de este dron en el plano, si ya está dibujado.
function colorDe(indice) {
  if (!ultimoParking || !ultimoParking.tandas
      || ultimoParking.tandas[indice] === undefined) {
    return "#c8c8c8";
  }
  return colorTanda(ultimoParking.tandas[indice]);
}

// La consola funciona suelta (python -m simtools, sin login, en 127.0.0.1) y
// dentro del portal en /simulacion/, donde sus rutas cuelgan de
// /api/admin/sim y van con el token del administrador.
const EN_PORTAL = location.pathname.startsWith("/simulacion");
const TOKEN = EN_PORTAL ? (() => { try { return localStorage.getItem("admin_token"); } catch (e) { return null; } })() : null;
if (EN_PORTAL) {
  if (!TOKEN) location.href = "/admin.html";
  document.getElementById("volver-panel").hidden = false;
}

async function pedir(ruta, opciones = {}) {
  if (EN_PORTAL) {
    ruta = ruta.replace(/^\/api\//, "/api/admin/sim/");
    opciones.headers = { ...(opciones.headers || {}), Authorization: `Bearer ${TOKEN}` };
  }
  const respuesta = await fetch(ruta, opciones);
  if (EN_PORTAL && respuesta.status === 401) {
    location.href = "/admin.html";
    throw new Error("Sesión caducada");
  }
  if (!respuesta.ok) {
    const detalle = await respuesta.json().catch(() => ({}));
    throw new Error(detalle.detail || detalle.error || `${respuesta.status} en ${ruta}`);
  }
  return respuesta.json();
}

const post = (ruta, cuerpo) => pedir(ruta, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

let ocultarMensaje = null;
function mensaje(texto, esError = false) {
  const caja = $("mensaje");
  caja.textContent = texto;
  caja.classList.toggle("error", esError);
  caja.classList.add("visible");
  clearTimeout(ocultarMensaje);
  ocultarMensaje = setTimeout(() => caja.classList.remove("visible"), 5000);
}

// ── Plano del parking ──────────────────────────────────────────────────
//
// El dibujo tiene que responder a una sola pregunta: ¿quién puede despegar a
// la vez que quién? Por eso cada plaza lleva su BURBUJA —un círculo de radio
// igual a la mitad de la separación exigida— y las burbujas que se tocan son,
// literalmente, los drones que se estorban. Ese solape es la restricción; la
// línea roja solo lo subraya y le pone el número encima.
//
// Se dibuja con el radio a la mitad a propósito: así "burbujas que se tocan"
// equivale exactamente a "centros más cerca que la separación exigida", que
// es la condición que aplica el gestor de espacio aéreo.
function dibujar(parking) {
  const svg = $("plano");
  svg.innerHTML = "";
  if (!compatible(parking)) return;

  ultimoParking = parking;
  const pads = parking.pads;
  if (!pads.length) return;

  const separacion = parking.separacion_exigida_m || 0;
  const margen = Math.max(separacion / 2, 5) + 4;
  const extremo = Math.max(
    ...pads.flatMap((p) => [Math.abs(p.x_m), Math.abs(p.y_m)]), 1) + margen;
  const lado = extremo * 2.3;
  svg.setAttribute("viewBox", `${-lado / 2} ${-lado / 2} ${lado} ${lado}`);

  const ns = "http://www.w3.org/2000/svg";
  const crear = (etiqueta, atributos, clase) => {
    const nodo = document.createElementNS(ns, etiqueta);
    for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, v);
    if (clase) nodo.setAttribute("class", clase);
    svg.appendChild(nodo);
    return nodo;
  };

  // El eje y del SVG crece hacia abajo y el norte hacia arriba: se invierte.
  const py = (pad) => -pad.y_m;
  const paso = lado > 120 ? 25 : 10;
  const apagado = (indice) => (foco !== null && !relacionada(indice) ? " apagada" : "");

  // Retícula, para que las distancias se puedan estimar a ojo.
  for (let d = -Math.ceil(lado / (2 * paso)) * paso; d <= lado / 2; d += paso) {
    crear("line", { x1: d, y1: -lado / 2, x2: d, y2: lado / 2 }, "rejilla-fondo");
    crear("line", { x1: -lado / 2, y1: d, x2: lado / 2, y2: d }, "rejilla-fondo");
  }
  crear("line", { x1: 0, y1: -lado / 2, x2: 0, y2: lado / 2 }, "eje");
  crear("line", { x1: -lado / 2, y1: 0, x2: lado / 2, y2: 0 }, "eje");

  // Centro del parking: el punto que marca el mapa del portal. Va sin
  // etiqueta porque en una fila cae justo entre dos plazas y las tapaba.
  const cruz = lado / 70;
  crear("line", { x1: -cruz, y1: 0, x2: cruz, y2: 0 }, "centro");
  crear("line", { x1: 0, y1: -cruz, x2: 0, y2: cruz }, "centro");

  // Burbujas primero, para que las plazas queden por encima.
  if (separacion > 0) {
    for (const pad of pads) {
      crear("circle", {
        cx: pad.x_m, cy: py(pad), r: separacion / 2,
        fill: colorTanda(parking.tandas[pad.index]),
        stroke: colorTanda(parking.tandas[pad.index]),
      }, `burbuja${apagado(pad.index)}`);
    }
  }

  // Las líneas van sin rótulo de distancia. Cada rótulo se colocaba en el
  // punto medio de SU par, así que en una fila el del par 1-4 caía en el
  // centro del dibujo —entre las plazas 2 y 3— y se leía como si midiera ese
  // hueco. El número era correcto y la lectura, falsa.
  //
  // La distancia que importa para decidir ya está en el veredicto: la de la
  // pareja más apretada, que es la que fija los turnos.
  for (const conflicto of parking.conflictos) {
    const a = pads[conflicto.a];
    const b = pads[conflicto.b];
    const visible = foco === null || foco === conflicto.a || foco === conflicto.b;
    crear("line", { x1: a.x_m, y1: py(a), x2: b.x_m, y2: py(b) },
          `conflicto${visible ? "" : " apagada"}`);
  }

  const talla = Math.max(lado / 24, 2.5);
  for (const pad of pads) {
    const cuadro = crear("rect", {
      x: pad.x_m - talla / 2, y: py(pad) - talla / 2,
      width: talla, height: talla,
      fill: colorTanda(parking.tandas[pad.index]),
    }, `pad${apagado(pad.index)}`);
    cuadro.dataset.index = pad.index;
    crear("text", {
      x: pad.x_m, y: py(pad) + talla * 0.2, "font-size": talla * 0.6,
    }, `pad-texto${apagado(pad.index)}`).textContent = pad.etiqueta || pad.index + 1;
  }

  dibujarEscala(crear, lado, paso);
}

// ¿Tiene esta plaza algo que ver con la enfocada?
function relacionada(indice) {
  if (foco === indice) return true;
  return ultimoParking.conflictos.some(
    (c) => (c.a === foco && c.b === indice) || (c.b === foco && c.a === indice));
}

function dibujarEscala(crear, lado, paso) {
  const y = lado / 2 - lado / 22;
  const x0 = -lado / 2 + lado / 22;
  crear("line", { x1: x0, y1: y, x2: x0 + paso, y2: y }, "escala");
  crear("line", { x1: x0, y1: y - lado / 90, x2: x0, y2: y + lado / 90 }, "escala");
  crear("line", { x1: x0 + paso, y1: y - lado / 90, x2: x0 + paso, y2: y + lado / 90 },
        "escala");
  crear("text", { x: x0 + paso / 2, y: y - lado / 60, "font-size": lado / 55 },
        "escala-texto").textContent = `${paso} m`;
}

// ── Lectura en palabras ────────────────────────────────────────────────
function leer(parking) {
  const caja = $("veredicto");
  if (!compatible(parking)) return;

  const total = parking.pads.length;
  const a_la_vez = parking.simultaneos;
  const turnos = parking.n_tandas;
  const exigida = parking.separacion_exigida_m;

  caja.hidden = false;

  let titular;
  let detalle;

  if (!exigida) {
    titular = "Un dron cada vez.";
    detalle = "La separación exigida está a 0, así que el parking se comporta " +
      "como un cerrojo único: la flota despega y aterriza de una en una, " +
      "disten lo que disten las plazas. Súbela para permitir maniobras en paralelo.";
  } else if (turnos === 1) {
    titular = `Los ${total} drones pueden maniobrar a la vez.`;
    detalle = `Ninguna pareja de plazas está a menos de ${exigida} m, así que ` +
      "no hay conflictos: la flota entera sale de una tacada.";
  } else {
    titular = `${a_la_vez} a la vez · ${turnos} turnos para sacar los ${total}.`;
    detalle = `La plaza más apretada tiene otra a ${parking.separacion_minima_m} m, ` +
      `por debajo de los ${exigida} m exigidos. Las plazas del mismo color ` +
      "despegan juntas; cada color es un turno.";
  }

  const chips = [];
  for (let t = 0; t < turnos; t++) {
    const cuantos = parking.tandas.filter((x) => x === t).length;
    chips.push(
      `<span class="tanda-chip">
         <span class="tanda-punto" style="background:${colorTanda(t)}"></span>
         Turno ${t + 1} · ${cuantos} ${cuantos === 1 ? "dron" : "drones"}
       </span>`);
  }

  // Con la separación a 0 cada dron es su propio turno, así que la tira de
  // colores serían N pastillas de un dron cada una: ruido que repite lo que
  // ya dice el texto.
  const conTira = exigida > 0 && turnos > 1;
  caja.innerHTML =
    `<strong>${titular}</strong>
     <span class="detalle">${detalle}</span>
     ${conTira ? `<div class="tandas-tira">${chips.join("")}</div>` : ""}`;
}

let pendiente = null;
async function previsualizar() {
  clearTimeout(pendiente);
  pendiente = setTimeout(async () => {
    try {
      const datos = await post("/api/parking/previsualizar", formacion());
      foco = null;
      dibujar(datos.parking);
      leer(datos.parking);
      pintarFlota();   // los colores de la flota siguen a los del plano
    } catch (error) {
      mensaje(error.message, true);
    }
  }, 120);
}

// ── Instancias ─────────────────────────────────────────────────────────
function pintarSitl(sitl) {
  // El selector refleja la aceleración con la que corren ahora las instancias.
  const acel = String(Number(sitl.speedup));
  if ([...$("speedup").options].some((o) => o.value === acel)) $("speedup").value = acel;
  const cuerpo = $("instancias").querySelector("tbody");
  cuerpo.innerHTML = "";
  for (const instancia of sitl.instancias) {
    let estado = "parada";
    let clase = "parada";
    if (instancia.panic) { estado = "PANIC"; clase = "mal"; }
    else if (instancia.vivo && instancia.escuchando) { estado = "en marcha"; clase = "ok"; }
    else if (instancia.vivo) { estado = "sin puerto"; clase = "mal"; }

    const fila = document.createElement("tr");
    fila.innerHTML = `
      <td>${instancia.drone_id}</td>
      <td>${instancia.sysid}</td>
      <td>${instancia.connection}</td>
      <td>${instancia.pid ?? "—"}</td>
      <td><span class="pastilla ${clase}">${estado}</span></td>`;
    cuerpo.appendChild(fila);
  }

  const problemas = [];
  if (!sitl.binario_ok) problemas.push(`No se encuentra el binario: ${sitl.binario}`);
  if (!sitl.defaults_ok) {
    problemas.push(`El fichero de parámetros no es válido (${sitl.defaults}). ` +
                   "Sin él las instancias arrancan sin FRAME_CLASS y no arman.");
  }
  const caja = $("entorno");
  caja.classList.toggle("mal", problemas.length > 0);
  caja.textContent = problemas.length
    ? problemas.join(" ")
    : `Binario y parámetros correctos. Aceleración actual ×${sitl.speedup}.`;
}

async function refrescar() {
  try {
    const datos = await pedir("/api/estado");
    if (datos.max_drones) $("n_drones").max = datos.max_drones;
    $("n_drones").value = datos.drones.length || 1;
    flotaIds = datos.drones.map((d) => d.drone_id);
    for (const campo of CAMPOS.slice(1)) {
      if (datos.escenario[campo] !== undefined) $(campo).value = datos.escenario[campo];
    }
    categorias = datos.categorias || [];
    seleccion = datos.drones.map((d) => d.category);
    foco = null;
    dibujar(datos.parking);
    leer(datos.parking);
    pintarFlota();
    pintarSitl(datos.sitl);
    pintarPresets(datos.presets || []);
    ajustarCampos();
  } catch (error) {
    mensaje(error.message, true);
  }
}

// ── Escenarios de pedidos ──────────────────────────────────────────────
function pintarPresets(presets) {
  const select = $("preset");
  if (select.options.length === presets.length) return;
  select.innerHTML = presets
    .map((p) => `<option value="${p.nombre}">${p.nombre} · ${p.n_pedidos} pedidos</option>`)
    .join("");
  select.dataset.descripciones = JSON.stringify(
    Object.fromEntries(presets.map((p) => [p.nombre, p.descripcion])));
  describirPreset();
}

function describirPreset() {
  const descripciones = JSON.parse($("preset").dataset.descripciones || "{}");
  $("preset-descripcion").textContent = descripciones[$("preset").value] || "";
}

// «Columnas» solo significa algo en la rejilla; dejarlo activo invita a
// moverlo y a no ver ningún efecto.
function ajustarCampos() {
  $("pad_cols").disabled = $("pad_layout").value !== "rejilla";
}

async function conBoton(boton, texto, accion) {
  const original = boton.textContent;
  boton.disabled = true;
  boton.textContent = texto;
  try {
    await accion();
  } catch (error) {
    mensaje(error.message, true);
  } finally {
    boton.textContent = original;
    boton.disabled = false;
  }
}

// ── Enganches ──────────────────────────────────────────────────────────
for (const campo of CAMPOS) {
  $(campo).addEventListener("input", () => {
    ajustarCampos();
    pintarFlota();      // al cambiar el número de drones, la lista lo sigue
    previsualizar();
  });
  $(campo).addEventListener("change", () => { ajustarCampos(); previsualizar(); });
}

$("plano").addEventListener("click", (evento) => {
  const indice = evento.target.dataset && evento.target.dataset.index;
  foco = indice === undefined ? null : Number(indice);
  if (ultimoParking) dibujar(ultimoParking);
});

$("aplicar").addEventListener("click", () => conBoton($("aplicar"), "Aplicando…",
  async () => {
    const datos = await post("/api/parking/aplicar", formacion());
    mensaje(`Formación aplicada: ${datos.drones.length} drones recolocados.`);
    await refrescar();
  }));

$("lanzar").addEventListener("click", () => conBoton($("lanzar"), "Arrancando…",
  async () => {
    const datos = await post("/api/sitl/lanzar", { speedup: Number($("speedup").value) });
    mensaje(datos.ok ? "Instancias en marcha." : "Alguna instancia no arrancó.", !datos.ok);
    await refrescar();
  }));

$("parar").addEventListener("click", () => conBoton($("parar"), "Parando…",
  async () => {
    await post("/api/sitl/parar", {});
    mensaje("Instancias detenidas.");
    await refrescar();
  }));

$("refrescar").addEventListener("click", () => conBoton($("refrescar"), "…", refrescar));

$("preset").addEventListener("change", describirPreset);

$("sembrar").addEventListener("click", () => conBoton($("sembrar"), "Sembrando…",
  async () => {
    const semilla = $("semilla").value.trim();
    const datos = await post("/api/bd/sembrar", {
      preset: $("preset").value,
      semilla: semilla === "" ? null : Number(semilla),
      pedidos: $("n_pedidos").value.trim() === "" ? null : Number($("n_pedidos").value),
    });
    mensaje(`${datos.creados} pedido(s) sembrados. Arranca los repartos en el portal.`);
  }));

$("limpiar").addEventListener("click", () => conBoton($("limpiar"), "Vaciando…",
  async () => {
    const datos = await post("/api/bd/limpiar", {
      pedidos: $("borrar_pedidos").checked,
      clientes: $("borrar_clientes").checked,
    });
    const detalle = Object.entries(datos.borrados)
      .map(([k, v]) => `${v} ${k}`).join(", ") || "nada";
    mensaje(`Borrado: ${detalle}.`);
  }));

refrescar();
