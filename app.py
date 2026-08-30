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


def source_preview(recipe):
    """Mantiene las vistas previas de Instagram, Facebook y YouTube del HTML original."""
    url = recipe["enlace"]
    if not url: return
    if recipe["plataforma"] == "Instagram":
        components.html(f'''<blockquote class="instagram-media" data-instgrm-permalink="{html.escape(url, quote=True)}" data-instgrm-version="14" style="background:#FFF;border:0;border-radius:10px;margin:0;max-width:540px;min-width:326px;padding:0;width:99.375%"></blockquote><script async src="https://www.instagram.com/embed.js"></script>''', height=520, scrolling=True)
    elif recipe["plataforma"] == "Facebook":
        components.html(f'<iframe src="https://www.facebook.com/plugins/video.php?href={quote(url, safe="")}&show_text=false" width="100%" height="420" style="border:none;overflow:hidden" scrolling="no" frameborder="0" allowfullscreen="true"></iframe>', height=430)
    elif "youtube.com" in url or "youtu.be" in url:
        video = url.split("youtu.be/")[-1].split("?")[0] if "youtu.be/" in url else url.split("v=")[-1].split("&")[0]
        components.html(f'<iframe width="100%" height="315" src="https://www.youtube.com/embed/{html.escape(video)}" frameborder="0" allowfullscreen></iframe>', height=325)


def inject_style():
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@500&family=Inter:wght@400;500;600;700&display=swap');
    :root { --ink:#2B2620;--ink-soft:#5C5346;--page:#EEE6D6;--paper:#FBF7EE;--paper2:#F4EDDC;--clay:#B5541B;--clay-deep:#8F3F13;--olive:#5B6B4F;--olive-soft:#DCE3D3;--line:rgba(43,38,32,.14); }
    .stApp {background:var(--page);color:var(--ink);font-family:Inter,sans-serif}.block-container{max-width:920px;padding-top:1.7rem;padding-bottom:4rem}h1,h2,h3{font-family:Fraunces,serif!important;color:var(--clay-deep)!important}h1{font-weight:600!important;letter-spacing:-.02em}[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none!important}
    div[data-testid="stExpander"]{background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 2px rgba(43,38,32,.06),0 6px 16px rgba(43,38,32,.07)}div[data-testid="stExpander"] details summary{padding:.75rem .9rem;font-family:Fraunces,serif;font-size:1.1rem}div[data-testid="stExpander"] details[open] summary{border-bottom:1px solid var(--line)}
    [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea{background:var(--paper2);border-color:var(--line);color:var(--ink)}[data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus{border-color:var(--clay);box-shadow:0 0 0 1px var(--clay)}
    .stButton button,[data-testid="stLinkButton"] a{border-radius:9px;border:0;background:var(--clay);color:white;font-family:Inter,sans-serif;font-weight:600;white-space:nowrap}.stButton button:hover,[data-testid="stLinkButton"] a:hover{background:var(--clay-deep);color:white;border:0}.stPills [data-baseweb="tag"]{background:var(--paper);border:2px solid var(--olive);border-radius:999px;color:var(--olive);font-weight:700;padding:6px 12px}.stPills [aria-pressed="true"]{background:var(--olive)!important;color:white!important;border-color:var(--olive)!important}
    [data-testid="stVerticalBlockBorderWrapper"]{background:var(--paper);border-color:var(--line)!important;border-radius:14px!important;box-shadow:0 1px 2px rgba(43,38,32,.06),0 6px 16px rgba(43,38,32,.07)}.recipe-name{font-family:Fraunces,serif;font-weight:500;font-size:1.65rem;line-height:1.25;color:var(--ink);margin:-.35rem 0 .8rem}.recipe-meta{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin:.1rem 0 .8rem}.cat{display:inline-block;font:600 11px Inter,sans-serif;letter-spacing:.03em;text-transform:uppercase;color:var(--olive);background:var(--olive-soft);padding:3px 8px;border-radius:6px}.cat.empty{background:var(--paper2);color:var(--ink-soft)}.stamp{border:1px dashed var(--line);border-radius:8px;padding:4px 7px;font:10px/1.45 'IBM Plex Mono',monospace;color:var(--ink-soft);text-align:right;transform:rotate(2deg)}.stamp b{color:var(--clay)}.recipe-preview{color:var(--ink-soft);font-size:.9rem;line-height:1.5;white-space:pre-wrap}.source-action-space{height:.7rem}.status{font-size:.78rem;color:var(--ink-soft)}.made{color:#5B8A56;font-weight:600}.pending{color:#9a7212;font-weight:600}.source-note{color:var(--ink-soft);font-size:.85rem;font-style:italic}
    </style>""", unsafe_allow_html=True)


def recipe_form(store, recipe, key, new=False):
    with st.form(key, clear_on_submit=new):
        name = st.text_input("Nombre de la receta *", recipe.get("nombre", ""))
        ingredients = st.text_area("Ingredientes", recipe.get("ingredientes", ""), height=130, placeholder="Añade o corrige los ingredientes…")
        source_url = st.text_input("Enlace original", recipe.get("enlace", ""), placeholder="https://…")
        notes = st.text_area("Vuestras notas", recipe.get("notas", ""), height=80, placeholder="Cambios que hicisteis, si merece la pena repetirla…")
        st.caption("Detalles de origen")
        category = st.text_input("Categoría", recipe.get("categoria", "")); author = st.text_input("Quién la añade", recipe.get("quien", "")); source_date = st.text_input("Fecha", recipe.get("fecha", "")); tags = st.text_input("Ingredientes principales / etiquetas", recipe.get("ingredientes_principales", ""))
        submitted = st.form_submit_button("Guardar receta", type="primary")
    if submitted:
        if not name.strip(): st.error("Ponle un nombre a la receta."); return
        store.upsert(normalize({"id":recipe.get("id",str(uuid.uuid4())),"nombre":name.strip(),"ingCompletos":ingredients,"hecha":recipe.get("hecha", False),"fit":recipe.get("fit", False),"enlace":source_url.strip(),"foto":recipe.get("foto", ""),"notas":notes,"categoria":category.strip(),"quien":author.strip(),"plataforma":recipe.get("plataforma", "Manual"),"fecha":source_date.strip(),"estado":recipe.get("estado", ""),"ingPrincipales":tags.strip()})); st.rerun()


def render_recipe(store, recipe):
    category = html.escape(recipe["categoria"] or "Sin categoría")
    category_class = " empty" if not recipe["categoria"] else ""
    with st.container(border=True):
        category_column, fit_column = st.columns([5, 1])
        with category_column:
            st.markdown(f'<span class="cat{category_class}">{category}</span>', unsafe_allow_html=True)
        with fit_column:
            selected_fit = st.pills("FIT", ["FIT"], default=["FIT"] if recipe["fit"] else [], selection_mode="multi", label_visibility="collapsed", key=f"fit_{recipe['id']}")
            if bool(selected_fit) != recipe["fit"]:
                updated = dict(recipe)
                updated["fit"] = bool(selected_fit)
                store.upsert(updated)
                st.rerun()
        st.markdown(f'<div class="recipe-name">{html.escape(visible_title(recipe))}</div>', unsafe_allow_html=True)
        if recipe["foto"]: st.image(recipe["foto"], use_container_width=True)
        preview = recipe["ingredientes"] or recipe["ingredientes_principales"] or "Sin ingredientes"
        st.markdown(f'<div class="recipe-preview">{html.escape(preview)}</div>', unsafe_allow_html=True)
        if recipe["notas_origen"]: st.markdown(f'<p class="source-note">Notas del chat: {html.escape(recipe["notas_origen"])}</p>', unsafe_allow_html=True)
        if recipe["enlace"]:
            st.markdown('<div class="source-action-space"></div>', unsafe_allow_html=True)
            st.link_button("Ver receta original →", recipe["enlace"])
            video_key = f"video_{recipe['id']}"
            if not st.session_state.get(video_key, False):
                if st.button("Cargar vídeo", key=f"load_{recipe['id']}"):
                    st.session_state[video_key] = True
                    st.rerun()
            if st.session_state.get(video_key, False):
                source_preview(recipe)
        with st.expander("Editar receta y más detalles"):
            recipe_form(store, recipe, f"edit_{recipe['id']}")
            if st.button("Eliminar esta receta", key=f"delete_{recipe['id']}"): store.delete(recipe["id"]); st.rerun()


st.set_page_config(page_title="El recetario", page_icon="🍳", layout="wide", initial_sidebar_state="collapsed")
inject_style()
try:
    store, storage_name = get_store()
    imported = seed(store); recipes = [normalize(row) for row in store.all()]
except Exception as exc:
    st.error("No se pudo conectar a la base de datos. Ejecuta schema.sql en Supabase y revisa los secretos."); st.exception(exc); st.stop()

st.markdown("<h1>El recetario</h1>", unsafe_allow_html=True)
st.caption(f"{len(recipes)} recetas")
if imported: st.success("Recetas iniciales importadas.")
action_left, action_right, _ = st.columns([1.25, 1.6, 4.15])
with action_left:
    if st.button("↻ Actualizar", key="refresh"):
        complete_missing_from_excel(store)
        st.rerun()
with action_right:
    if st.button("＋ Nueva receta", key="new_recipe_button"):
        st.session_state.show_new_recipe = not st.session_state.get("show_new_recipe", False)
search = st.text_input("Buscar", placeholder="Buscar por nombre o ingrediente…", label_visibility="collapsed")
categories = sorted({r["categoria"] for r in recipes if r["categoria"]})
selected = st.pills("Categorías", ["Todas", "FIT"] + categories, default="Todas", selection_mode="single", label_visibility="collapsed")
query = search.lower().strip()
def matches(recipe):
    haystack = " ".join(str(recipe.get(field, "")) for field in ("nombre", "ingredientes", "ingredientes_principales", "notas")).lower()
    return (not query or query in haystack) and (selected != "FIT" or recipe["fit"]) and (selected in ("Todas", "FIT") or recipe["categoria"] == selected)
visible = [r for r in recipes if matches(r)]
st.caption(f"{len(visible)} de {len(recipes)} recetas")
if st.session_state.get("show_new_recipe", False):
    with st.expander("Nueva receta", expanded=True):
        recipe_form(store, {"id":str(uuid.uuid4()),"fecha":date.today().strftime("%-d/%-m/%y"),"plataforma":"Manual","estado":"Añadida a mano"}, "new_recipe", True)

page_size = 12
if "recipes_visible_count" not in st.session_state:
    st.session_state.recipes_visible_count = page_size
visible_page = visible[:st.session_state.recipes_visible_count]
for start in range(0, len(visible_page), 2):
    left, right = st.columns(2)
    with left: render_recipe(store, visible_page[start])
    if start + 1 < len(visible_page):
        with right: render_recipe(store, visible_page[start + 1])
if len(visible_page) < len(visible):
    if st.button("Cargar más recetas", key="load_more_recipes"):
        st.session_state.recipes_visible_count += page_size
        st.rerun()
