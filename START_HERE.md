# HappyHelper — Start Here for AI Agents

> Last updated: 2026-10-10

## What is this?

HappyHelper (formerly ParakeetAI) is a Django web app + Chrome extension that provides real-time AI coaching during interviews and meetings. It transcribes speech live via Groq Whisper, sends context to an LLM (Groq/OpenRouter), and surfaces suggested answers in a browser overlay.

## Repo layout

```
local_parakeet/                 ← git root
  local_parakeet/               ← Django project settings
    settings.py                 ← loads .env (try/except for git-crypt on Render)
    urls.py                     ← root URL conf
  interview/                    ← main Django app
    models.py                   ← InterviewSession, TranscriptEntry, Participant
    views.py                    ← all views + REST API endpoints
    urls.py                     ← app URL routing
    templates/interview/
      landing.html              ← SaaS marketing landing page (unauthenticated /)
      login.html                ← sign-in page
      home.html                 ← authenticated dashboard
      pricing.html              ← full pricing/billing page
      live_session.html         ← real-time session UI
      session_detail.html       ← post-session review
      settings.html             ← user settings (API keys, model choice)
      profile.html              ← user profile
```

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django 4.x, Python 3.11 |
| DB | Postgres (Render managed) |
| Auth | Django's built-in auth |
| AI | Groq Whisper (transcription), Groq/OpenRouter (chat) |
| Deploy | Render (auto-deploy on push to `main`) |
| Extension | Chrome extension (content_script.js → calls Render URL) |

## Environment variables (set in Render dashboard)

```
DATABASE_URL
SECRET_KEY
GROQ_API_KEY
OPENROUTER_API_KEY
DJANGO_SUPERUSER_USERNAME
DJANGO_SUPERUSER_EMAIL
DJANGO_SUPERUSER_PASSWORD
```

The `.env` file in the repo is git-crypt encrypted — `settings.py` wraps `load_dotenv()` in try/except so it silently skips the binary on Render.

## Key URLs

| URL | View | Notes |
|---|---|---|
| `/` | `home` | Landing page (unauth) or dashboard (auth) |
| `/pricing/` | `pricing_view` | Dedicated pricing/billing page |
| `/login/` | `login_view` | Sign-in |
| `/signup/` | `signup_view` | Registration |
| `/session/new/` | `new_session` | Create session |
| `/session/<uuid>/` | `live_session` | Real-time session |
| `/settings/` | `settings_page` | API key, model config |
| `/api/session/<uuid>/transcribe/` | `api_transcribe` | POST audio → transcript |
| `/api/session/<uuid>/chat/` | `api_chat` | POST transcript → AI answer |

## Current state (as of 2026-10-04)

### Done ✅
- SaaS landing page (`landing.html`) with hero, how-it-works, features, testimonials, pricing teaser, CTA, footer
- Dedicated pricing page (`pricing.html`) with 3 tiers (Free/$0, Pro/$19, Team/$49), feature comparison table, FAQ, annual/monthly toggle
- `home` view updated: unauthenticated → `landing.html`, authenticated → `home.html`
- `/pricing/` route added
- Design system in `interview/templates/interview/_styles.html`: one set of tokens for dark and light, shared by every page. Logo in `_logo.html`, files in `docs/brand/`. See the Design system section of `README.md` before adding colours or fonts.

### Pending / Next tasks 🔲

#### Priority 1 — Auth & signup
- [ ] Create `signup_view` in `views.py` + `signup.html` template (the landing page CTAs link to `/signup/`)
- [ ] Add `path("signup/", views.signup_view, name="signup")` in `urls.py`
- [ ] Minimal form: username, email, password — use Django's `UserCreationForm`

#### Priority 2 — Deploy & env setup
- [ ] Set all 7 env vars in Render dashboard (see list above)
- [ ] Trigger deploy (or push to `main` — Render auto-deploys)
- [ ] Update Chrome extension `content_script.js`: change `baseUrl` from `https://parakeetai.loca.lt` to `https://parakeetai.onrender.com`

#### Priority 3 — Payment integration (Stripe)
- [ ] Add `stripe` to `requirements.txt`
- [ ] Create `billing/` app or add billing views to `interview/`
- [ ] Stripe Checkout session for Pro ($19/mo) and Team ($49/mo)
- [ ] Webhook handler for `checkout.session.completed` and `customer.subscription.deleted`
- [ ] Add `UserProfile` model with `plan` field (free/pro/team) and `stripe_customer_id`
- [ ] Gate features: session count limit (Free=5), model quality, meeting mode

#### Priority 4 — Dashboard enhancements
- [ ] Add session count/limit display to `home.html` for Free plan users
- [ ] "Upgrade" banner when approaching limit
- [ ] Export session as PDF

#### Priority 5 — Polish
- [ ] `404.html` and `500.html` error pages
- [ ] Email verification on signup (optional, Django's `send_mail`)
- [x] Responsive nav (links fold into the account menu on phones)
- [ ] Meta tags / OG tags for landing page SEO

## How to run locally

```bash
cd local_parakeet
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://localhost:8000` — you'll see the landing page unauthenticated.

## Git workflow

```bash
git add <files>
git commit -m "your message

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push origin main   # Render auto-deploys
```

**Never include actual token values in push commands. Always use `$GITHUB_TOKEN`.**

## Render deployment

- Service ID: `srv-db0svfmgekts73b5kfcg`
- Workspace: `tea-db0steegekts73b5bm50`
- Live URL: `https://parakeetai.onrender.com`
- Auto-deploy: ON (pushes to `main` trigger deploy)
