# 🏀 Calendarios automáticos CB Arganda (FBM)

Tres calendarios **independientes** y siempre al día, para suscribirse desde Apple Calendar
(iPhone, iPad y Mac), Google Calendar u Outlook, y **avisos por Telegram** de todo lo que cambia:

| Calendario | Categoría FBM (exacta) | Equipo FBM | Archivo |
|---|---|---|---|
| 🟠 CB Arganda · Cadete Masc. 1º año | `Cadete Masc. 1ºaño` | `CB ARGANDA` | `cadete-masculino-1-ano.ics` |
| 🔵 CB Arganda · Infantil Masc. 1º año | `Infantil Masc. 1ºaño` | (aún no publicado) | `infantil-masculino-1-ano.ics` |
| 🟢 CB Arganda · Infantil Masc. Preferente | `Infantil Masc. Pref.` | `CB ARGANDA` | `infantil-masculino-preferente.ics` |

Coste: **0 €/mes**. Los calendarios **no necesitan ninguna credencial**. Telegram (opcional) solo necesita dos
*Secrets* de GitHub: el token del bot y tu chat. Nada de Gmail, contraseñas de aplicación ni Google.

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
 ┌─────────────────────┼─────────────────────┐
 ↓                     ↓                     ↓
Cadete 1º año     Infantil 1º año     Infantil Preferente
 ↓                     ↓                     ↓
cadete-...ics     infantil-...1-ano.ics   infantil-...preferente.ics
 └─────────────────────┬─────────────────────┘
                       ↓
      GitHub Pages  (+ index.html de suscripción + estado.json)
                       ↓
       Suscripción webcal:// → Apple Calendar (se refresca solo)

                       +

      Cola de avisos (data/telegram.json) → Telegram Bot → tu chat
      (último paso, DESPUÉS de publicar; si falla, los calendarios no se ven afectados)
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

**Cómo se programa (horas en UTC).** GitHub solo entiende de forma fiable horas UTC: con la opción `timezone:`
el viernes 25/09/2026 no se disparó ninguna ejecución. Por eso el workflow programa las dos horas UTC posibles
y el programa, que trabaja en hora de Madrid, solo actúa **desde las 17:00 y una sola vez al día**:

| Cron (UTC) | Verano (UTC+2) | Invierno (UTC+1) |
|---|---|---|
| `5 15 * * 1,5` | **17:05** → comprobación | 16:05 → no hace nada (antes de las 17:00) |
| `5 16 * * 1,5` | 18:05 → ya hecha, no repite (o la hace si la de 17:05 no llegó) | **17:05** → comprobación |
| `45 16 * * 1,5` | **18:45** → respaldo | 17:45 → ya hecha, no repite |
| `45 17 * * 1,5` | 19:45 → ya hecha, no repite | **18:45** → respaldo |

Hay una prueba automática que lo comprueba para días de verano, de invierno y de las dos semanas de cambio de hora.

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
| Sigue sin aparecer en 3 comprobaciones (≥ 7 días) mientras el resto de su grupo sí aparece | Lo elimina del calendario (configurable en `config.json` → `desaparecidos`; `0` = nunca) | Sí |
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

* Solo se aceptan grupos cuya categoría sea *exactamente* `Cadete Masc. 1ºaño`, `Infantil Masc. 1ºaño`
  o `Infantil Masc. Pref.`. Así el infantil de 1º año y el preferente nunca se mezclan entre sí,
  ni con «Cadete Masc. Pref.» u otras categorías.
* **Infantil Preferente** (comprobado en la FBM el 25/09/2026): categoría `Infantil Masc. Pref.`,
  grupo `PRIMERA 1ª DIVISION - GRUPO 2`, equipo `CB ARGANDA`, 22 partidos.
  El nombre `CB ARGANDA` está fijado en `config.json` (`nombre_fbm`). Si apareciera otro equipo infantil
  preferente del club (p. ej. «CB ARGANDA B»), su grupo se ignora y se avisa una vez.
* Dentro del grupo, el equipo del club es el único cuyo nombre contiene «ARGANDA».
* Si hubiera dos, **no se adivina**: se avisa y se configura `nombre_fbm` en `config.json`.

> La categoría `Infantil Masc. 1ºaño` **aún no está publicada** en la temporada 2026-27. La temporada pasada
> empezó el 19/10/2025. En cuanto la FBM la publique, sus partidos se añadirán solos y recibirás un aviso.

## 3. Avisos por Telegram

Telegram es una **capa secundaria**: los calendarios funcionan igual con o sin ella. Orden de cada ejecución:
**1.** datos FBM → **2.** verificar → **3.** conciliar → **4.** generar calendarios → **5.** publicar en Pages → **6.** Telegram.

* El paso de calendarios (4) solo deja los avisos en la cola `data/telegram.json`: no usa red ni token.
* Un trabajo aparte (`telegram`) los envía **después** de publicar, con `continue-on-error`.
  Si Telegram no responde o faltan los secrets, se registra un aviso (⚠️ en *Actions*).
  Los mensajes se quedan en la cola y se reintentan en la siguiente ejecución.
  Los calendarios ya están publicados.
* Los mensajes salen del **resultado de la conciliación** (el mismo que actualiza los `.ics`).
  Telegram no interpreta los datos por su cuenta.

| Resultado | Mensaje | ¿Cuántas veces? |
|---|---|---|
| Primera vez que Telegram procesa un equipo (sus partidos actuales) | 📋 AVISOS DE TELEGRAM ACTIVADOS (un único resumen) | 1 en total |
| Partido que aparece después | 🏀 NUEVO PARTIDO | 1 por partido |
| Lunes: partido de esa semana comprobado | 🔎 PARTIDO DETECTADO | 1 por partido y fecha |
| Viernes: partido de ese fin de semana confirmado | ✅ PARTIDO CONFIRMADO | 1 por partido y fecha |
| Cambio de hora (incluida 00:00 → hora oficial) | 🔄 CAMBIO DE HORA | 1 por cambio |
| Cambio de fecha | 📅 CAMBIO DE FECHA | 1 por cambio |
| Cambio de pabellón o dirección | 📍 CAMBIO DE PABELLÓN | 1 por cambio |
| Aplazado (con o sin nueva fecha) | ⚠️ PARTIDO APLAZADO | 1 por cambio |
| Nueva fecha tras un aplazamiento | 📅 NUEVO HORARIO TRAS EL APLAZAMIENTO | 1 |
| Cancelado | ❌ PARTIDO CANCELADO | 1 |
| Deja de aparecer en la FBM | ⚠️ POSIBLE DESAPARICIÓN (no se elimina) | 1 |
| Eliminado tras varias comprobaciones | 🗑️ PARTIDO ELIMINADO | 1 |
| Rival, local/visitante, competición, estado, resultado, discrepancias | 🔄 INFORMACIÓN ACTUALIZADA | 1 por cambio |
| Nueva competición/fase del equipo | 🆕 NUEVA COMPETICIÓN DETECTADA | 1 |
| Error | 🚨 ERROR EN LA AUTOMATIZACIÓN | 1 por ejecución fallida (el mismo error de un grupo, como mucho cada 3 días) |
| Sin cambios | — | 0 |

**Anti-duplicados**: cada aviso tiene un identificador basado en el UID del partido. Las altas y las
verificaciones se marcan en el estado del partido. Diez ejecuciones sin cambios envían **0 mensajes**.

**Primera ejecución con Telegram (línea base)**: los partidos que ya existen en la FBM se registran como estado
inicial **sin** un aviso por partido. Recibirás un único mensaje «📋 AVISOS DE TELEGRAM ACTIVADOS» con el número de
partidos de cada calendario (hoy: 20 del cadete, 0 del infantil 1º y 22 del infantil preferente). En esa misma
ejecución sí se avisan los cambios reales y la verificación del lunes o la confirmación del viernes, si toca.
Desde ahí, cada partido que aparezca después genera su 🏀 NUEVO PARTIDO. Esto incluye los del Infantil 1º año
cuando la FBM publique la categoría.

### 3.1 Configurar Telegram (una vez, ~5 min)

1. **Crear el bot**: en Telegram, abre una conversación con **@BotFather** (tiene la marca azul de verificado).
   Envía `/newbot` y responde:
   * un **nombre** (p. ej. `Calendarios CB Arganda`);
   * un **usuario** que termine en `bot` (p. ej. `calendarios_cbarganda_bot`).
2. **Token**: BotFather te responde con una línea tipo `123456789:AA…`. Ese es el token.
   **No lo pegues en ningún chat, archivo ni commit**: solo irá a GitHub Secrets (paso 4).
3. **Tu chat_id**:
   1. Abre tu bot en Telegram (el enlace `t.me/…` que te da BotFather), pulsa **Iniciar** y escríbele `hola`.
   2. En tu ordenador, abre PowerShell y ejecuta (te pedirá el token sin mostrarlo en pantalla):
      ```powershell
      $s = Read-Host "Token del bot" -AsSecureString; $t = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)); (Invoke-RestMethod "https://api.telegram.org/bot$t/getUpdates").result.message.chat | Select-Object id, first_name -Unique
      ```
      El número de la columna `id` es tu **chat_id**. Si sale vacío, vuelve a escribir al bot y repite.
      El token se escribe oculto (`****`) y no queda guardado en el historial de PowerShell.
4. **Guardar en GitHub**: repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   Crea estos dos:
   | Name | Secret |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | el token del paso 2 |
   | `TELEGRAM_CHAT_ID` | el número del paso 3 |

   El chat_id no es tan sensible como el token, pero el repositorio es público y los logs también.
   Por eso se guarda también como *Secret*: GitHub lo oculta con `***` en cualquier log.
5. **Probar**: **Actions** → **Actualizar calendarios** → **Run workflow** → marca *Solo enviar un mensaje de
   prueba por Telegram* → **Run workflow**. En menos de un minuto recibirás
   «🏀 Prueba de avisos de los calendarios CB Arganda». Si no llega, abre la ejecución → trabajo **telegram**:
   el aviso ⚠️ explica la causa (secret que falta, token incorrecto o chat que no ha pulsado *Iniciar*).
6. **Primera ejecución real**: **Run workflow** con modo `manual` y sin marcar nada. Llegarán los avisos de alta de
   todos los partidos futuros.

## 4. Otros avisos y detección de errores

Además de Telegram, hay cuatro formas de enterarse de lo que pasa, todas gratis:

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

## 5. Coste: 0 €/mes

| Pieza | Plan | Límite | Uso real |
|---|---|---|---|
| GitHub (repositorio público) | Free | — | 1 repositorio |
| GitHub Actions | Free: minutos **ilimitados** en repos públicos | — | ~2 min × 2-4 ejecuciones/semana |
| GitHub Pages | Free (repos públicos) | 100 GB/mes de tráfico, 1 GB de sitio | < 1 MB de sitio |
| GitHub Issues (avisos) | Incluido | — | Unos pocos al mes |
| Telegram Bot API | Gratuita, sin planes de pago para bots | ~30 mensajes/s | Unos pocos por semana |
| Apple Calendar | Incluido en iOS/macOS | — | 4 suscripciones |

Nada caduca ni se convierte en pago. El repositorio es público porque GitHub Pages gratis lo exige.
Solo contiene **información pública de los partidos** (equipos, fechas, horas y pabellones publicados por la FBM):
ni nombres de jugadores, ni emails, ni contraseñas, ni tokens.
Los commits usan identidades *noreply*, y la copia de la web de la FBM que usan las pruebas está anonimizada.

## 6. Archivos

```
config.json                      Equipos, categorías FBM, colores, 45 min / 2 h
pabellones.json                  Correcciones manuales de dirección (opcional)
requirements.txt                 beautifulsoup4, openpyxl, tzdata
fbmcal/fuente.py                 Descarga y lectura de la web y del Excel de la FBM
fbmcal/conciliar.py              Claves únicas, detección de cambios, contraste de fuentes
fbmcal/ics.py                    Generación de los .ics (Europe/Madrid, verano/invierno)
fbmcal/informe.py                Resumen de ejecución, avisos (Issues) y estado.json
fbmcal/avisos_telegram.py        Resultado de la conciliación → mensajes de Telegram (sin red ni token)
fbmcal/telegram.py               Cola y envío por la Telegram Bot API (solo biblioteca estándar)
fbmcal/web.py                    Página de suscripción y estado
fbmcal/main.py                   Orquestación (python -m fbmcal), escritura atómica
tests/                           89 pruebas (calendarios, Telegram, tercer equipo, primera ejecución y horarios), sin red ni tokens reales
.github/workflows/actualizar-calendarios.yml   Automatización
data/estado.json                 (se genera) memoria de partidos y cambios
data/telegram.json               (se genera) cola de avisos pendientes y registro de enviados (sin secretos)
docs/                            (se genera) lo que publica GitHub Pages
```

## 7. Configuración paso a paso (una sola vez, ~10 min)

### 7.1 Crear el repositorio y subir el código

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

### 7.2 Activar GitHub Pages

Repositorio → **Settings** → **Pages** → *Build and deployment* → *Source*: **GitHub Actions**.

### 7.3 Primera ejecución

1. Repositorio → **Actions**. Si pregunta, pulsa *I understand my workflows, go ahead and enable them*.
2. **Actualizar calendarios** → **Run workflow** → modo `manual` → **Run workflow**.
3. Cuando termine con ✅ (1-2 min), los calendarios estarán en
   <https://juannnes.github.io/calendarios-cb-arganda/>.
   En la pestaña **Issues** aparecerá el aviso «🆕 Nueva competición/fase detectada» del cadete.

### 7.4 (Opcional) Comprobar que te llegan los avisos

* **Run workflow** → marca *Solo crear un aviso de prueba (Issue)* → **Run workflow**.
* Para recibirlo en el móvil, instala la app **GitHub Mobile** e inicia sesión.
* En <https://github.com/settings/notifications>, en *Subscriptions → Watching*, activa **GitHub** (web y móvil) y/o **Email**.
  Ese email lo envía GitHub a la dirección de tu cuenta de GitHub. No necesita Gmail ni ninguna contraseña.
* Si no te llega, en el repositorio pulsa **Watch → All Activity**.

## 8. Automatización

* Se ejecuta sola **cada lunes y viernes: comprobación de las 17:00, hora de Madrid** (lanzada a las 17:05, con respaldo a las 18:45).
* **Antes de tocar nada** pasa las pruebas automáticas. Si fallan, no se modifica ningún calendario.
* **Escritura atómica**: los dos `.ics`, la página, el `estado.json` y el estado interno se generan primero en memoria
  y solo se escriben si todo ha ido bien.
  Si la FBM no responde, devuelve una página rota o cambia de formato, la ejecución falla sin modificar nada.
  GitHub Pages sigue sirviendo los últimos calendarios buenos.
* Puedes lanzar una comprobación cuando quieras desde **Actions → Run workflow**.
* Para que no se desactive por inactividad (la regla de GitHub de 60 días en repositorios públicos),
  cada ejecución correcta guarda un commit, así que el repositorio siempre tiene actividad.

## 9. Acceder a los calendarios (móvil y ordenador)

Abre <https://juannnes.github.io/calendarios-cb-arganda/> en cada dispositivo. Cada calendario tiene su propia URL:

* Cadete: `https://juannnes.github.io/calendarios-cb-arganda/cadete-masculino-1-ano.ics`
* Infantil 1º año: `https://juannnes.github.io/calendarios-cb-arganda/infantil-masculino-1-ano.ics`
* Infantil Preferente: `https://juannnes.github.io/calendarios-cb-arganda/infantil-masculino-preferente.ics`

Cómo suscribirse:

* **iPhone / iPad**: pulsa «Suscribirse en Apple Calendar» → *Suscribirse* → en *Cuenta* elige **iCloud** → *Añadir*.
  Con iCloud aparece también en el Mac de esa persona.
* **Mac**: pulsa el botón → Calendario → *Ubicación*: **iCloud** → *Actualización automática*: **Cada 15 minutos** → OK.
* **Familia**: envía el enlace de la página a las otras 3 personas. Cada una se suscribe desde su dispositivo.
* **Google Calendar / Android / Outlook**: añade el enlace `.ics` con «Desde URL». Google refresca los calendarios suscritos cada varias horas.

## 10. Mantenimiento: qué puede romperse y cómo arreglarlo

| Posible problema | Síntoma | Solución |
|---|---|---|
| La FBM cambia el diseño de su web | Workflow en rojo + Issue «❌ Error». Los calendarios no se tocan | Ajustar `fbmcal/fuente.py`; los tests con la página guardada ayudan |
| Cambia la URL del club | Error de descarga | Actualizar `club_url` y `xlsx_url` en `config.json` |
| La FBM renombra la categoría | Aviso «⚠️ Posible categoría no reconocida» | Añadir el nuevo nombre a `categoria_fbm` en `config.json` |
| El equipo aparece con otro nombre sin «ARGANDA» | Aviso «No se encuentra ningún equipo del club» | Poner el nombre exacto en `nombre_fbm` en `config.json` |
| Dos equipos del club en el mismo grupo | Aviso «Hay varios equipos del club» | Poner el nombre del correcto en `nombre_fbm` |
| GitHub desactiva el cron por inactividad | La página muestra una última comprobación antigua | Actions → Actualizar calendarios → *Enable workflow* |
| Dirección de un pabellón incompleta | Mapa impreciso | Añadir la corrección a `pabellones.json` |
| Telegram no avisa | ⚠️ en el trabajo **telegram** de la ejecución | Revisar los secrets; los avisos esperan en `data/telegram.json` y salen en la siguiente ejecución |
| Token del bot expuesto por error | — | En @BotFather: `/revoke` → elegir el bot → nuevo token → actualizar el secret `TELEGRAM_BOT_TOKEN` |
| Nueva temporada (agosto) | Nada: la clave incluye la temporada y los grupos nuevos se detectan solos | Opcional: si la FBM cambia los nombres de categoría, actualizar `config.json` |

Para probar en local (Windows):
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -v
python -m fbmcal --modo manual --estado prueba/estado.json --salida prueba/docs
```
