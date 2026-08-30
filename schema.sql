create table if not exists public.recipes (
  id text primary key,
  fecha text not null default '',
  quien text not null default '',
  plataforma text not null default '',
  nombre text not null,
  categoria text not null default '',
  ingredientes_principales text not null default '',
  ingredientes text not null default '',
  notas_origen text not null default '',
  enlace text not null default '',
  estado text not null default '',
  fit boolean not null default false,
  hecha boolean not null default false,
  foto text not null default '',
  notas text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- La app usa una clave de servidor y no necesita acceso directo desde el navegador.
-- Activar RLS evita que la clave anónima pueda leer estas recetas.
alter table public.recipes enable row level security;
