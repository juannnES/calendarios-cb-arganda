# 🏀 Calendarios automáticos CB Arganda (FBM)

Dos calendarios **independientes** y siempre al día, para suscribirse desde Apple Calendar
(iPhone, iPad y Mac), Google Calendar u Outlook:

| Calendario | Categoría FBM | Archivo |
|---|---|---|
| CB Arganda · Cadete Masc. 1º año | `Cadete Masc. 1ºaño` | `cadete-masculino-1-ano.ics` |
| CB Arganda · Infantil Masc. 1º año | `Infantil Masc. 1ºaño` | `infantil-masculino-1-ano.ics` |

Coste: **0 €/mes**. Sin servidores ni suscripciones.

---

## 1. Arquitectura

```
 GitHub Actions (gratis)                                   GitHub Pages (gratis)
 ┌───────────────────────────────────────────────┐        ┌──────────────────────────┐
 │ Lunes y viernes 17:05 (Europe/Madrid)        │        │ index.html (suscribirse)  │
 │  + respaldo 18:45 si la primera no se ejecutó │        │ cadete-...ics             │
 │                                               │  ───►  │ infantil-...ics           │
 │ 1. Pruebas automáticas                        │        └────────────┬─────────────┘
 │ 2. Descarga web oficial FBM + Excel oficial   │                     │ webcal://
 │ 3. Contrasta fuentes y detecta cambios        │                     ▼
 │ 4. Guarda estado (data/estado.json)           │        Apple Calendar de cada
 │ 5. Genera los 2 .ics                          │        miembro de la familia
 │ 6. Email si hay cambios / problemas           │        (se refresca solo)
 └───────────────────────────────────────────────┘
```

* **Lunes**: comprueba todos los partidos y marca como «🔎 Verificado el lunes» los de esa semana (de lunes a domingo).
* **Viernes**: vuelve a comprobar y marca los de este fin de semana como «✅ CONFIRMADO» (confirmación final).
* En cada ejecución se revisa **toda la temporada**, así que los partidos futuros aparecen desde el principio.
  Los que no tienen hora se muestran a las **00:00** con ⏳ hasta que la FBM publique la hora oficial.
* Cada evento empieza **45 min antes** del partido y termina **2 h después** del inicio
  (partido a las 16:45 → evento de 16:00 a 18:45).

### Identificador único (sin duplicados)

Cada partido tiene una clave `temporada | grupo FBM | equipo | jornada | local-vs-visitante`
(p. ej. `2026-27|fbm-17743|cadete-masc-1-ano|j01|c-b-coslada-vs-cb-arganda`). El grupo FBM identifica
la competición, la categoría, la fase y el grupo. El **UID** del evento se genera una sola vez y no cambia nunca.
Por eso un cambio de hora, fecha, pabellón o nombre de equipo **modifica el mismo evento**.

| Situación | Qué hace | ¿Email? |
|---|---|---|
| Partido nuevo | Crea el evento | No |
| Hora 00:00 → hora oficial | Modifica el evento | No |
| Cambio de hora / fecha / pabellón | Modifica el evento | Sí |
| Aplazado con nueva fecha | Mueve el evento a la nueva fecha/hora | Sí |
| Aplazado sin fecha | Lo deja en su fecha con «⏸️ APLAZADO» | Sí |
| Cancelado / anulado | Lo elimina del calendario | Sí |
| Desaparece de la web | **No lo borra**: lo marca con ⚠️ y avisa | Sí |
| Vuelve a aparecer | Quita el aviso | Sí |
| Cambio de nombre de un equipo | Mismo evento, nombre actualizado | Sí |
| Discrepancia entre fuentes oficiales | Aplica la regla de abajo, la anota en el evento | Sí |
| Nueva fase o grupo (p. ej. eliminatorias) | Añade sus partidos | Sí |
| Error (web caída, formato cambiado…) | **No toca nada** y reintenta | Sí |
| Sin cambios | Nada | No |

## 2. Fuentes oficiales

Todas son de la **Federación de Baloncesto de Madrid**, el organismo que organiza estas ligas:

1. **Página de resultados del club** (fuente principal):
   <https://www.fbm.es/resultados-club-6917/baloncesto-arganda>.
   Es HTML generado en el servidor, sin JavaScript ni Cloudflare, y contiene el **calendario completo de cada grupo** del club.
   De ahí se leen la jornada, el local y el visitante, la fecha, la hora, el pabellón y la dirección.
2. **Tabla «Próximos partidos»** de esa misma página (contraste).
3. **Excel oficial de próximos partidos**: `https://www.fbm.es/informes.aspx?delegacion=1&club=6917&informe=proximos-partidos-club&formato=xlsx` (contraste).

¿Por qué esta fuente? La FBM no ofrece ni API, ni JSON ni ICS. La página general «Horarios y resultados»
funciona con formularios ASP.NET (postbacks), mucho más frágiles. La página del club es una sola petición GET
estable que ya trae todos los grupos del club.

**Regla ante discrepancias** (nunca se elige al azar):

* Un dato «sin publicar» no contradice a uno publicado.
* Si las fuentes discrepan, se usa el valor de la mayoría.
* Si no hay mayoría, manda el **calendario oficial de la competición**.
* La discrepancia se escribe en la descripción del evento y se avisa por email.

**Identificación de los equipos**:

* Solo se aceptan grupos cuya categoría sea *exactamente* `Cadete Masc. 1ºaño` o `Infantil Masc. 1ºaño`,
  así que nunca se confunden con «Cadete Masc. Pref.» ni con «Infantil Masc. Pref.».
* Dentro del grupo, el equipo del club es el único cuyo nombre contiene «ARGANDA».
* Si hubiera dos, **no se adivina**: se avisa por email y se configura `nombre_fbm` en `config.json`.

> La categoría `Infantil Masc. 1ºaño` **aún no está publicada** en la temporada 2026-27. La temporada pasada
> empezó el 19/10/2025. En cuanto la FBM la publique, sus partidos se añadirán solos y recibirás un email.

## 3. Coste: 0 €/mes

| Pieza | Plan | Límite | Uso real |
|---|---|---|---|
| GitHub (repositorio público) | Free | — | 1 repositorio |
| GitHub Actions | Free: minutos **ilimitados** en repos públicos | — | ~2 min × 2-4 ejecuciones/semana |
| GitHub Pages | Free (repos públicos) | 100 GB/mes de tráfico, 1 GB de sitio | < 1 MB de sitio, KB/día |
| Gmail SMTP (avisos) | Cuenta gratuita | ~500 emails/día | Unos pocos al mes |
| Apple Calendar | Incluido en iOS/macOS | — | 4 suscripciones |

Nada caduca ni se convierte en pago. El repositorio es público porque GitHub Pages gratis lo exige.
Solo contiene datos públicos de la FBM (equipos, fechas y pabellones): **ningún nombre de jugador ni ningún email**.
Los emails van en *Secrets* cifrados.

## 4. Archivos

```
config.json                      Equipos, categorías FBM, colores, 45 min / 2 h
pabellones.json                  Correcciones manuales de dirección (opcional)
requirements.txt                 beautifulsoup4, openpyxl, tzdata
fbmcal/fuente.py                 Descarga y lectura de la web y del Excel de la FBM
fbmcal/conciliar.py              Claves únicas, detección de cambios, contraste de fuentes
fbmcal/ics.py                    Generación de los .ics (Europe/Madrid, verano/invierno)
fbmcal/avisos.py                 Emails por Gmail
fbmcal/web.py                    Página de suscripción
fbmcal/main.py                   Orquestación (python -m fbmcal)
tests/                           35 pruebas con la página real de la FBM guardada
.github/workflows/actualizar-calendarios.yml   Automatización
data/estado.json                 (se genera) memoria de partidos y cambios
docs/                            (se genera) lo que publica GitHub Pages
```

## 5. Configuración paso a paso (una sola vez, ~15 min)

### 5.1 Crear el repositorio y subir el código

1. Entra en <https://github.com/new>.
   * *Repository name*: `calendarios-cb-arganda`.
   * **Public**.
   * No marques «Add a README».
   * Pulsa **Create repository**.
2. En esta carpeta (`C:\Users\JER\Documents\baloncesto\calendarios`), abre una terminal y ejecuta
   (cambia `TU_USUARIO` por tu usuario de GitHub):
   ```bash
   git remote add origin https://github.com/TU_USUARIO/calendarios-cb-arganda.git
   git push -u origin main
   ```
   La primera vez, Windows abrirá una ventana para iniciar sesión en GitHub.

### 5.2 Activar GitHub Pages

Repositorio → **Settings** → **Pages** → *Build and deployment* → *Source*: **GitHub Actions**.

### 5.3 Crear la contraseña de aplicación de Gmail (para los avisos)

Gmail no deja usar tu contraseña normal desde programas. Hay que crear una contraseña de aplicación:

1. Entra con la cuenta que **enviará** los avisos (puede ser la misma que los recibe).
   Hace falta tener la **verificación en dos pasos** activada: <https://myaccount.google.com/signinoptions/twosv>.
2. Ve a <https://myaccount.google.com/apppasswords>, escribe un nombre (p. ej. `Calendarios`) y pulsa **Crear**.
3. Copia los 16 caracteres que aparecen. Solo se muestran una vez.

### 5.4 Guardar los secretos en GitHub (nunca en el código)

Repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Crea estos tres:

| Nombre | Valor |
|---|---|
| `GMAIL_USER` | La dirección Gmail que envía (la de la contraseña de aplicación) |
| `GMAIL_APP_PASSWORD` | Los 16 caracteres del paso anterior |
| `NOTIFY_TO` | La dirección que recibe los avisos |

### 5.5 Primera ejecución y prueba del email

1. Repositorio → **Actions**. Si pregunta, pulsa *I understand my workflows, go ahead and enable them*.
2. **Actualizar calendarios** → **Run workflow** → marca *Solo enviar un email de prueba* → **Run workflow**.
   Deberías recibir el email de prueba en 1-2 minutos.
3. Otra vez **Run workflow**, ahora **sin** marcar la casilla y con modo `manual`.
   Cuando termine (círculo verde), tendrás los calendarios publicados en
   `https://TU_USUARIO.github.io/calendarios-cb-arganda/` y recibirás un email
   «Nueva competición/fase detectada» del cadete.

## 6. Automatización

* El workflow se ejecuta solo **cada lunes y viernes a las 17:05, hora de Madrid**.
  GitHub aplica el cambio de horario de verano o invierno gracias a `timezone: "Europe/Madrid"`.
* GitHub puede retrasar unos minutos las tareas programadas, e incluso saltarse alguna si hay mucha carga.
  Por eso hay una **segunda ejecución de respaldo a las 18:45**. Si la de las 17:05 ya terminó bien, la de respaldo no hace nada.
* Si algo falla, el sistema no modifica los calendarios. Recibirás un email de error, y GitHub te enviará otro, y se reintentará en la siguiente ejecución.
* Puedes lanzar una comprobación cuando quieras desde **Actions → Run workflow**.

## 7. Acceder a los calendarios (móvil y ordenador)

Abre `https://TU_USUARIO.github.io/calendarios-cb-arganda/` en cada dispositivo:

* **iPhone / iPad**: pulsa «Suscribirse en Apple Calendar» → *Suscribirse* → en *Cuenta* elige **iCloud** → *Añadir*.
  Si usas iCloud, basta con suscribirse una vez por persona: aparece también en su Mac.
  Si se añade «En mi iPhone», se refresca según *Ajustes → Calendario → Cuentas → Obtener datos*.
* **Mac**: pulsa el botón → Calendario → *Ubicación*: **iCloud** → *Actualización automática*: **Cada 15 minutos** → OK.
* **Compartir con la familia**: envía el enlace de la página a las otras 3 personas. Cada una se suscribe desde su dispositivo.
* **Google Calendar / Android / Outlook**: añade el enlace `.ics` con «Desde URL». Ojo: Google refresca los calendarios suscritos cada varias horas.

Las alertas se configuran en cada dispositivo. En Mac, al suscribirte, desmarca «Eliminar alertas» si quieres que funcionen.

## 8. Mantenimiento: qué puede romperse y cómo arreglarlo

| Posible problema | Síntoma | Solución |
|---|---|---|
| La FBM cambia el diseño de su web | Email «❌ error» o «La web no muestra ningún partido…». Los calendarios no se tocan | Ajustar `fbmcal/fuente.py`; los tests con la página guardada ayudan |
| Cambia la URL del club | Error de descarga | Actualizar `club_url` y `xlsx_url` en `config.json` |
| La FBM renombra la categoría | Email «⚠️ Posible categoría no reconocida» | Añadir el nuevo nombre a `categoria_fbm` en `config.json` |
| El equipo aparece con otro nombre sin «ARGANDA» | Email «No se encuentra ningún equipo del club» | Poner el nombre exacto en `nombre_fbm` en `config.json` |
| Dos equipos del club en el mismo grupo | Email «Hay varios equipos del club» | Poner el nombre del correcto en `nombre_fbm` |
| 60 días sin actividad en el repositorio | GitHub desactiva el cron (no debería pasar: cada ejecución guarda un commit) | Actions → Actualizar calendarios → *Enable workflow* |
| Se revoca la contraseña de aplicación de Gmail | No llegan emails (la ejecución sigue funcionando) | Crear otra y actualizar `GMAIL_APP_PASSWORD` |
| Dirección de un pabellón incompleta | Mapa impreciso | Añadir la corrección a `pabellones.json` |
| Nueva temporada (agosto) | Nada: la clave incluye la temporada y los grupos nuevos se detectan solos | Opcional: si la FBM cambia los nombres de categoría, actualizar `config.json` |

Para probar en local (Windows):
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -v
python -m fbmcal --modo manual --sin-email --estado prueba/estado.json --salida prueba/docs
```
