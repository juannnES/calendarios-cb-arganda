"""Página índice (GitHub Pages) con los botones de suscripción a cada calendario."""
from datetime import date, datetime
from html import escape

from .ics import titulo_evento
from .util import DIAS, fecha_es


def generar_indice(config: dict, estado: dict, ahora: datetime) -> str:
    tarjetas = []
    hoy = ahora.date().isoformat()
    for cfg in config["equipos"]:
        est = estado["equipos"].get(cfg["id"], {})
        proximos = sorted(
            (q for q in est.get("partidos", {}).values()
             if q["estado"] != "cancelado" and q["fecha"] and q["fecha"] >= hoy),
            key=lambda q: (q["fecha"], q["hora"] or ""))[:5]
        if proximos:
            filas = "".join(
                f"<li><span class='f'>{DIAS[date.fromisoformat(q['fecha']).weekday()][:3]} {fecha_es(q['fecha'])}"
                f" · {q['hora'] or 'hora pendiente'}</span>{escape(titulo_evento(q, cfg['nombre_corto']))}</li>"
                for q in proximos)
            lista = f"<ul>{filas}</ul>"
        else:
            lista = ("<p class='vacio'>La FBM todavía no ha publicado partidos de este equipo. "
                     "El calendario se rellenará solo en cuanto aparezcan.</p>")
        tarjetas.append(f"""
      <section class="card" style="--c:{cfg['color']}">
        <h2>{escape(cfg['nombre_calendario'])}</h2>
        <a class="btn" data-ics="{cfg['archivo_ics']}" href="{cfg['archivo_ics']}">Suscribirse en Apple Calendar</a>
        <p class="url">Enlace para otros calendarios: <code data-url="{cfg['archivo_ics']}">{cfg['archivo_ics']}</code></p>
        <h3>Próximos partidos</h3>{lista}
      </section>""")

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calendarios CB Arganda</title>
<style>
  :root {{ --bg:#f6f7f9; --fg:#1b1f24; --muted:#5b6470; --card:#fff; --line:#e3e6ea; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1115; --fg:#e8eaed; --muted:#9aa3ad; --card:#181b21; --line:#2a2f37; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:760px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 24px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-top:4px solid var(--c); border-radius:12px; padding:18px; margin-bottom:18px; }}
  .card h2 {{ font-size:1.2rem; margin:0 0 12px; }}
  .card h3 {{ font-size:.95rem; color:var(--muted); margin:16px 0 6px; }}
  .btn {{ display:inline-block; background:var(--c); color:#fff; text-decoration:none; padding:10px 16px; border-radius:8px; font-weight:600; }}
  .url {{ font-size:.85rem; color:var(--muted); overflow-wrap:anywhere; }}
  ul {{ list-style:none; padding:0; margin:0; }}
  li {{ padding:8px 0; border-bottom:1px solid var(--line); }}
  li:last-child {{ border-bottom:0; }}
  .f {{ display:block; font-size:.85rem; color:var(--muted); }}
  .vacio {{ color:var(--muted); }}
  details {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 18px; margin-bottom:12px; }}
  summary {{ cursor:pointer; font-weight:600; }}
  footer {{ color:var(--muted); font-size:.85rem; margin-top:24px; }}
</style>
</head>
<body>
<main>
  <h1>🏀 Calendarios CB Arganda</h1>
  <p class="sub">Partidos oficiales de la Federación de Baloncesto de Madrid. Se comprueban automáticamente cada lunes y viernes a las 17:05 (hora de Madrid).</p>
  {''.join(tarjetas)}
  <details><summary>Cómo suscribirse en iPhone / iPad</summary>
    <p>Pulsa el botón del calendario desde el iPhone → «Suscribirse» → en «Cuenta» elige <b>iCloud</b> (así aparece también en el Mac y en el resto de dispositivos) → «Añadir».</p>
  </details>
  <details><summary>Cómo suscribirse en Mac</summary>
    <p>Pulsa el botón → se abre Calendario → en «Ubicación» elige <b>iCloud</b> y en «Actualización automática» elige <b>Cada 15 minutos</b> (o cada hora) → OK.</p>
  </details>
  <details><summary>Google Calendar / Outlook / Android</summary>
    <p>Copia el enlace del calendario y añádelo como «Desde URL» (Google Calendar web → Otros calendarios → + → Desde URL).</p>
  </details>
  <footer>Última actualización: {ahora:%d/%m/%Y %H:%M} (hora de Madrid) · Fuente: <a href="{config['fuente']['club_url']}">fbm.es</a></footer>
</main>
<script>
  const base = location.href.replace(/[#?].*$/, '').replace(/[^/]*$/, '');
  document.querySelectorAll('[data-ics]').forEach(a => a.href = base.replace(/^https?:/, 'webcal:') + a.dataset.ics);
  document.querySelectorAll('[data-url]').forEach(c => c.textContent = base + c.dataset.url);
</script>
</body>
</html>
"""
