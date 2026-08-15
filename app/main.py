"""FastAPI application: customer chatbot, referral landing, admin dashboard."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from html import escape
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.admin import (
    SESSION_COOKIE, check_password, is_authenticated, issue_session,
    router as admin_router,
)
from .api.public import router as public_router
from .config import BASE_DIR, settings
from .db import init_db
from .services import groups, intents, pricing, referrals
from .utils import token

log = logging.getLogger("groupbuy")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

WEB_DIR = BASE_DIR / "web"
TEMPLATE_DIR = WEB_DIR / "templates"


def render(name: str, **context: Any) -> HTMLResponse:
    """Minimal templating: `{{ key }}` substitution, no engine dependency."""
    html = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    for key, value in context.items():
        html = html.replace(f"{{{{ {key} }}}}", "" if value is None else str(value))
    return HTMLResponse(html)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    pricing.seed_product_slabs()
    if settings.SEED_DEMO_DATA:
        from .seed import seed_demo

        seed_demo()

    task: asyncio.Task | None = None
    if settings.ENABLE_BACKGROUND_WORKER:
        from .worker import loop

        task = asyncio.create_task(loop(settings.PUBLIC_BASE_URL))
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="AI Group Buying Chatbot",
    description="Buy Together → Increase Quantity → Unlock Better Price",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(public_router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


# --------------------------------------------------------------------------- #
# customer screens
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return render("chat.html", REF="", GROUP="", INVITE_BANNER="")


@app.get("/join/{group_code}", response_class=HTMLResponse)
def join_landing(group_code: str, request: Request, ref: str = "") -> HTMLResponse:
    """Screen 3 — someone opened a shared link."""
    group = groups.get_by_code(group_code)
    banner = ""
    if ref:
        referrals.record_click(ref, request.query_params.get("s"))
    if group is not None:
        facts = pricing.price_facts(group)
        inviter = ""
        referral = referrals.get_by_code(ref) if ref else None
        if referral and referral.get("referrer_customer_id"):
            from .services import customers

            customer = customers.get(referral["referrer_customer_id"])
            name = (customer or {}).get("name") or ""
            inviter = name.split(" ")[0] if name else ""
        who = f"{inviter} has invited you" if inviter else "You've been invited"
        banner = (
            f'<div class="invite"><strong>{who}</strong> to join the '
            f'<em>{facts["group_label"]}</em> buying group.<br>'
            f'<span class="invite-qty">Currently {facts["group_quantity_text"]} pooled</span></div>'
        )
    return render("chat.html", REF=ref, GROUP=group_code if group else "", INVITE_BANNER=banner)


@app.get("/my/{status_token}", response_class=HTMLResponse)
def my_requests(status_token: str, request: Request) -> HTMLResponse:
    """Read-only status page for a returning buyer.

    There is no customer login in the MVP -- the unguessable token in the link
    is the credential, so the page is marked noindex and shows nothing without it.
    """
    from .services import customers

    customer = customers.by_status_token(status_token)
    if customer is None:
        return render(
            "notice.html",
            TITLE="Link not found",
            BODY="That link is no longer valid. Start a chat and we'll pull up your "
                 "requests from your mobile number.",
            ACTION='<a class="btn" href="/">Start a chat</a>',
        )

    records = intents.list_by_customer(customer["id"])
    name = (customer.get("name") or "").split(" ")[0]
    who = f"{name} · {customer['mobile']}" if name else str(customer.get("mobile") or "")

    if not records:
        body = '<p class="empty">You have no requests yet.</p>'
    else:
        body = "".join(
            _request_card(record, str(request.base_url).rstrip("/")) for record in records
        )
    return render("status.html", WHO=escape(who), REQUESTS=body)


def _request_card(record: dict[str, Any], base: str) -> str:
    """One requirement, with its group's live position. All figures come from
    the pricing engine."""
    from . import catalog
    from .services import customers

    category = catalog.get(record["category"])
    status = str(record.get("status") or "active")
    strength = intents.STRENGTH_LABELS.get(record["intent_strength"], record["intent_strength"])
    qty = float(record.get("quantity") or 0)
    qty_text = category.qty_label(qty) if category else f"{qty:g}"

    group = groups.get(record["group_id"]) if record.get("group_id") else None
    cells: list[str] = []
    footer = ""

    if group is not None:
        facts = pricing.price_facts(group, qty)
        cells.append(_cell("Buyers together need", facts["group_quantity_text"]))
        cells.append(_cell("Current group price", facts.get("current_price_text") or "—"))
        if facts.get("next_target_qty"):
            cells.append(_cell("Next target", facts["next_target_text"]))
            cells.append(_cell("Still needed", facts["gap_text"]))
        if facts.get("your_saving", 0) > 0:
            cells.append(
                _cell("Your saving so far", f"{facts['your_saving_text']} on {qty_text}", wide=True)
            )
        if status == "active":
            referral = referrals.ensure(record["customer_id"], group["id"])
            kit = referrals.share_kit(group, facts, referral["referral_code"], base)
            footer = (
                f'<div class="actions">'
                f'<a class="btn" href="{escape(kit["whatsapp_url"], quote=True)}" '
                f'target="_blank" rel="noopener">📲 Invite someone</a>'
                f'<a class="btn ghost" href="/r/{escape(record["id"])}/reschedule">📅 Change date</a>'
                f"</div>"
            )
        if not group["supplier_price_confirmed"]:
            footer += ('<p class="note">Indicative group price — confirmed once the supplier '
                       "quote is locked.</p>")
    else:
        cells.append(_cell("Status", "Waiting to be grouped", wide=True))

    when = record.get("desired_purchase_date") or "—"
    return (
        f'<div class="req">'
        f'<div class="top">'
        f'<div><h3>{escape(qty_text)} · {escape(record.get("product") or "")}</h3>'
        f'<p class="meta">{escape(record.get("city") or "")} · planned for {escape(str(when))} · '
        f'{escape(strength)} · {escape(record["id"])}</p></div>'
        f'<span class="pill {escape(status)}">{escape(status)}</span>'
        f"</div>"
        f'<div class="grid">{"".join(cells)}</div>'
        f"{footer}"
        f"</div>"
    )


def _cell(key: str, value: str, wide: bool = False) -> str:
    return (
        f'<div class="cell{" wide" if wide else ""}">'
        f'<div class="k">{escape(key)}</div><div class="v">{escape(str(value))}</div></div>'
    )


@app.get("/r/{intent_id}/{action}", response_class=HTMLResponse)
def reconfirm(intent_id: str, action: str, date: str = "") -> HTMLResponse:
    """One-tap links from the pre-expiry reminder (spec section 25)."""
    intent = intents.get_full(intent_id)
    if intent is None:
        return render("notice.html", TITLE="Link expired",
                      BODY="We couldn't find that requirement. Start a new chat to tell us what you need.",
                      ACTION='<a class="btn" href="/">Start a new chat</a>')

    if action == "yes":
        intents.reconfirm(intent_id, still_interested=True)
        return render("notice.html", TITLE="Thanks — you're still in 👍",
                      BODY="We've kept your requirement active and extended your window. "
                           "We'll message you when your group's price improves.",
                      ACTION='<a class="btn" href="/">Add another requirement</a>')
    if action == "no":
        intents.reconfirm(intent_id, still_interested=False)
        return render("notice.html", TITLE="Removed",
                      BODY="Your requirement has been cancelled and taken out of the group quantity. "
                           "Thanks for letting us know.",
                      ACTION='<a class="btn" href="/">Start again</a>')
    if action == "reschedule":
        if date:
            intents.reconfirm(intent_id, new_date=date, still_interested=True)
            return render("notice.html", TITLE="Date updated ✅",
                          BODY=f"We've moved your purchase date to {date} and kept you in the group.",
                          ACTION='<a class="btn" href="/">Back to chat</a>')
        return render("notice.html", TITLE="Change your purchase date",
                      BODY="Pick the date you now plan to buy on:",
                      ACTION=f'<form method="get"><input type="date" name="date" required>'
                             f'<button class="btn" type="submit">Save</button></form>')

    return RedirectResponse("/")


# --------------------------------------------------------------------------- #
# admin screens
# --------------------------------------------------------------------------- #
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/admin/login", status_code=303)
    return render("admin.html", VERSION=__version__)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(error: str = "") -> HTMLResponse:
    return render(
        "login.html",
        ERROR=f'<p class="err">{error}</p>' if error else "",
    )


@app.post("/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    if not check_password(username, password):
        return RedirectResponse("/admin/login?error=Incorrect+username+or+password", status_code=303)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(),
        max_age=settings.ADMIN_SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict[str, Any]:
    from . import nlu

    return {
        "status": "ok",
        "version": __version__,
        "nlu_engine": nlu.engine_name(),
        "groups": groups.stats(),
        "intents": intents.stats(),
    }


@app.get("/api/session/new")
def new_session() -> dict[str, str]:
    return {"session_id": f"S-{token(12)}"}


@app.exception_handler(KeyError)
def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(ValueError)
def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)
