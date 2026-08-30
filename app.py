from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "recipes.json"
SQLITE_FILE = ROOT / "recetario.db"

FIELDS = [
    "id", "fecha", "quien", "plataforma", "nombre", "categoria",
    "ingredientes_principales", "ingredientes", "notas_origen", "enlace",
    "estado", "fit", "hecha", "foto", "notas",
]


def normalize(recipe: dict) -> dict:
    """Adapta el formato del HTML original al de la aplicación."""
    return {
        "id": str(recipe.get("id", uuid.uuid4())),
        "fecha": recipe.get("fecha", ""),
        "quien": recipe.get("quien", ""),
        "plataforma": recipe.get("plataforma", ""),
        "nombre": recipe.get("nombre", "(sin nombre)"),
        "categoria": recipe.get("categoria", ""),
        "ingredientes_principales": recipe.get("ingredientes_principales", recipe.get("ingPrincipales", "")),
        "ingredientes": recipe.get("ingredientes", recipe.get("ingCompletos", "")),
        "notas_origen": recipe.get("notas_origen", recipe.get("notasChat", "")),
        "enlace": recipe.get("enlace", ""),
        "estado": recipe.get("estado", ""),
        "fit": bool(recipe.get("fit", False)),
        "hecha": bool(recipe.get("hecha", False)),
        "foto": recipe.get("foto", ""),
        "notas": recipe.get("notas", ""),
    }


class SQLiteStore:
    def __init__(self):
        self.db = sqlite3.connect(SQLITE_FILE, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        columns = ", ".join(
            f"{field} {'integer' if field in ('fit', 'hecha') else 'text'}"
            for field in FIELDS
        )
        self.db.execute(f"create table if not exists recipes ({columns}, primary key (id))")
        self.db.commit()

    def all(self):
        return [dict(row) for row in self.db.execute("select * from recipes order by nombre collate nocase")]

    def count(self):
        return self.db.execute("select count(*) from recipes").fetchone()[0]

    def upsert(self, recipe):
        values = [int(recipe[field]) if field in ("fit", "hecha") else recipe[field] for field in FIELDS]
        placeholders = ", ".join("?" for _ in FIELDS)
        updates = ", ".join(f"{field}=excluded.{field}" for field in FIELDS if field != "id")
        self.db.execute(f"insert into recipes ({', '.join(FIELDS)}) values ({placeholders}) on conflict(id) do update set {updates}", values)
        self.db.commit()

    def delete(self, recipe_id):
        self.db.execute("delete from recipes where id=?", (recipe_id,))
        self.db.commit()


class SupabaseStore:
    def __init__(self, url, key):
        from supabase import create_client
        self.client = create_client(url, key)

    def all(self):
        return self.client.table("recipes").select("*").order("nombre").execute().data

    def count(self):
        return len(self.client.table("recipes").select("id").execute().data)

    def upsert(self, recipe):
        self.client.table("recipes").upsert(recipe).execute()

    def delete(self, recipe_id):
        self.client.table("recipes").delete().eq("id", recipe_id).execute()


def get_store():
    if "supabase_url" in st.secrets and "supabase_service_role_key" in st.secrets:
        return SupabaseStore(st.secrets["supabase_url"], st.secrets["supabase_service_role_key"]), "Supabase compartido"
    return SQLiteStore(), "SQLite local (solo pruebas)"


def require_password():
    password = st.secrets.get("access_password", "")
    if not password:
        return
    if st.session_state.get("allowed"):
        return
    st.title("El recetario")
    entered = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if entered == password:
            st.session_state.allowed = True
            st.rerun()
        st.error("Contraseña incorrecta")
    st.stop()


def seed(store):
    if store.count():
        return False
    recipes = [normalize(item) for item in json.loads(DATA_FILE.read_text())]
    for recipe in recipes:
        store.upsert(recipe)
    return True


def recipe_form(store, recipe: dict, key: str, is_new=False):
    with st.form(key, clear_on_submit=is_new):
        left, right = st.columns(2)
        with left:
            name = st.text_input("Nombre *", recipe.get("nombre", ""))
            category = st.text_input("Categoría", recipe.get("categoria", ""))
            author = st.text_input("Añadida por", recipe.get("quien", ""))
        with right:
            platform = st.text_input("Plataforma", recipe.get("plataforma", "Manual"))
            source_date = st.text_input("Fecha", recipe.get("fecha", ""))
            status = st.text_input("Estado", recipe.get("estado", ""))
        ingredients = st.text_area("Ingredientes", recipe.get("ingredientes", ""), height=140)
        main_ingredients = st.text_input("Ingredientes principales / etiquetas", recipe.get("ingredientes_principales", ""))
        source_url = st.text_input("Enlace original", recipe.get("enlace", ""))
        photo = st.text_input("Enlace de foto", recipe.get("foto", ""))
        notes = st.text_area("Notas vuestras", recipe.get("notas", ""), height=100)
        done, fit = st.columns(2)
        with done:
            made = st.checkbox("Ya la hemos hecho", bool(recipe.get("hecha", False)))
        with fit:
            is_fit = st.checkbox("FIT", bool(recipe.get("fit", False)))
        saved = st.form_submit_button("Guardar receta", type="primary")
    if saved:
        if not name.strip():
            st.error("La receta necesita un nombre.")
            return
        updated = normalize({
            "id": recipe.get("id", str(uuid.uuid4())), "nombre": name.strip(),
            "categoria": category.strip(), "quien": author.strip(), "plataforma": platform.strip(),
            "fecha": source_date.strip(), "estado": status.strip(), "ingCompletos": ingredients,
            "ingPrincipales": main_ingredients, "enlace": source_url.strip(), "foto": photo.strip(),
            "notas": notes, "hecha": made, "fit": is_fit,
        })
        store.upsert(updated)
        st.success("Receta guardada.")
        st.rerun()


st.set_page_config(page_title="El recetario", page_icon="🍳", layout="wide")
require_password()
store, storage_name = get_store()

try:
    imported = seed(store)
except Exception as exc:
    st.error("No se pudo conectar a la base de datos. Confirma que ejecutaste schema.sql en Supabase y revisa los secretos.")
    st.exception(exc)
    st.stop()

st.title("🍳 El recetario")
st.caption(f"{storage_name}. Los cambios se guardan al pulsar «Guardar receta».")
if imported:
    st.success("Se han importado las recetas iniciales.")

with st.sidebar:
    st.header("Filtrar")
    query = st.text_input("Buscar", placeholder="Nombre o ingrediente")
    only_fit = st.checkbox("Solo FIT")
    only_done = st.checkbox("Solo hechas")
    st.divider()
    if st.button("Recargar datos"):
        st.rerun()

try:
    recipes = [normalize(recipe) for recipe in store.all()]
except Exception as exc:
    st.error("No se pudieron cargar las recetas.")
    st.exception(exc)
    st.stop()

categories = sorted({recipe["categoria"] for recipe in recipes if recipe["categoria"]})
category = st.selectbox("Categoría", ["Todas"] + categories)

def matches(recipe):
    text = " ".join(str(recipe.get(field, "")) for field in ("nombre", "ingredientes", "ingredientes_principales", "notas")).lower()
    return ((not query or query.lower() in text)
            and (category == "Todas" or recipe["categoria"] == category)
            and (not only_fit or recipe["fit"])
            and (not only_done or recipe["hecha"]))

visible = [recipe for recipe in recipes if matches(recipe)]
st.subheader(f"{len(visible)} de {len(recipes)} recetas")

with st.expander("＋ Añadir receta", expanded=False):
    recipe_form(store, {"id": str(uuid.uuid4()), "fecha": date.today().strftime("%-d/%-m/%y"), "plataforma": "Manual", "estado": "Añadida a mano"}, "new_recipe", True)

for recipe in visible:
    icon = "✅" if recipe["hecha"] else ("🥗" if recipe["fit"] else "🍽️")
    label = f"{icon} {recipe['nombre']}" + (f" · {recipe['categoria']}" if recipe["categoria"] else "")
    with st.expander(label):
        if recipe["foto"]:
            st.image(recipe["foto"], width=360)
        if recipe["notas_origen"]:
            st.caption(f"Nota original: {recipe['notas_origen']}")
        recipe_form(store, recipe, f"edit_{recipe['id']}")
        if st.button("Eliminar receta", key=f"delete_{recipe['id']}"):
            store.delete(recipe["id"])
            st.rerun()
