# El recetario compartido

Aplicación Streamlit creada a partir de `recetario_1.html`. Incluye las 157 recetas detectadas, búsquedas, filtros, recetas manuales y edición de ingredientes, notas, estado, enlaces y marcas FIT/hecha.

## Probarla en este ordenador

Requiere Python 3.10 o superior.

```bash
cd recetario_compartido
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

En esta modalidad usa `recetario.db`, una base local. Sirve para probar la aplicación, pero **no** comparte los cambios entre dispositivos.

## Usarla los dos con los mismos datos

La opción prevista es desplegar la app y usar una base de datos Supabase (sus planes gratuitos son suficientes para un recetario familiar):

1. Cread un proyecto en [Supabase](https://supabase.com/dashboard), abrid el editor SQL y ejecutad el contenido de `schema.sql`.
2. En *Project settings → API*, copiad el **Project URL** y la clave **service_role**. Esta segunda clave solo debe estar en los secretos del servidor, nunca en una web estática ni en un repositorio público.
3. Subid esta carpeta a un repositorio privado de GitHub y desplegadla en [Streamlit Community Cloud](https://share.streamlit.io/), o ejecutadla en un servidor que dejéis encendido.
4. En los secretos del despliegue, añadid el contenido de `.streamlit/secrets.toml.example`, con vuestros valores. Elegid una contraseña para compartirla entre los dos.
5. Abrís el mismo enlace desde los dos dispositivos. Cada guardado se escribe en Supabase; pulsad **Recargar datos** para ver inmediatamente una edición hecha desde otro dispositivo.

La importación inicial se hace una sola vez: al arrancar con una base vacía se cargan automáticamente las recetas de `data/recipes.json`. No pulséis ni ejecutéis la importación de nuevo sobre una base ya usada.

## Seguridad y copias

El enlace de la app queda protegido por la contraseña definida en `access_password`. No añadáis `.streamlit/secrets.toml` al repositorio: ya está incluido en `.gitignore`. Para una copia de seguridad, exportad la tabla `recipes` desde Supabase de vez en cuando.
