from __future__ import annotations

import html
import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "recipes.json"
SQLITE_FILE = ROOT / "recetario.db"
FIELDS = ["id", "fecha", "quien", "plataforma", "nombre", "categoria", "ingredientes_principales", "ingredientes", "notas_origen", "enlace", "estado", "fit", "hecha", "foto", "notas"]


def normalize(recipe: dict) -> dict:
    return {
        "id": str(recipe.get("id", uuid.uuid4())), "fecha": recipe.get("fecha", ""), "quien": recipe.get("quien", ""),
        "plataforma": recipe.get("plataforma", ""), "nombre": recipe.get("nombre", "(sin nombre)"), "categoria": recipe.get("categoria", ""),
        "ingredientes_principales": recipe.get("ingredientes_principales", recipe.get("ingPrincipales", "")), "ingredientes": recipe.get("ingredientes", recipe.get("ingCompletos", "")),
        "notas_origen": recipe.get("notas_origen", recipe.get("notasChat", "")), "enlace": recipe.get("enlace", ""), "estado": recipe.get("estado", ""),
        "fit": bool(recipe.get("fit", False)), "hecha": bool(recipe.get("hecha", False)), "foto": recipe.get("foto", ""), "notas": recipe.get("notas", ""),
    }


class SQLiteStore:
    def __init__(self):
        self.db = sqlite3.connect(SQLITE_FILE, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        columns = ", ".join(f"{f} {'integer' if f in ('fit', 'hecha') else 'text'}" for f in FIELDS)
        self.db.execute(f"create table if not exists recipes ({columns}, primary key (id))")
        self.db.commit()
    def all(self): return [dict(row) for row in self.db.execute("select * from recipes order by nombre collate nocase")]
    def count(self): return self.db.execute("select count(*) from recipes").fetchone()[0]
    def upsert(self, recipe):
        values = [int(recipe[f]) if f in ("fit", "hecha") else recipe[f] for f in FIELDS]
        marks = ", ".join("?" for _ in FIELDS)
        updates = ", ".join(f"{f}=excluded.{f}" for f in FIELDS if f != "id")
        self.db.execute(f"insert into recipes ({', '.join(FIELDS)}) values ({marks}) on conflict(id) do update set {updates}", values)
        self.db.commit()
    def delete(self, recipe_id):
        self.db.execute("delete from recipes where id=?", (recipe_id,)); self.db.commit()


class SupabaseStore:
    def __init__(self, url, key):
        from supabase import create_client
        self.client = create_client(url, key)
    def all(self): return self.client.table("recipes").select("*").order("nombre").execute().data
    def count(self): return len(self.client.table("recipes").select("id").execute().data)
    def upsert(self, recipe): self.client.table("recipes").upsert(recipe).execute()
    def delete(self, recipe_id): self.client.table("recipes").delete().eq("id", recipe_id).execute()


def get_store():
    has_url = "supabase_url" in st.secrets
    has_key = "supabase_service_role_key" in st.secrets
    if has_url and has_key:
        return SupabaseStore(st.secrets["supabase_url"], st.secrets["supabase_service_role_key"]), "Supabase compartido"
    if has_url or has_key:
        raise RuntimeError("Falta uno de los secretos de Supabase: supabase_url y supabase_service_role_key son obligatorios.")
    return SQLiteStore(), "SQLite local (solo pruebas)"


def seed(store):
    if store.count(): return False
    for source in json.loads(DATA_FILE.read_text()): store.upsert(normalize(source))
    return True


def complete_missing_from_excel(store):
    """Completa una base existente sin sustituir las correcciones personales."""
    existing = {str(recipe["id"]): normalize(recipe) for recipe in store.all()}
    changed = 0
    for source in json.loads(DATA_FILE.read_text()):
        incoming = normalize(source)
        saved = existing.get(incoming["id"])
        if saved is None:
            # Una receta ausente puede haber sido borrada por la pareja: no la recreamos.
            continue
        updated = dict(saved)
        for field in ("nombre", "categoria", "ingredientes_principales", "ingredientes", "notas_origen", "enlace", "estado", "fecha", "quien", "plataforma", "foto"):
            if incoming[field] and (not updated[field] or updated[field] == "(sin nombre)"):
                updated[field] = incoming[field]
        if updated != saved:
            store.upsert(updated)
            changed += 1
    return changed


def platform_label(platform):
    return {"Instagram":"IG", "Facebook":"FB", "YouTube":"YT", "TikTok":"TT", "Manual":"A MANO"}.get(platform, "WEB")


def visible_title(recipe):
    title = (recipe.get("nombre") or "").strip()
    placeholder_markers = ("sin nombre", "contenido marcado como sensible", "sin ingredientes en el pie", "sin receta en el texto")
    if not title or any(marker in title.lower() for marker in placeholder_markers):
        return "Sin título"
    return title


def _lazy_embed_script(selector, script_src):
    """<script> que carga el SDK de embed de una red externa solo cuando el bloque
    entra en pantalla (IntersectionObserver), para no ralentizar el listado con
    decenas de tarjetas cargando SDKs de golpe."""
    return f'''<script>
new IntersectionObserver((entries, obs) => {{
  if (!entries[0].isIntersecting) return;
  obs.disconnect();
  const s = document.createElement("script");
  s.async = true; s.src = "{script_src}";
  document.body.appendChild(s);
}}, {{rootMargin: "200px"}}).observe(document.querySelector("{selector}"));
</script>'''


def source_preview(recipe):
    """Vistas previas de Instagram, TikTok, Facebook y YouTube: se muestran solas, como en
    la red original, pero de forma perezosa (ver _lazy_embed_script) para que el listado
    siga cargando rápido.

    Nota sobre Facebook: su plugin de vídeo (plugins/video.php) solo soporta el formato
    clásico facebook.com/videos/... — no incrusta Reels (/reel/...) ni enlaces "compartir"
    (/share/...), que es como llegan casi todos los enlaces de Facebook guardados aquí.
    En esos casos se avisa en vez de mostrar un iframe roto en blanco."""
    url = recipe["enlace"]
    if not url: return
    platform = recipe["plataforma"]
    if platform == "Instagram":
        components.html(f'''<blockquote id="embed" class="instagram-media" data-instgrm-permalink="{html.escape(url, quote=True)}" data-instgrm-version="14" style="background:#FFF;border:0;border-radius:10px;margin:0;max-width:540px;min-width:326px;padding:0;width:99.375%"></blockquote>
{_lazy_embed_script("#embed", "https://www.instagram.com/embed.js")}''', height=520, scrolling=True)
    elif platform == "TikTok":
        components.html(f'''<blockquote id="embed" class="tiktok-embed" cite="{html.escape(url, quote=True)}" style="max-width:605px;min-width:325px"><section></section></blockquote>
{_lazy_embed_script("#embed", "https://www.tiktok.com/embed.js")}''', height=740, scrolling=True)
    elif platform == "Facebook":
        if "/reel/" in url or "/share/" in url:
            st.markdown('<p class="source-note">Vista previa no disponible: Facebook no permite incrustar Reels ni enlaces "compartir". Usa «Ver receta original» para verla.</p>', unsafe_allow_html=True)
        else:
            components.html(f'<iframe src="https://www.facebook.com/plugins/video.php?href={quote(url, safe="")}&show_text=false" width="100%" height="420" style="border:none;overflow:hidden" scrolling="no" frameborder="0" loading="lazy" allowfullscreen="true"></iframe>', height=430)
    elif "youtube.com" in url or "youtu.be" in url:
        video = url.split("youtu.be/")[-1].split("?")[0] if "youtu.be/" in url else url.split("v=")[-1].split("&")[0]
        components.html(f'<iframe width="100%" height="315" src="https://www.youtube.com/embed/{html.escape(video)}" frameborder="0" loading="lazy" allowfullscreen></iframe>', height=325)


_LIGHT_PALETTE = {
    # Paleta "Recipe & Cooking App" (skill ui-ux-pro-max, --domain color): terracota vivo
    # como primario, esmeralda como acento, dorado para FIT, crema cálido de fondo.
    "ink": "#0F172A", "ink-soft": "#475569",
    "page": "#FFFBEB", "paper": "#FFFFFF", "paper2": "#F8F2F0",
    "clay": "#9A3412", "clay-deep": "#78280E", "on-clay": "#FFFFFF",
    "olive": "#059669", "olive-deep": "#065F46", "olive-soft": "#D1FAE5", "on-olive": "#0F172A",
    "gold": "#A16207", "gold-deep": "#854D0E", "gold-soft": "#FEF3C7", "on-gold": "#FFFFFF",
    "danger": "#DC2626", "danger-deep": "#B91C1C", "on-danger": "#FFFFFF",
    "line": "rgba(15,23,42,.13)", "shadow-1": "rgba(15,23,42,.06)", "shadow-2": "rgba(15,23,42,.07)",
}
_DARK_PALETTE = {
    # Mismos roles que _LIGHT_PALETTE, no una inversión literal: fondo cálido casi negro
    # (no azul-negro genérico) y los acentos se aclaran para destacar sobre fondo oscuro —
    # lo que invierte quién necesita texto claro/oscuro encima (ver los "on-*").
    "ink": "#F4ECE2", "ink-soft": "#C7B8A8",
    "page": "#1B140F", "paper": "#2A2019", "paper2": "#332720",
    "clay": "#F0713C", "clay-deep": "#F79764", "on-clay": "#1B140F",
    "olive": "#34D399", "olive-deep": "#6EE7B7", "olive-soft": "#113B2C", "on-olive": "#1B140F",
    "gold": "#FBBF24", "gold-deep": "#FCD34D", "gold-soft": "#3A2A08", "on-gold": "#1B140F",
    "danger": "#F87171", "danger-deep": "#FCA5A5", "on-danger": "#1B140F",
    "line": "rgba(244,236,226,.14)", "shadow-1": "rgba(0,0,0,.30)", "shadow-2": "rgba(0,0,0,.40)",
}


def inject_style():
    # st.context.theme.type refleja el tema real que ve la persona (claro/oscuro/auto de su
    # SO, o lo que haya elegido a mano en el menú de Streamlit) — así no hace falta duplicar
    # esa lógica con un @media(prefers-color-scheme) que solo vería el SO, no el ajuste manual.
    theme = getattr(getattr(st.context, "theme", None), "type", None) or "light"
    palette = _DARK_PALETTE if theme == "dark" else _LIGHT_PALETTE
    tokens = ";".join(f"--{name}:{value}" for name, value in palette.items())
    st.markdown(f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@500&family=Inter:wght@400;500;600;700&display=swap');
    :root {{ {tokens}; }}
    .stApp {{background:var(--page);color:var(--ink);font-family:Inter,sans-serif}}.block-container{{max-width:920px;padding-top:1.7rem;padding-bottom:4rem}}h1,h2,h3{{font-family:Fraunces,serif!important;color:var(--clay-deep)!important}}h1{{font-weight:600!important;letter-spacing:-.02em}}[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{{display:none!important}}
    div[data-testid="stExpander"]{{background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 2px var(--shadow-1),0 6px 16px var(--shadow-2)}}div[data-testid="stExpander"] details summary{{padding:.75rem .9rem;font-family:Fraunces,serif;font-size:1.1rem}}div[data-testid="stExpander"] details[open] summary{{border-bottom:1px solid var(--line)}}
    [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea{{background:var(--paper2);border-color:var(--line);color:var(--ink)}}[data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus{{border-color:var(--clay);box-shadow:0 0 0 1px var(--clay)}}
    .stButton button,[data-testid="stLinkButton"] a{{border-radius:9px;border:0;background:var(--clay);color:var(--on-clay);font-family:Inter,sans-serif;font-weight:600;white-space:nowrap}}.stButton button:hover,[data-testid="stLinkButton"] a:hover{{background:var(--clay-deep);color:var(--on-clay);border:0}}.stPills [data-baseweb="tag"]{{background:var(--paper);border:2px solid var(--olive-deep);border-radius:999px;color:var(--olive-deep);font-weight:700;padding:6px 12px}}.stPills [aria-pressed="true"]{{background:var(--olive)!important;color:var(--on-olive)!important;border-color:var(--olive)!important}}
    [data-testid="stVerticalBlockBorderWrapper"]{{background:var(--paper);border-color:var(--line)!important;border-radius:14px!important;box-shadow:0 1px 2px var(--shadow-1),0 6px 16px var(--shadow-2)}}.recipe-name{{font-family:Fraunces,serif;font-weight:500;font-size:1.65rem;line-height:1.25;color:var(--ink);margin:-.35rem 0 .8rem}}.recipe-meta{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin:.1rem 0 .8rem}}.cat{{display:inline-block;font:600 11px Inter,sans-serif;letter-spacing:.03em;text-transform:uppercase;color:var(--olive-deep);background:var(--olive-soft);padding:3px 8px;border-radius:6px}}.cat.empty{{background:var(--paper2);color:var(--ink-soft)}}.stamp{{border:1px dashed var(--line);border-radius:8px;padding:4px 7px;font:10px/1.45 'IBM Plex Mono',monospace;color:var(--ink-soft);text-align:right;transform:rotate(2deg)}}.stamp b{{color:var(--clay)}}.recipe-preview{{color:var(--ink-soft);font-size:.9rem;line-height:1.5;white-space:pre-wrap}}.source-action-space{{height:.7rem}}.source-note{{color:var(--ink-soft);font-size:.85rem;font-style:italic}}
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .delete-confirm-marker) [data-testid="stButton"] button{{background:var(--danger)!important;color:var(--on-danger)!important}}div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .delete-confirm-marker) [data-testid="stButton"] button:hover{{background:var(--danger-deep)!important}}
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .fit-badge-marker) .stPills [data-baseweb="tag"]{{background:var(--gold-soft)!important;border:0!important;border-radius:6px!important;color:var(--gold-deep)!important;font:600 11px Inter,sans-serif!important;letter-spacing:.03em!important;text-transform:uppercase!important;padding:3px 8px!important;min-height:0!important}}div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .fit-badge-marker) .stPills [aria-pressed="true"]{{background:var(--gold)!important;color:var(--on-gold)!important}}
    header[data-testid="stHeader"]{{background:var(--page)!important;border-bottom:1px solid var(--line)}}header[data-testid="stHeader"]:before{{content:"El recetario";position:absolute;left:1rem;top:.45rem;font-family:Fraunces,serif;font-weight:600;font-size:1.45rem;color:var(--clay-deep);z-index:1000}}div[data-testid="stElementContainer"]:has(.actions-row-marker),div[data-testid="stElementContainer"]:has(.recipe-chip-marker),div[data-testid="stElementContainer"]:has(.recipe-grid-marker),div[data-testid="stElementContainer"]:has(.recetario-sticky-marker),div[data-testid="stElementContainer"]:has(.delete-confirm-marker),div[data-testid="stElementContainer"]:has(.fit-badge-marker){{display:none!important}}[data-testid="stVerticalBlock"]:has(.recetario-sticky-marker){{position:sticky;top:0;z-index:90;background:var(--page);padding:8px 0 10px;border-bottom:1px solid var(--line)}}div[data-testid="stHorizontalBlock"]:has(.actions-row-marker),div[data-testid="stHorizontalBlock"]:has(.recipe-chip-marker){{flex-wrap:nowrap!important;gap:.45rem!important}}div[data-testid="stHorizontalBlock"]:has(.actions-row-marker)>div,div[data-testid="stHorizontalBlock"]:has(.recipe-chip-marker)>div{{min-width:0!important}}
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .infinite-scroll-marker){{display:none!important}}
    @media(max-width:600px){{.block-container{{padding-left:16px;padding-right:16px;padding-top:.45rem}}header[data-testid="stHeader"]:before{{font-size:1.2rem;top:.55rem}}.stPills [data-baseweb="tag"]{{font-size:.72rem!important;padding:6px 10px!important;min-height:30px;letter-spacing:0!important;margin:0!important}}.stPills [data-baseweb="tag"] span{{line-height:1.2!important}}.stButton button,[data-testid="stLinkButton"] a{{font-size:.88rem;padding:.68rem .6rem;min-height:44px}}.recipe-name{{font-size:1.5rem}}div[data-testid="stHorizontalBlock"]:has(.recipe-grid-marker){{flex-direction:column!important;gap:.75rem!important}}div[data-testid="stHorizontalBlock"]:has(.recipe-grid-marker)>div{{width:100%!important;flex:1 1 100%!important}}.source-action-space{{height:.55rem}}}}
    </style>""", unsafe_allow_html=True)


def inject_scroll_to_top():
    """Inyecta un botón flotante 'volver arriba' directamente en el documento de Streamlit
    (no en el iframe de este componente, para que quede fijo sobre toda la pantalla).
    Es idempotente: si ya existe (de una ejecución anterior de Streamlit) no lo duplica."""
    components.html("""<script>
(function() {
  const doc = window.parent.document;
  if (doc.getElementById("recetario-top-btn")) return;
  const root = doc.documentElement;
  const clay = getComputedStyle(root).getPropertyValue("--clay").trim() || "#9A3412";
  const clayDeep = getComputedStyle(root).getPropertyValue("--clay-deep").trim() || "#78280E";
  const onClay = getComputedStyle(root).getPropertyValue("--on-clay").trim() || "#FFFFFF";
  const style = doc.createElement("style");
  style.textContent = `
    #recetario-top-btn { position: fixed; right: 20px; bottom: 24px; z-index: 9999;
      width: 46px; height: 46px; border-radius: 50%; border: 0; background: ${clay}; color: ${onClay};
      display: flex; align-items: center; justify-content: center; cursor: pointer;
      box-shadow: 0 6px 20px rgba(0,0,0,.25); opacity: 0; pointer-events: none;
      transform: translateY(8px); transition: opacity .2s ease, transform .2s ease, background .2s ease; }
    #recetario-top-btn.show { opacity: 1; pointer-events: auto; transform: translateY(0); }
    #recetario-top-btn:hover { background: ${clayDeep}; }
    #recetario-top-btn:focus-visible { outline: 2px solid ${clayDeep}; outline-offset: 2px; }
  `;
  doc.head.appendChild(style);
  const btn = doc.createElement("button");
  btn.id = "recetario-top-btn";
  btn.setAttribute("aria-label", "Volver arriba");
  btn.setAttribute("title", "Volver arriba");
  btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  // No sabemos de antemano qué contenedor es el que realmente hace scroll en esta versión de
  // Streamlit, así que probamos varios candidatos conocidos y actuamos sobre todos: es inofensivo
  // pedirle scrollTo(0) a uno que ya está arriba.
  const scrollers = () => [
    doc.querySelector('section[data-testid="stMain"]'),
    doc.querySelector('[data-testid="stAppViewContainer"]'),
    doc.scrollingElement,
    doc.documentElement,
  ].filter(Boolean);
  btn.addEventListener("click", () => {
    const reduceMotion = window.parent.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const behavior = reduceMotion ? "auto" : "smooth";
    scrollers().forEach((el) => el.scrollTo({top: 0, behavior}));
  });
  doc.body.appendChild(btn);
  const toggle = (e) => {
    const targetY = (e && e.target && "scrollTop" in e.target) ? e.target.scrollTop : 0;
    const y = Math.max(targetY, ...scrollers().map((el) => el.scrollTop || 0));
    btn.classList.toggle("show", y > 600);
  };
  doc.addEventListener("scroll", toggle, {capture: true, passive: true});
  toggle();
})();
</script>""", height=0)


def recipe_form(store, recipe, key, new=False):
    with st.form(key, clear_on_submit=new):
        name = st.text_input("Nombre de la receta *", recipe.get("nombre", ""))
        ingredients = st.text_area("Ingredientes", recipe.get("ingredientes", ""), height=130, placeholder="Añade o corrige los ingredientes…")
        source_url = st.text_input("Enlace original", recipe.get("enlace", ""), placeholder="https://…")
        notes = st.text_area("Vuestras notas", recipe.get("notas", ""), height=80, placeholder="Cambios que hicisteis, si merece la pena repetirla…")
        st.caption("Detalles de origen")
        category = st.text_input("Categoría", recipe.get("categoria", "")); author = st.text_input("Quién la añade", recipe.get("quien", "")); source_date = st.text_input("Fecha", recipe.get("fecha", "")); tags = st.text_input("Ingredientes principales / etiquetas", recipe.get("ingredientes_principales", ""))
        submitted = st.form_submit_button("Guardar receta", type="primary", icon=":material/save:")
    if submitted:
        if not name.strip(): st.error("Ponle un nombre a la receta.", icon=":material/error:"); return
        with st.spinner("Guardando…"):
            store.upsert(normalize({"id":recipe.get("id",str(uuid.uuid4())),"nombre":name.strip(),"ingCompletos":ingredients,"hecha":recipe.get("hecha", False),"fit":recipe.get("fit", False),"enlace":source_url.strip(),"foto":recipe.get("foto", ""),"notas":notes,"categoria":category.strip(),"quien":author.strip(),"plataforma":recipe.get("plataforma", "Manual"),"fecha":source_date.strip(),"estado":recipe.get("estado", ""),"ingPrincipales":tags.strip()}))
        st.rerun()


def render_recipe(store, recipe):
    category = html.escape(recipe["categoria"] or "Sin categoría")
    category_class = " empty" if not recipe["categoria"] else ""
    title = visible_title(recipe)
    with st.container(border=True):
        category_column, fit_column = st.columns([3, 1])
        with category_column:
            st.markdown('<div class="recipe-chip-marker"></div>', unsafe_allow_html=True)
            st.markdown(f'<span class="cat{category_class}">{category}</span>', unsafe_allow_html=True)
        with fit_column:
            st.markdown('<div class="fit-badge-marker"></div>', unsafe_allow_html=True)
            selected_fit = st.pills("FIT", ["FIT"], default=["FIT"] if recipe["fit"] else [], selection_mode="multi", label_visibility="collapsed", key=f"fit_{recipe['id']}")
            if bool(selected_fit) != recipe["fit"]:
                updated = dict(recipe); updated["fit"] = bool(selected_fit)
                with st.spinner("Guardando…"): store.upsert(updated)
                st.rerun()
        st.markdown(f'<div class="recipe-name">{html.escape(title)}</div>', unsafe_allow_html=True)
        if recipe["foto"]:
            st.markdown(f'<img src="{html.escape(recipe["foto"], quote=True)}" alt="{html.escape(title)}" loading="lazy" style="width:100%;border-radius:10px;display:block" onerror="this.style.display=\'none\'">', unsafe_allow_html=True)
        preview = recipe["ingredientes"] or recipe["ingredientes_principales"] or "Sin ingredientes"
        st.markdown(f'<div class="recipe-preview">{html.escape(preview)}</div>', unsafe_allow_html=True)
        if recipe["notas_origen"]: st.markdown(f'<p class="source-note">Notas del chat: {html.escape(recipe["notas_origen"])}</p>', unsafe_allow_html=True)
        if recipe["enlace"]:
            st.markdown('<div class="source-action-space"></div>', unsafe_allow_html=True)
            st.link_button("Ver receta original", recipe["enlace"], icon=":material/open_in_new:", use_container_width=True)
            source_preview(recipe)
        with st.expander("Editar receta y más detalles"):
            recipe_form(store, recipe, f"edit_{recipe['id']}")
            confirm_key = f"confirm_delete_{recipe['id']}"
            if not st.session_state.get(confirm_key, False):
                if st.button("Eliminar esta receta", key=f"delete_{recipe['id']}", icon=":material/delete:"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"¿Eliminar «{title}»? No se puede deshacer.", icon=":material/warning:")
                cancel_column, confirm_column = st.columns(2)
                with cancel_column:
                    st.markdown('<div class="actions-row-marker"></div>', unsafe_allow_html=True)
                    if st.button("Cancelar", key=f"cancel_{recipe['id']}", use_container_width=True):
                        st.session_state[confirm_key] = False
                        st.rerun()
                with confirm_column:
                    st.markdown('<div class="delete-confirm-marker"></div>', unsafe_allow_html=True)
                    if st.button("Sí, eliminar", key=f"confirm_{recipe['id']}", icon=":material/delete_forever:", use_container_width=True):
                        with st.spinner("Eliminando…"): store.delete(recipe["id"])
                        st.session_state.pop(confirm_key, None)
                        st.rerun()


st.set_page_config(page_title="El recetario", page_icon="🍳", layout="wide", initial_sidebar_state="collapsed")
inject_style()
inject_scroll_to_top()
try:
    store, storage_name = get_store()
    imported = seed(store); recipes = [normalize(row) for row in store.all()]
except Exception as exc:
    st.error("No se pudo conectar a la base de datos. Ejecuta schema.sql en Supabase y revisa los secretos."); st.exception(exc); st.stop()

with st.container():
    st.markdown('<div class="recetario-sticky-marker"></div>', unsafe_allow_html=True)
    st.caption(f"{len(recipes)} recetas")
    if imported: st.success("Recetas iniciales importadas.")
    action_left, action_right = st.columns(2)
    with action_left:
        st.markdown('<div class="actions-row-marker"></div>', unsafe_allow_html=True)
        if st.button("Actualizar", key="refresh", icon=":material/refresh:", use_container_width=True):
            with st.spinner("Actualizando…"): complete_missing_from_excel(store)
            st.rerun()
    with action_right:
        if st.button("Nueva receta", key="new_recipe_button", icon=":material/add:", use_container_width=True):
            st.session_state.show_new_recipe = not st.session_state.get("show_new_recipe", False)
    search = st.text_input("Buscar", placeholder="Buscar por nombre o ingrediente…", label_visibility="collapsed", icon=":material/search:", key="search_query")
    categories = sorted({r["categoria"] for r in recipes if r["categoria"]})
    selected = st.pills("Categorías", ["Todas", "FIT"] + categories, default="Todas", selection_mode="single", label_visibility="collapsed", key="category_filter")
query = search.lower().strip()
def matches(recipe):
    haystack = " ".join(str(recipe.get(field, "")) for field in ("nombre", "ingredientes", "ingredientes_principales", "notas")).lower()
    return (not query or query in haystack) and (selected != "FIT" or recipe["fit"]) and (selected in ("Todas", "FIT") or recipe["categoria"] == selected)
visible = [r for r in recipes if matches(r)]
st.caption(f"{len(visible)} de {len(recipes)} recetas")
if st.session_state.get("show_new_recipe", False):
    with st.expander("Nueva receta", expanded=True):
        recipe_form(store, {"id":str(uuid.uuid4()),"fecha":date.today().strftime("%-d/%-m/%y"),"plataforma":"Manual","estado":"Añadida a mano"}, "new_recipe", True)

if not recipes:
    with st.container(border=True):
        st.markdown("##### Aún no hay recetas")
        st.write("Añade la primera con el botón “Nueva receta” de arriba.")
elif not visible:
    with st.container(border=True):
        st.markdown("##### Ninguna receta coincide")
        st.write("Prueba con otra palabra o quita el filtro de categoría.")
        if st.button("Quitar filtros", key="reset_filters", icon=":material/filter_alt_off:"):
            st.session_state.search_query = ""
            st.session_state.category_filter = "Todas"
            st.rerun()

page_size = 12
if "recipes_visible_count" not in st.session_state:
    st.session_state.recipes_visible_count = page_size
visible_page = visible[:st.session_state.recipes_visible_count]
for start in range(0, len(visible_page), 2):
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="recipe-grid-marker"></div>', unsafe_allow_html=True)
        render_recipe(store, visible_page[start])
    if start + 1 < len(visible_page):
        with right: render_recipe(store, visible_page[start + 1])
if len(visible_page) < len(visible):
    # Scroll infinito sin paquete adicional: el botón real de Streamlit sigue ahí (funciona
    # exactamente igual que antes) pero queda oculto por CSS; un centinela justo debajo, con
    # IntersectionObserver, le hace click() por nosotros en cuanto entra en pantalla — mismo
    # documento (components.html es same-origin), sin protocolo interno de Streamlit de por medio.
    with st.container():
        st.markdown('<div class="infinite-scroll-marker"></div>', unsafe_allow_html=True)
        if st.button("Cargar más recetas", key="load_more_recipes", icon=":material/expand_more:"):
            st.session_state.recipes_visible_count += page_size
            st.rerun()
    components.html("""<div id="scroll-sentinel" style="height:1px"></div>
<script>
(function() {
  const doc = window.parent.document;
  const markers = doc.querySelectorAll(".infinite-scroll-marker");
  const marker = markers[markers.length - 1];
  const btn = marker && marker.closest('[data-testid="stVerticalBlock"]')?.querySelector("button");
  if (!btn) return;
  new IntersectionObserver((entries, obs) => {
    if (!entries[0].isIntersecting) return;
    obs.disconnect();
    btn.click();
  }, {rootMargin: "800px"}).observe(document.getElementById("scroll-sentinel"));
})();
</script>""", height=1)
