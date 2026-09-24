# 🏀 Calendarios automáticos CB Arganda (FBM)

Dos calendarios **independientes** y siempre al día, para suscribirse desde Apple Calendar
(iPhone, iPad y Mac), Google Calendar u Outlook:

| Calendario | Categoría FBM | Archivo |
|---|---|---|
| CB Arganda · Cadete Masc. 1º año | `Cadete Masc. 1ºaño` | `cadete-masculino-1-ano.ics` |
| CB Arganda · Infantil Masc. 1º año | `Infantil Masc. 1ºaño` | `infantil-masculino-1-ano.ics` |

Coste: **0 €/mes**. **No necesita ninguna credencial personal**: ni Gmail, ni Google, ni tokens, ni secretos.

---

## 1. Arquitectura

```
FBM (fbm.es, web pública)
 ↓
GitHub Actions  ── lunes y viernes, comprobación de las 17:00 (Europe/Madrid)
 ↓
Python (fbmcal) ── pruebas automáticas → lectura FBM → contraste de fuentes
 ↓
Conciliación / verificación ── claves únicas, UID estables, sin duplicados
 ↓
 ┌──────────────────────┐
 ↓                      ↓
Cadete 1º año       Infantil 1º año
 ↓                      ↓
cadete-masculino-1-ano.ics   infantil-masculino-1-ano.ics
 └──────────┬───────────┘
            ↓
      GitHub Pages  (+ index.html de suscripción + estado.json)
            ↓
       Suscripción webcal://
            ↓
      Apple Calendar (se refresca solo)
```

* **Lunes**: consulta la FBM, detecta cambios y marca como «🔎 Verificado el lunes» los partidos de esa semana (de lunes a domingo).
* **Viernes**: vuelve a consultar y marca los partidos de este fin de semana como «✅ CONFIRMADO» (confirmación final).
* En cada ejecución se revisa **toda la temporada**, así que los partidos futuros aparecen desde el principio.
  Los que no tienen hora se muestran a las **00:00** con ⏳ hasta que la FBM publique la hora oficial.
* Cada evento empieza **45 min antes** del partido y termina **2 h después** del inicio
  (partido a las 16:45 → evento de 16:00 a 18:45).

### Cómo se conserva la hora del partido

`Hora FBM (texto «12:30»)` → `Python la guarda tal cual («12:30»)` → `.ics: DTSTART;TZID=Europe/Madrid:…T114500`
→ `Apple Calendar: 11:45–14:30, hora de Madrid`.

* **No hay ninguna conversión a UTC** ni desfase de zona horaria.
  La hora se escribe como hora local de Madrid con `TZID=Europe/Madrid`, y el calendario incluye las reglas de verano e invierno.
* La **única** diferencia entre la hora de la FBM y el inicio del bloque en el calendario son los 45 minutos de antelación acordados.
  Por eso un partido a las **12:30** aparece como bloque **11:45–14:30**.
  La hora exacta del partido figura siempre en la descripción: «🕐 Hora: 12:30».
* Si prefieres que el bloque empiece justo a la hora del partido, cambia `"minutos_antes": 45` por `0` en `config.json`.
  Hay una prueba que lo verifica: 12:30 en la FBM → 12:30 en el calendario.

### Horario: «comprobación de las 17:00»

La comprobación **representa la de las 17:00** del lunes y del viernes (hora de Madrid, con horario de verano o invierno automático).
En GitHub se lanza a las **17:05**: GitHub avisa de que las tareas programadas en el minuto 0 son las que más se retrasan
o se descartan cuando hay mucha carga. Además hay una **ejecución de respaldo a las 18:45**.
Si la de las 17:05 ya terminó bien, la de respaldo no hace nada. Si GitHub se la saltó o falló, la de respaldo hace el trabajo.

### Identificador único (sin duplicados)

Cada partido tiene una clave `temporada | grupo FBM | equipo | jornada | local-vs-visitante`
(p. ej. `2026-27|fbm-17743|cadete-masc-1-ano|j01|c-b-coslada-vs-cb-arganda`). El grupo FBM identifica
la competición, la categoría, la fase y el grupo. El **UID** del evento se genera una sola vez y no cambia nunca.
Por eso un cambio de hora, fecha, pabellón o nombre de equipo **modifica el mismo evento**.

| Situación | Qué hace | ¿Aviso? |
|---|---|---|
| Partido nuevo | Crea el evento | No |
| Hora 00:00 → hora oficial | Modifica el evento | No |
| Cambio de hora / fecha / pabellón | Modifica el evento | Sí |
| Aplazado con nueva fecha | Mueve el evento a la nueva fecha/hora | Sí |
| Aplazado sin fecha | Lo deja en su fecha con «⏸️ APLAZADO» | Sí |
| Cancelado / anulado | Lo elimina del calendario | Sí |
| Desaparece de la web | **No lo borra**: lo marca con ⚠️ | Sí |
| Vuelve a aparecer | Quita el aviso | Sí |
| Cambio de nombre de un equipo | Mismo evento, nombre actualizado | Sí |
| Discrepancia entre fuentes oficiales | Aplica la regla de abajo, la anota en el evento | Sí |
| Nueva fase o grupo (p. ej. eliminatorias) | Añade sus partidos | Sí |
| Error (web caída, formato cambiado…) | **No toca nada**, workflow en rojo, reintenta | Sí |
| Sin cambios | Nada | No |

## 2. Fuentes oficiales

Todas son de la **Federación de Baloncesto de Madrid**, el organismo que organiza estas ligas:

1. **Página de resultados del club** (fuente principal):
   <https://www.fbm.es/resultados-club-6917/baloncesto-arganda>.
   Es HTML generado en el servidor, sin JavaScript ni Cloudflare, y contiene el **calendario completo de cada grupo** del club.
2. **Tabla «Próximos partidos»** de esa misma página (contraste).
3. **Excel oficial de próximos partidos**: `https://www.fbm.es/informes.aspx?delegacion=1&club=6917&informe=proximos-partidos-club&formato=xlsx` (contraste).

¿Por qué esta fuente? La FBM no ofrece ni API, ni JSON ni ICS. La página general «Horarios y resultados»
funciona con formularios ASP.NET (postbacks), mucho más frágiles. La página del club es una sola petición GET
pública y estable que ya trae todos los grupos del club.

**Regla ante discrepancias** (nunca se elige al azar):

* Un dato «sin publicar» no contradice a uno publicado.
* Si las fuentes discrepan, se usa el valor de la mayoría.
* Si no hay mayoría, manda el **calendario oficial de la competición**.
* La discrepancia se escribe en la descripción del evento y se avisa.

**Identificación de los equipos**:

* Solo se aceptan grupos cuya categoría sea *exactamente* `Cadete Masc. 1ºaño` o `Infantil Masc. 1ºaño`,
  así que nunca se mezclan con «Cadete Masc. Pref.» ni con «Infantil Masc. Pref.».
* Dentro del grupo, el equipo del club es el único cuyo nombre contiene «ARGANDA».
* Si hubiera dos, **no se adivina**: se avisa y se configura `nombre_fbm` en `config.json`.

> La categoría `Infantil Masc. 1ºaño` **aún no está publicada** en la temporada 2026-27. La temporada pasada
> empezó el 19/10/2025. En cuanto la FBM la publique, sus partidos se añadirán solos y recibirás un aviso.

## 3. Avisos y detección de errores (sin email ni credenciales)

El sistema funciona perfectamente **sin avisos**. Aun así, hay cuatro formas de enterarse de lo que pasa, todas gratis:

1. **Workflow en rojo**: si algo falla, la ejecución termina con error y GitHub lo marca en rojo en la pestaña *Actions*.
   GitHub avisa automáticamente de los workflows fallidos a la persona que subió el workflow.
2. **Issues automáticos del repositorio** (opcional).
   El workflow crea un *Issue* cuando hay cambios (hora, fecha, pabellón, aplazamiento, cancelación…) y otro cuando hay un error.
   Este último se cierra solo en cuanto una ejecución vuelve a funcionar.
   Usa el **token automático de GitHub** (`GITHUB_TOKEN`): no hay que crear ni guardar nada.
   GitHub te lo notifica en github.com, en la **app GitHub Mobile** y, si lo tienes activado, en el email de tu cuenta de GitHub.
3. **Resumen de cada ejecución**: en *Actions* → la ejecución → *Summary* verás una tabla con los partidos, el próximo partido y los cambios.
4. **Página de estado**: la página publicada muestra la **última comprobación correcta** y la próxima.
   Si tiene más de 4 días, algo ha fallado. `estado.json` tiene el detalle técnico.

## 4. Coste: 0 €/mes

| Pieza | Plan | Límite | Uso real |
|---|---|---|---|
| GitHub (repositorio público) | Free | — | 1 repositorio |
| GitHub Actions | Free: minutos **ilimitados** en repos públicos | — | ~2 min × 2-4 ejecuciones/semana |
| GitHub Pages | Free (repos públicos) | 100 GB/mes de tráfico, 1 GB de sitio | < 1 MB de sitio |
| GitHub Issues (avisos) | Incluido | — | Unos pocos al mes |
| Apple Calendar | Incluido en iOS/macOS | — | 4 suscripciones |

Nada caduca ni se convierte en pago. El repositorio es público porque GitHub Pages gratis lo exige.
Solo contiene **información pública de los partidos** (equipos, fechas, horas y pabellones publicados por la FBM):
ni nombres de jugadores, ni emails, ni contraseñas, ni tokens.
Los commits usan identidades *noreply*, y la copia de la web de la FBM que usan las pruebas está anonimizada.

## 5. Archivos

```
config.json                      Equipos, categorías FBM, colores, 45 min / 2 h
pabellones.json                  Correcciones manuales de dirección (opcional)
requirements.txt                 beautifulsoup4, openpyxl, tzdata
fbmcal/fuente.py                 Descarga y lectura de la web y del Excel de la FBM
fbmcal/conciliar.py              Claves únicas, detección de cambios, contraste de fuentes
fbmcal/ics.py                    Generación de los .ics (Europe/Madrid, verano/invierno)
fbmcal/informe.py                Resumen de ejecución, avisos (Issues) y estado.json
fbmcal/web.py                    Página de suscripción y estado
fbmcal/main.py                   Orquestación (python -m fbmcal), escritura atómica
tests/                           43 pruebas con la página real de la FBM guardada (reducida y anonimizada)
.github/workflows/actualizar-calendarios.yml   Automatización
data/estado.json                 (se genera) memoria de partidos y cambios
docs/                            (se genera) lo que publica GitHub Pages
```

## 6. Configuración paso a paso (una sola vez, ~10 min)

### 6.1 Crear el repositorio y subir el código

1. Entra en <https://github.com/new>.
   * *Repository name*: `calendarios-cb-arganda`.
   * **Public**.
   * No marques «Add a README».
   * Pulsa **Create repository**.
2. En esta carpeta (`C:\Users\JER\Documents\baloncesto\calendarios`), abre una terminal y ejecuta
   (ya hecho: el repositorio es <https://github.com/juannnES/calendarios-cb-arganda>):
   ```bash
   git remote add origin https://github.com/juannnES/calendarios-cb-arganda.git
   git push -u origin main
   ```
   La primera vez, Windows abrirá una ventana para iniciar sesión **en GitHub**. Es tu sesión de GitHub, no se guarda en el proyecto.

### 6.2 Activar GitHub Pages

Repositorio → **Settings** → **Pages** → *Build and deployment* → *Source*: **GitHub Actions**.

### 6.3 Primera ejecución

1. Repositorio → **Actions**. Si pregunta, pulsa *I understand my workflows, go ahead and enable them*.
2. **Actualizar calendarios** → **Run workflow** → modo `manual` → **Run workflow**.
3. Cuando termine con ✅ (1-2 min), los calendarios estarán en
   <https://juannnes.github.io/calendarios-cb-arganda/>.
   En la pestaña **Issues** aparecerá el aviso «🆕 Nueva competición/fase detectada» del cadete.

### 6.4 (Opcional) Comprobar que te llegan los avisos

* **Run workflow** → marca *Solo crear un aviso de prueba (Issue)* → **Run workflow**.
* Para recibirlo en el móvil, instala la app **GitHub Mobile** e inicia sesión.
* En <https://github.com/settings/notifications>, en *Subscriptions → Watching*, activa **GitHub** (web y móvil) y/o **Email**.
  Ese email lo envía GitHub a la dirección de tu cuenta de GitHub. No necesita Gmail ni ninguna contraseña.
* Si no te llega, en el repositorio pulsa **Watch → All Activity**.

## 7. Automatización

* Se ejecuta sola **cada lunes y viernes: comprobación de las 17:00, hora de Madrid** (lanzada a las 17:05, con respaldo a las 18:45).
* **Antes de tocar nada** pasa las pruebas automáticas. Si fallan, no se modifica ningún calendario.
* **Escritura atómica**: los dos `.ics`, la página, el `estado.json` y el estado interno se generan primero en memoria
  y solo se escriben si todo ha ido bien.
  Si la FBM no responde, devuelve una página rota o cambia de formato, la ejecución falla sin modificar nada.
  GitHub Pages sigue sirviendo los últimos calendarios buenos.
* Puedes lanzar una comprobación cuando quieras desde **Actions → Run workflow**.
* Para que no se desactive por inactividad (la regla de GitHub de 60 días en repositorios públicos),
  cada ejecución correcta guarda un commit, así que el repositorio siempre tiene actividad.

## 8. Acceder a los calendarios (móvil y ordenador)

Abre <https://juannnes.github.io/calendarios-cb-arganda/> en cada dispositivo. Cada calendario tiene su propia URL:

* Cadete: `https://juannnes.github.io/calendarios-cb-arganda/cadete-masculino-1-ano.ics`
* Infantil: `https://juannnes.github.io/calendarios-cb-arganda/infantil-masculino-1-ano.ics`

Cómo suscribirse:

* **iPhone / iPad**: pulsa «Suscribirse en Apple Calendar» → *Suscribirse* → en *Cuenta* elige **iCloud** → *Añadir*.
  Con iCloud aparece también en el Mac de esa persona.
* **Mac**: pulsa el botón → Calendario → *Ubicación*: **iCloud** → *Actualización automática*: **Cada 15 minutos** → OK.
* **Familia**: envía el enlace de la página a las otras 3 personas. Cada una se suscribe desde su dispositivo.
* **Google Calendar / Android / Outlook**: añade el enlace `.ics` con «Desde URL». Google refresca los calendarios suscritos cada varias horas.

## 9. Mantenimiento: qué puede romperse y cómo arreglarlo

| Posible problema | Síntoma | Solución |
|---|---|---|
| La FBM cambia el diseño de su web | Workflow en rojo + Issue «❌ Error». Los calendarios no se tocan | Ajustar `fbmcal/fuente.py`; los tests con la página guardada ayudan |
| Cambia la URL del club | Error de descarga | Actualizar `club_url` y `xlsx_url` en `config.json` |
| La FBM renombra la categoría | Aviso «⚠️ Posible categoría no reconocida» | Añadir el nuevo nombre a `categoria_fbm` en `config.json` |
| El equipo aparece con otro nombre sin «ARGANDA» | Aviso «No se encuentra ningún equipo del club» | Poner el nombre exacto en `nombre_fbm` en `config.json` |
| Dos equipos del club en el mismo grupo | Aviso «Hay varios equipos del club» | Poner el nombre del correcto en `nombre_fbm` |
| GitHub desactiva el cron por inactividad | La página muestra una última comprobación antigua | Actions → Actualizar calendarios → *Enable workflow* |
| Dirección de un pabellón incompleta | Mapa impreciso | Añadir la corrección a `pabellones.json` |
| Nueva temporada (agosto) | Nada: la clave incluye la temporada y los grupos nuevos se detectan solos | Opcional: si la FBM cambia los nombres de categoría, actualizar `config.json` |

Para probar en local (Windows):
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -v
python -m fbmcal --modo manual --estado prueba/estado.json --salida prueba/docs
```
