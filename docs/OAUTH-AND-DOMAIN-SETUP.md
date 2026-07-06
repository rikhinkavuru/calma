# OAuth providers + real-domain migration — setup guide

Two questions answered: (A) how to fill out each WorkOS "Your app's credentials" form, and (B) do it before or
after a real domain + everything a domain change touches.

## TL;DR — before or after the domain?

**The OAuth credentials are domain-independent.** Each provider redirects to WorkOS
(`https://auth.workos.com/sso/oauth/<provider>/<id>/callback`), NOT to Calma. So the Client ID / Secret you
paste into WorkOS never change when your domain changes. You can set them up now.

The ONLY domain-coupled part of provider setup is the **consent-screen branding URLs** (app homepage / privacy /
terms), which Google especially wants on a verified domain before it lets you publish to the public (vs. a
handful of "test users").

**Recommendation:** if you're not launching this week, stay on the WorkOS **demo credentials** (already working,
they just show "WorkOS" on the consent screen). When you buy the domain, do the OAuth apps + the domain
migration below in one pass — so you fill the consent-screen URLs once, with the final domain. Nothing is wasted
either way; only the consent URLs would need a later touch-up.

Apple is the hardest and needs a paid ($99/yr) Apple Developer account — consider Google + GitHub + Microsoft
first and add Apple later.

---

## A. Filling out each WorkOS provider

For every provider: in WorkOS, click **"Your app's credentials"** (not Demo), then paste the values below.
The **Redirect URI** shown in WorkOS is what you register inside the provider — copy it exactly.

### Google (redirect URI `…/sso/oauth/google/nodUA1…/callback`)
1. Google Cloud Console → create/select a project named **Calma**.
2. **APIs & Services → OAuth consent screen**: User type **External**. App name **Calma**, support email, upload
   the lotus logo. App homepage / privacy / terms URLs = your domain (or your Vercel URL for now). Add your
   domain under **Authorized domains** (this is for the branding links, not the redirect). Save. While unverified
   it runs in "Testing" mode — add yourself under **Test users**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**: type **Web application**, name
   "Calma Web". Under **Authorized redirect URIs**, paste the WorkOS Google redirect URI. Create.
4. Copy **Client ID** + **Client secret** → paste into WorkOS (Google Client ID / Secret).
5. Leave scopes as `userinfo.email` + `userinfo.profile` (already set). "Return Google OAuth tokens" unchecked
   unless you plan to call Google APIs. Save.

### Microsoft (redirect URI `…/sso/oauth/microsoft/Irl9…/callback`)
1. Azure Portal → **Microsoft Entra ID → App registrations → New registration**. Name **Calma**.
2. Supported account types: **Accounts in any org directory + personal Microsoft accounts**.
3. Redirect URI: platform **Web**, paste the WorkOS Microsoft redirect URI. Register.
4. Copy **Application (client) ID** → Microsoft Client ID.
5. **Certificates & secrets → New client secret** → copy the secret **Value** (not the ID) → Microsoft Client
   Secret. Paste both into WorkOS. Scopes `email` + `profile` are fine. Save.

### GitHub (redirect URI `…/sso/oauth/github/X44D…/callback`)
1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Application name **Calma**. Homepage URL = your domain (or Vercel URL). **Authorization callback URL** = paste
   the WorkOS GitHub redirect URI. Register.
3. Copy **Client ID**. Click **Generate a new client secret** → copy it.
4. Paste both into WorkOS. Scope `user:email` is already set. (Optional: upload a Calma logo.) Save.

### Apple (redirect URI `…/sso/oauth/apple/JySc…/callback`) — hardest, paid account
Needs an Apple Developer account. You provide 4 things: Team ID, Service ID, Key ID, Private Key.
1. **Team ID**: developer.apple.com → Membership → the 10-character Team ID.
2. **App ID**: Certificates, Identifiers & Profiles → Identifiers → **+** → **App IDs** → enable "Sign in with
   Apple". (This is the *primary* App ID the Service ID points to.)
3. **Service ID** (= Apple Service ID): Identifiers → **+** → **Services IDs**. Description **Calma**, identifier
   e.g. `com.calma.web`. Enable "Sign in with Apple" → **Configure**: primary App ID = the one above; Domains =
   `auth.workos.com`; Return URLs = paste the WorkOS Apple redirect URI.
4. **Key** (= Apple Key ID + Private Key): Keys → **+** → enable "Sign in with Apple" → configure with the App ID
   → Register → **download the `.p8`** (one-time). The **Key ID** is shown; the file contents are the **Private
   Key**.
5. Paste Team ID, Service ID, Key ID, and the `.p8` contents into WorkOS. Save.

After saving any provider, also set **WorkOS → Branding** (app name = Calma, logo) — that styles the AuthKit
hosted pages.

---

## B. What to change when you get a real domain

Good news: the app builds OAuth redirects from the live request host (`origin()` in
`web/app/dashboard/login-actions.ts`), so `/auth/callback` and the provider round-trips follow the new domain
automatically. The list below is the finite set that is hardcoded or env-pinned.

### 1. DNS + Vercel
- Buy the domain, add it to the Vercel **web** project (Settings → Domains), point DNS as Vercel instructs.
- (Optional) a subdomain like `api.<domain>` → the Fly engine, if you want to move off `calma-engine.fly.dev`.

### 2. WorkOS
- **Redirects**: add `https://<domain>/callback` **and** `https://<domain>/auth/callback` (keep the Vercel ones
  until you cut over). These are the app's own callbacks (distinct from the provider→WorkOS redirect URIs, which
  don't change).
- Update the AuthKit redirect env below to match.

### 3. Environment variables (Vercel web project)
- `NEXT_PUBLIC_WORKOS_REDIRECT_URI` / `WORKOS_REDIRECT_URI` → `https://<domain>/callback`
- `WORKOS_COOKIE_DOMAIN` → `.<domain>` (so the session cookie scopes to your domain)
- `CALMA_API_URL` → only if you move the engine to a custom domain

### 4. Hardcoded URLs in code (grep-confirmed)
- SEO / metadata `SITE_URL` (three files): `web/app/robots.ts`, `web/app/layout.tsx`, `web/app/sitemap.ts` —
  currently `https://calma1.vercel.app`.
- Dashboard/docs constants: `DASH` in `web/app/docs/content.ts`; `ENGINE` in `content.ts`,
  `web/app/dashboard/ApiKeysClient.tsx`, `IntegrationsClient.tsx` (engine URL — only if the engine domain moves).
- `trycalma.ai` references: legal contact emails in `web/app/terms/page.tsx` + `web/app/privacy/page.tsx`; badge
  URLs in `web/app/proof/page.tsx` + `web/app/badge/route.ts`.
- CLI/MCP docs + defaults: `cli/calma.py`, `cli/calma_mcp.py`, `cli/README.md`, `cli/pyproject.toml`
  (`calma1.vercel.app` dashboard links; `calma-engine.fly.dev` default API — the API default only if the engine
  moves).

### 5. Email (for the legal pages to be real)
- Set up `legal@<domain>` and `privacy@<domain>` mailboxes (currently the pages say `@trycalma.ai`). Point MX
  records; update the two legal pages if the address differs.

### 6. OAuth consent branding (once, after the domain)
- Update each provider's consent-screen homepage / privacy / terms URLs to the real domain, and (Google)
  complete domain verification to publish beyond test users. The client IDs/secrets do NOT change.

### 7. Nice-to-haves
- OpenGraph/Twitter image absolute URLs (in `layout.tsx` metadata) → real domain.
- Any marketing copy or footer links pointing at the Vercel URL.

**One clean way to do #4/#5:** introduce a single `NEXT_PUBLIC_SITE_URL` env var and replace the hardcoded
`SITE_URL` constants with it, so future domain changes are one env edit instead of a code change. (Say the word
and I'll refactor that.)
