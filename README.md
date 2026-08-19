# AI Group Buying Chatbot — MVP

**Buy Together → Increase Quantity → Unlock Better Price.**

A mobile-first web chatbot that captures purchase intents in conversation, pools
compatible buyers into buying groups, prices those groups off quantity slabs, and
messages everyone whenever the group's position improves — which gives them a
reason to invite more buyers, which improves the position again.

The customer has no dashboard, no login and no account. They talk to the bot once;
after that the system works in the background and contacts them.

```
Chat → intent → matched into a group → quantity ↑ → price ↓ → notify → share → repeat
```

---

## Run it

```bash
pip install -r requirements.txt
python run.py
```

| URL | What it is |
| --- | --- |
| `http://127.0.0.1:8000/` | Customer chatbot (the main customer screen) |
| `http://127.0.0.1:8000/join/{code}?ref={ref}` | Referral landing → same chatbot, pre-attributed |
| `http://127.0.0.1:8000/my/{token}` | A buyer's own requests + live group status (link is the credential) |
| `http://127.0.0.1:8000/admin` | Admin back office (`admin` / `admin`) |
| `http://127.0.0.1:8000/docs` | Interactive OpenAPI reference |
| `http://127.0.0.1:8000/health` | Liveness + which NLU engine is active |

The database starts **empty** — the back office only ever shows real customer
demand. Set `SEED_DEMO_DATA=1` on a throwaway database if you want sample rows to
look at. No database server, no build step, no API key required.

```bash
python -m pytest        # 236 tests
RELOAD=1 python run.py  # auto-reload during development
```

---

## Deploy

The app is a single Python process plus a SQLite file, so any container host works.

```bash
docker build -t groupbuy . && docker run -p 8000:8000 -v groupbuy-data:/data groupbuy
```

- **Render** — `render.yaml` is a ready blueprint (New → Blueprint → pick the repo).
- **Railway / Fly.io / Cloud Run** — point them at the `Dockerfile`; they set `$PORT`.
- **Anything Heroku-style** — the `Procfile` is there.

Set these before going live:

| Variable | Why |
| --- | --- |
| `PUBLIC_BASE_URL` | share and status links are absolute — they must point at the real host |
| `ADMIN_PASSWORD`, `ADMIN_SECRET` | the defaults are `admin` / derived; change both |
| `DB_PATH` | put it on a **persistent disk**, or every deploy wipes live buying groups |
| `ANTHROPIC_API_KEY` | optional — switches the NLU from rules to Claude |

GitHub hosts the code; it does not run it. Pushing the repo does not by itself
produce a live URL — one of the hosts above does.

---

## How the pieces fit

```
                    ┌──────────────┐
   customer ───────▶│ conversation │  asks only for what's missing
                    └──────┬───────┘
                           │ slot bag
                    ┌──────▼───────┐
                    │     NLU      │  Claude (if keyed) + rules fallback
                    └──────┬───────┘
                           │ structured intent
                    ┌──────▼───────┐      ┌──────────┐
                    │   intents    │─────▶│ matching │  exact vs flexible
                    └──────┬───────┘      └────┬─────┘
                           │                   │
                    ┌──────▼───────────────────▼─────┐
                    │            groups              │  aggregate → recalculate
                    └──────┬───────────────────┬─────┘
                           │                   │
                    ┌──────▼──────┐     ┌──────▼────────┐
                    │   pricing   │     │ notifications │  WhatsApp / SMS / email
                    └─────────────┘     └───────────────┘
                     every number         every message
```

### The rule that shapes the architecture

**The AI never produces a number.** Prices, quantities, targets, gaps and savings
come from `services/pricing.py` and are handed to the language layer as
pre-rendered facts that it may only echo. `test_pricing.py` pins the arithmetic;
`price_facts()` simply omits price keys when a group has no slabs, so there is
nothing for a model to hallucinate from.

---

## Conversation engine

The bot holds a slot bag and asks for the single highest-priority missing value.
Anything the customer already said is never asked again:

> "I need two Daikin 1.5 ton ACs in Ahmedabad next week."

extracts product, quantity, brand, capacity, city and purchase date in one turn,
then continues from split/window onward.

- **Priority order**: product → **mobile** → quantity → specification → location →
  purchase date → wait flexibility → brand flexibility → name.
- **Mobile second.** The number is the identity, so it is asked immediately after
  the product — that is what makes returning buyers recognisable before they are
  put through the whole flow again. The intent is never created without it.
- **Optional questions are capped** at two, and dropped after two unhelpful
  answers. Essential ones (quantity, city, name, mobile) get rephrased instead of
  repeated.
- **Every visit is a fresh chat.** Opening the site never replays an old
  conversation; continuity comes from the mobile number, not from browser state.

### Commands work at any point

Steering instructions are matched **before** slot extraction, so they can never
be mistaken for an answer to the question on screen. Asking to cancel while the
bot is asking "Split or Window?" cancels — it does not get read as a spec.

| Say | What happens |
| --- | --- |
| "cancel my request", "no longer required" | cancels the saved request and drops its quantity from the group; asks which one when there are several. Nothing saved yet → says so and offers a fresh start |
| "show me my old request", "order status" | lists their requests and hands over the `/my/{token}` link, texting it too. Asks for the number first if we don't know them yet |
| "change product", "something else" | keeps name and mobile, drops the product, starts again |
| "exit", "bye", "that's all" | closes warmly; reassures them their group keeps working if a request is live |
| "how does this work?", "share", "I'm ready to buy" | answered without losing the thread |

Any missed answer also surfaces **Change product / My requests / Cancel** chips,
so the customer always has a way out instead of a repeated question.

### Returning buyers

A number we already know short-circuits the flow:

```
"I need AC" → "What's your mobile number?" → 9876543210
        ↓
"Welcome back, Rahul 👋  You already have 1 active request:
 • 2 ACs · 1.5 Ton Split Inverter AC · Ahmedabad"
        ↓
[➕ Add a new request]          [📋 Show my past requests]
        ↓                                ↓
 full flow, but the name          a /my/{token} link, in chat and
 is never asked again             texted to their mobile
```

`/my/{token}` lists every request with its live group position — quantity
pooled, current price, next target, gap, saving so far — and lets them invite
someone or change their purchase date. There is still no login: the unguessable
token in the link is the credential, and the page is `noindex`.

### Live merges

While a chat is open the page polls `GET /api/chat/{session}/live` every 15s. If
another buyer's compatible requirement merges into the same group meanwhile, it
lands in that conversation immediately:

> 👥 A matching requirement just merged into your group — **2 ACs** added.
> Your group is now at **27 ACs**.

followed by refreshed group, next-target and share cards. The endpoint diffs the
group against the snapshot the customer last saw, so an update is delivered once
and the wording is chosen — but never the numbers — by the message layer.

### Two NLU engines

| | Rules (default) | Claude |
| --- | --- | --- |
| Requires | nothing | `ANTHROPIC_API_KEY` |
| Handles | quantities & units, capacities, brands, cities, dates, wait phrases, typos | messy free text, unusual phrasings, off-script questions |
| Role | always runs; wins on exact fields (mobile, unit conversion, canonical city) | runs first when keyed, fills everything else |

With a key set the engines merge — deterministic values take precedence, and any
LLM failure (network, rate limit, refusal, bad JSON) silently falls back to rules.
Extraction uses structured outputs against a JSON schema generated from the
category's own slot definitions, so the model cannot invent slot names.

---

## Matching engine

Hard filters first — same category, same city, compatible specification,
overlapping purchase windows, compatible brand policy. Survivors are scored:

### Purchase windows are deadlines, not appointments

**"Within 15 days" means any time between now and then.** An intent's window
therefore runs from `earliest_purchase_date` (today, for anyone who answered
with a deadline) to `maximum_purchase_date` — not from the desired date.

Treating the desired date as the window *start* is subtly catastrophic: a buyer
saying "within 7 days" got 24–31 Aug and one saying "within 15 days" got 1–8
Sep. Adjacent, non-overlapping, so two buyers who wanted the same rice in the
same city were split into separate groups, their quantities never combined, the
price never dropped, and nobody was notified. `test_window_matching.py` pins it.

Only an explicitly chosen calendar date is treated as "not before then", so a
buyer purchasing in four months still won't be pooled with a group closing this
week.

```
40  base
20  product-spec exactness
20  brand fit
10  group momentum  (how close the group already is to its next slab)
 5  same area
 5  window overlap quality
```

Score ≥ 60 joins the best group; otherwise the intent starts a new one.

- **Exact groups** are brand-locked. A buyer who insists on Daikin only ever
  lands in a Daikin-locked group — a flexible group could be negotiated as any
  brand, so it cannot honour that requirement.
- **Flexible groups** accept buyers with no preference or a stated preference
  plus willingness to switch.
- **Momentum** makes a flexible buyer join the larger pool when two groups fit,
  so demand consolidates toward the next price break instead of fragmenting.

`GET /api/admin/intents/{id}` returns the full scoring breakdown — every reason
and every blocker — so an operator can see exactly why an intent landed where it did.

---

## Pricing and quantity

Each group owns a private copy of its slab table (editable per group without
touching the product-wide template).

| Quantity | Price |
| --- | ---: |
| 1–5 | ₹40,000 |
| 6–10 | ₹38,500 |
| 11–20 | ₹37,000 |
| 21–30 | ₹35,500 |
| 31–50 | ₹34,000 |
| 51+ | ₹32,500 |

Three quantities are tracked separately:

- **total intent qty** — every active intent
- **strong intent qty** — mobile + date captured; **this drives the price** and is
  the number used for supplier negotiation
- **confirmed qty** — accepted the final offer

Expired and cancelled intents leave the totals automatically, so the quantity a
supplier is quoted against stays honest.

---

## Notifications

Composed from backend facts, deduped, rate-limited, and written to an outbox
table before dispatch. The default sender logs to the console, so the entire loop
is observable without third-party credentials.

| Trigger | Sent when |
| --- | --- |
| `price_drop` | the group crosses into a cheaper slab |
| `near_target` | the gap to the next slab is ≤ 3 units |
| `progress` | the group passes 50% / 80% / 90% toward the next slab |
| `expiry_reminder` | 3 days before the purchase window closes |
| `referral_joined` | someone's invite produced an intent |
| `admin_broadcast` | an operator messages a group |

Guards: one message per customer per milestone (`dedupe_key`), at most two per
customer per group per day, and the buyer who just triggered a change is excluded
— they already saw it in chat.

Swap in a real provider without touching the rules:

```python
from app.services import notifications

def send_whatsapp(n):        # n has to, message, channel, payload…
    return meta_cloud_api.send(n["to"], n["message"])

notifications.register_sender("whatsapp", send_whatsapp)
```

Reminder links are one-tap: `/r/{intent_id}/yes`, `/reschedule`, `/no`.

---

## Referrals

Every customer gets a stable code per group. `/join/{groupCode}?ref={code}`
records the click, shows who invited them and what the group currently stands at,
then starts the chatbot. Clicks, chats started, intents submitted and quantity
generated are all tracked, and the referrer is notified when their invite lands.

---

## Any product

AC and rice have negotiated slab tables. Everything else goes through the
**open-ended** category: the customer names the product in their own words and
buyers wanting the same thing in the same city pool together.

```
"I need 50 office chairs"              ┐
"looking for good quality Office Chair" ┘ → one group, 80 units
```

Grouping is by a normalised key, so phrasing does not fragment demand:
quantities, units, punctuation and filler adjectives are stripped and each word
singularised — `2 Office Chairs!`, `office chair` and `good quality OFFICE
CHAIRS` all become `office chair`. The group is labelled from that canonical
form, not from whoever created it. Quantity is counted in the customer's own
unit (`100 kg cement`, `50 boxes`, `20 litres`).

### An open group starts with no price, and says so

Nobody has quoted for a product we have never bought. Rather than invent a
number, the group collects quantity and the chat is explicit:

> **Price: being negotiated**
> We're pooling demand for this product now. As soon as we have enough quantity
> we'll get a supplier quote and message you the price.

No price, no next target, no savings — `price_facts()` omits those keys entirely
when a group has no slabs, so there is nothing for a language model to echo.

The back office flags these groups as **needs quote**. When an operator loads
the supplier's slabs (`PUT /api/admin/groups/{id}/slabs`), `recalculate()`
reports `price_appeared` and every pooled member is messaged — bypassing the
daily notification cap, because it is the payoff for joining on trust.

A product that outgrows this — enough volume to be worth a dedicated flow with
its own questions and standing slab table — graduates to its own module.

---

## Adding a product category

Create one module in `app/catalog/` exposing a `CATEGORY`, and add its name to
`_MODULES` in `app/catalog/__init__.py`. Nothing else changes — the conversation
engine, matching, pricing, notifications and admin dashboard are all driven from
the declaration:

```python
CATEGORY = Category(
    key="LAPTOP", label="Laptop", emoji="💻",
    unit="unit", unit_plural="units", product_noun="Laptop",
    quantity_question="How many laptops do you need?",
    quantity_chips=("1", "2", "5", "10+"),
    slots=(Slot(name="screen_size", question="What screen size?", priority=20,
                chips=("13\"", "14\"", "15.6\""), grouping=True), ...),
    grouping_fields=("screen_size", "ram"),
    slabs={"LAPTOP|15.6\"|16gb": (Slab(1, 5, 62000), Slab(6, 20, 58000), ...)},
    default_slab_key="LAPTOP|15.6\"|16gb",
    triggers=(r"\blaptop\b", r"\bnotebook\b"),
)
```

---

## API

Customer-facing (no auth):

```
POST /api/chat/message              GET  /api/chat/{session_id}
GET  /api/chat/{session_id}/live    GET  /my/{status_token}
POST /api/intents                   GET  /api/intents/{id}
PUT  /api/intents/{id}              POST /api/intents/{id}/match
POST /api/intents/{id}/reconfirm
GET  /api/groups/{id}               GET  /api/groups/{id}/pricing
POST /api/groups/{id}/join          POST /api/groups/{id}/recalculate
POST /api/referrals                 GET  /api/referrals/{code}
POST /api/notifications/process     GET  /api/catalog
GET  /join/{groupCode}?ref={code}
```

Admin (session cookie or HTTP Basic):

```
GET  /api/admin/overview            GET  /api/admin/demand-by-product
GET  /api/admin/expiring
GET  /api/admin/groups              GET  /api/admin/groups/{id}
PUT  /api/admin/groups/{id}/slabs   POST /api/admin/groups/{id}/supplier-price
POST /api/admin/groups/{id}/status  POST /api/admin/groups/{id}/notify
POST /api/admin/groups/merge        POST /api/admin/groups/{id}/split
POST /api/admin/groups/consolidate
GET  /api/admin/intents             GET  /api/admin/intents/{id}
PUT  /api/admin/intents/{id}        POST /api/admin/intents/move
POST /api/admin/intents/{id}/status POST /api/admin/intents/{id}/strength
GET  /api/admin/customers           GET  /api/admin/referrals
GET  /api/admin/conversations       GET  /api/admin/conversations/{session}
GET  /api/admin/slab-templates      GET  /api/admin/audit
POST /api/admin/maintenance/run-jobs
POST /api/admin/maintenance/recalculate-all
```

```bash
curl -u admin:admin http://127.0.0.1:8000/api/admin/overview
```

---

## Admin dashboard

Eight views: overview (demand by product / city / area / purchase date / intent
strength, plus expiring intents), groups, intents, customers, referrals,
notification outbox, conversations and pricing templates.

**Groups are presented per product** — one panel per category, each headed with
that product's totals: groups, customers, total demand, strong demand, confirmed,
and **quantity pending to close the next price level**. Two different products
are never comparable side by side, so they never share a table.

"Pending" is the operator's headline number: how much more quantity would unlock
a cheaper slab. It appears per group (sorted closest-to-closing first) and summed
per product, with groups already on their cheapest slab marked *best price* and
excluded from the total. `GET /api/admin/demand-by-product` returns the same
figures for reporting.

Operators can view any chat transcript beside the AI's extracted fields, correct
an extraction and re-run matching, move an intent between groups, merge or split
groups, edit a group's slabs, mark a supplier price confirmed, message a group,
change intent status or strength, and run the background jobs on demand. Every
mutation is written to an audit log.

---

## Background worker

Runs in-process every 60s (`ENABLE_BACKGROUND_WORKER=0` to disable and drive it
externally instead):

1. **consolidate** — pool any two open groups buying the same thing
2. expire intents past their window and re-aggregate affected groups
3. queue reconfirmation reminders for intents nearing expiry
4. dispatch the outbox
5. every tenth tick, sweep all groups for milestone notifications

### Consolidation

Matching decides where a *new* intent goes. Consolidation is the safety net for
groups that are already apart: every pass, any two open groups with the same
category, specification, city, brand policy and overlapping windows are pooled,
larger absorbing smaller so codes already shared with customers keep working.

It exists because a split is invisible to the customer and expensive to the
business — two half-groups both pay the higher price. Whatever the cause (a
matching-rule change, an admin edit, two simultaneous first buyers racing),
the next pass heals it.

Buyers pulled into the bigger pool are told when their price improves. Their old
group's price is compared against the new one — the *target* group's price often
does not change at all, so the ordinary recalculation can never discover this.

```bash
curl -u admin:admin -X POST '.../api/admin/groups/consolidate?dry_run=true'
```

`dry_run` previews the merges with reasons and changes nothing. Merged groups
keep their row so old links resolve, but drop out of the back office and out of
demand totals.

Same work over HTTP: `POST /api/notifications/process`.

---

## Database

SQLite, plain SQL, no ORM — portable to Postgres with minimal edits.

`customers` · `purchase_intents` · `buying_groups` · `pricing_slabs` ·
`referrals` · `referral_events` · `conversations` · `notifications` ·
`admin_audit` · `sequences`

Schema in [`app/schema.sql`](app/schema.sql).

---

## Tests

```
tests/test_pricing.py        slab boundaries, savings, missing-price safety
tests/test_nlu.py            extraction, units, dates, typos, no re-asking
tests/test_matching.py       exact vs flexible, momentum, windows, expiry
tests/test_conversation.py   question order, mobile-first, loop guards, resume
tests/test_returning_customer.py  recognition, status page, live merge updates
tests/test_commands.py       cancel / show-past / change-product / exit, mid-flow
tests/test_window_matching.py  deadline semantics, pooling, no dead-end loops
tests/test_consolidation.py  auto-merge sweep, what must never be pooled
tests/test_open_products.py  any-product pooling, unpriced-group honesty
tests/test_notifications.py  triggers, dedupe, rate limits, expiry, referrals
tests/test_api.py            every endpoint including admin operations
tests/test_end_to_end.py     the full loop, asserted against the spec's numbers
```

`test_end_to_end.py` reproduces the worked example: an 18-unit group, a buyer
adding 2 sees **20 ACs at ₹37,000** (saving ₹3,000/unit, ₹6,000 total), is told
the next level is **21 units at ₹35,500**, shares a link, and when the friend's
3 units land the price drops and every existing member is notified — except the
friend, who just saw it in chat.

---

## Production notes

Not in the MVP, deliberately: real WhatsApp/SMS providers (adapters are
registerable), OTP verification (schema and flow allow for it —
`customers.mobile_verified`, `customers.mark_verified()`), staff accounts and
roles, and Postgres. Set `ADMIN_PASSWORD`, `ADMIN_SECRET` and `PUBLIC_BASE_URL`
before deploying, and put the app behind TLS.
