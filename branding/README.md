# Branding

Traccar's own dashboard is used as-is. Nothing here modifies Traccar's source, so
upgrading stays a matter of changing a pinned tag.

The client's identity has **not** been invented. Placeholders only, until the real
company name and logo arrive.

## Placeholders

| Slot | Placeholder | Variable |
|---|---|---|
| Company name | `Company Name` | `COMPANY_NAME` |
| Dashboard title | `Fleet Control` | `DASHBOARD_TITLE` |
| Logo | `assets/logo-placeholder.svg` | `COMPANY_LOGO` |

## How overriding works

`branding/override/` is mounted at `/opt/traccar/web/override`, which Traccar
serves as static content and merges into the web app. Put overrides there and they
appear without forking anything.

Keep it to:

- a logo image
- a CSS file

## The rules

**Do not fork Traccar.** It is GPL-2.0. Hosting and running it is fine;
distributing a modified version obligates you to publish that source. Keeping
branding in `web/override` sidesteps that entirely and makes upgrades trivial.

**Keep this directory small and boring.** Every override is a thing that can
break on the next Traccar upgrade, and one forgotten CSS override can make the
dashboard unusable without any visible error.

**Keep real client assets out of Git.** `branding/assets/*` is gitignored apart
from the placeholder and `.gitkeep`, because a logo is often the client's
confidential brand material.

## Applying real branding later

1. Put the logo in `branding/assets/` (ignored by Git)
2. Put an override CSS file in `branding/override/`
3. Set `COMPANY_NAME` and `DASHBOARD_TITLE`
4. Redeploy

## Placeholder logo

`assets/logo-placeholder.svg` is a neutral map pin. Replace it when the real logo
exists.
