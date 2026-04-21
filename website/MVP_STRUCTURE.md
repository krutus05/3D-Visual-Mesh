# 3DVisual Mesh Hub MVP Structure

## Best choice

Build the hub in two layers:

1. `Official Releases`
   only the owner uploads installers, zips, patch notes, screenshots
2. `Plugin Hub`
   users create accounts, upload plugin packages, and wait for approval

## Why

- official app downloads need higher trust
- community uploads need moderation
- this keeps the site useful without becoming a mess too early

## Core pages

### Public pages

- Home
- Official Downloads
- Plugin Browser
- Single Plugin Page
- Changelog / Release Notes

### Account pages

- Sign Up
- Log In
- My Profile
- My Plugins
- Submit Plugin
- Edit Plugin

### Admin pages

- Admin Review Queue
- Official Release Upload
- Plugin Moderation Panel
- Featured Plugins Editor

## Upload rules

### Official releases

Only owner role can upload:

- installer `.exe`
- portable `.zip`
- screenshots
- release notes
- version metadata

### Community plugins

Users can upload:

- plugin zip
- cover image
- screenshots
- title
- short description
- long description
- tags
- version number
- compatibility notes

Community uploads should start as:

- `pending`

They only become public after owner approval.

## Recommended plugin package format

For version 1, accept only a zip package with a simple manifest:

```json
{
  "name": "Blender Cleanup Tools",
  "slug": "blender-cleanup-tools",
  "version": "0.1.0",
  "author": "Creator Name",
  "entry": "plugin.py",
  "description": "Short summary",
  "tags": ["blender", "cleanup", "retopo"],
  "min_app_version": "0.1.0"
}
```

## Real downside

Do not allow random executables in user plugin uploads for v1.

If you allow raw `.exe` tools too early, moderation and safety get much harder.

## Suggested build order

1. Static site prototype
2. Real Next.js app shell
3. Supabase auth
4. Official releases table + upload screen
5. Plugin upload flow
6. Admin approval flow
7. Search, tags, featured plugins
8. Ratings and comments later

## MVP success target

The first real live version should let people do four things well:

- download the official app safely
- browse approved plugins
- create an account
- submit a plugin for review
