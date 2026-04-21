-- 3DVisual Mesh Hub
-- Starter Supabase/Postgres schema for official releases + moderated plugin hub.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    username text unique,
    display_name text,
    avatar_url text,
    role text not null default 'user' check (role in ('owner', 'moderator', 'user')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.official_releases (
    id uuid primary key default gen_random_uuid(),
    version text not null unique,
    channel text not null default 'beta',
    title text not null,
    summary text not null default '',
    changelog text not null default '',
    installer_url text,
    portable_url text,
    cover_image_url text,
    is_published boolean not null default false,
    published_at timestamptz,
    created_by uuid references public.profiles(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.plugins (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.profiles(id) on delete cascade,
    slug text not null unique,
    name text not null,
    short_description text not null default '',
    long_description text not null default '',
    category text not null default 'workflow',
    status text not null default 'pending' check (status in ('draft', 'pending', 'approved', 'rejected', 'hidden')),
    cover_image_url text,
    repo_url text,
    homepage_url text,
    min_app_version text,
    featured boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.plugin_versions (
    id uuid primary key default gen_random_uuid(),
    plugin_id uuid not null references public.plugins(id) on delete cascade,
    version text not null,
    changelog text not null default '',
    package_url text not null,
    manifest_json jsonb not null default '{}'::jsonb,
    review_status text not null default 'pending' check (review_status in ('pending', 'approved', 'rejected')),
    reviewed_by uuid references public.profiles(id),
    reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    unique(plugin_id, version)
);

create table if not exists public.plugin_images (
    id uuid primary key default gen_random_uuid(),
    plugin_id uuid not null references public.plugins(id) on delete cascade,
    image_url text not null,
    sort_order integer not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists public.plugin_tags (
    plugin_id uuid not null references public.plugins(id) on delete cascade,
    tag text not null,
    created_at timestamptz not null default now(),
    primary key (plugin_id, tag)
);

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_official_releases_updated_at on public.official_releases;
create trigger set_official_releases_updated_at
before update on public.official_releases
for each row execute function public.set_updated_at();

drop trigger if exists set_plugins_updated_at on public.plugins;
create trigger set_plugins_updated_at
before update on public.plugins
for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.official_releases enable row level security;
alter table public.plugins enable row level security;
alter table public.plugin_versions enable row level security;
alter table public.plugin_images enable row level security;
alter table public.plugin_tags enable row level security;

-- Public read access for published official releases.
create policy "public can read published releases"
on public.official_releases
for select
using (is_published = true);

-- Only owner or moderators should manage official releases.
create policy "owner can manage official releases"
on public.official_releases
for all
using (
    exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role in ('owner', 'moderator')
    )
)
with check (
    exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role in ('owner', 'moderator')
    )
);

-- Public can read approved plugins only.
create policy "public can read approved plugins"
on public.plugins
for select
using (status = 'approved');

create policy "public can read approved plugin versions"
on public.plugin_versions
for select
using (
    review_status = 'approved'
    and exists (
        select 1
        from public.plugins
        where plugins.id = plugin_versions.plugin_id
          and plugins.status = 'approved'
    )
);

create policy "public can read images for approved plugins"
on public.plugin_images
for select
using (
    exists (
        select 1
        from public.plugins
        where plugins.id = plugin_images.plugin_id
          and plugins.status = 'approved'
    )
);

create policy "public can read tags for approved plugins"
on public.plugin_tags
for select
using (
    exists (
        select 1
        from public.plugins
        where plugins.id = plugin_tags.plugin_id
          and plugins.status = 'approved'
    )
);

-- Logged in users can create their own plugin entries.
create policy "users can insert own plugins"
on public.plugins
for insert
with check (owner_id = auth.uid());

create policy "owners can update own plugins"
on public.plugins
for update
using (
    owner_id = auth.uid()
    or exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role in ('owner', 'moderator')
    )
)
with check (
    owner_id = auth.uid()
    or exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role in ('owner', 'moderator')
    )
);

create policy "owners can read own plugins"
on public.plugins
for select
using (
    owner_id = auth.uid()
    or status = 'approved'
    or exists (
        select 1
        from public.profiles
        where profiles.id = auth.uid()
          and profiles.role in ('owner', 'moderator')
    )
);

create policy "users can insert versions for own plugins"
on public.plugin_versions
for insert
with check (
    exists (
        select 1
        from public.plugins
        where plugins.id = plugin_versions.plugin_id
          and plugins.owner_id = auth.uid()
    )
);

create policy "users can read own plugin versions"
on public.plugin_versions
for select
using (
    review_status = 'approved'
    or exists (
        select 1
        from public.plugins
        where plugins.id = plugin_versions.plugin_id
          and (
            plugins.owner_id = auth.uid()
            or exists (
                select 1
                from public.profiles
                where profiles.id = auth.uid()
                  and profiles.role in ('owner', 'moderator')
            )
          )
    )
);

create policy "users can add images to own plugins"
on public.plugin_images
for insert
with check (
    exists (
        select 1
        from public.plugins
        where plugins.id = plugin_images.plugin_id
          and plugins.owner_id = auth.uid()
    )
);

create policy "users can add tags to own plugins"
on public.plugin_tags
for insert
with check (
    exists (
        select 1
        from public.plugins
        where plugins.id = plugin_tags.plugin_id
          and plugins.owner_id = auth.uid()
    )
);

-- Profiles are readable to signed-in users.
create policy "signed in users can read profiles"
on public.profiles
for select
using (auth.role() = 'authenticated');

create policy "users can manage own profile"
on public.profiles
for all
using (id = auth.uid())
with check (id = auth.uid());

-- Suggested storage buckets:
-- official-builds
-- plugin-packages
-- plugin-media
