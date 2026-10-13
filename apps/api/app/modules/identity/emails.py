"""Account emails in English and Telugu (chosen by the user's lesson language)."""

from html import escape

from app.core.mail import Message

BRAND = "EduVerse AI"

TEXT = {
    "en": {
        "greeting": "Hello {name},",
        "reset_subject": "Reset your EduVerse AI password",
        "reset_body": "We received a request to reset your password. Open this link within {minutes} minutes to choose a new one:",
        "reset_button": "Choose a new password",
        "reset_ignore": "If you did not ask for this, ignore this email; your password stays the same.",
        "verify_subject": "Confirm your email for EduVerse AI",
        "verify_body": "Please confirm that this is your email address. The link works for {hours} hours:",
        "verify_button": "Confirm my email",
        "verify_ignore": "If you did not create an EduVerse AI account, you can ignore this email.",
        "changed_subject": "Your EduVerse AI password was changed",
        "changed_body": "Your password was just changed, and you were signed out on every device.",
        "changed_warn": "If this was not you, reset your password now at {link} and tell us by replying to this email.",
        "signoff": "The EduVerse AI team",
    },
    "te": {
        "greeting": "నమస్కారం {name},",
        "reset_subject": "మీ EduVerse AI పాస్‌వర్డ్‌ను రీసెట్ చేయండి",
        "reset_body": "మీ పాస్‌వర్డ్ రీసెట్ కోసం అభ్యర్థన వచ్చింది. కొత్త పాస్‌వర్డ్ ఎంచుకోవడానికి {minutes} నిమిషాల్లోగా ఈ లింక్ తెరవండి:",
        "reset_button": "కొత్త పాస్‌వర్డ్ ఎంచుకోండి",
        "reset_ignore": "ఈ అభ్యర్థన మీరు చేయకపోతే, ఈ ఇమెయిల్‌ను పట్టించుకోకండి; మీ పాస్‌వర్డ్ మారదు.",
        "verify_subject": "EduVerse AI కోసం మీ ఇమెయిల్‌ను నిర్ధారించండి",
        "verify_body": "ఇది మీ ఇమెయిల్ చిరునామా అని నిర్ధారించండి. ఈ లింక్ {hours} గంటల పాటు పనిచేస్తుంది:",
        "verify_button": "నా ఇమెయిల్‌ను నిర్ధారించండి",
        "verify_ignore": "మీరు EduVerse AI ఖాతా సృష్టించకపోతే, ఈ ఇమెయిల్‌ను పట్టించుకోకండి.",
        "changed_subject": "మీ EduVerse AI పాస్‌వర్డ్ మార్చబడింది",
        "changed_body": "మీ పాస్‌వర్డ్ ఇప్పుడే మార్చబడింది, అన్ని పరికరాల నుండి మీరు సైన్ అవుట్ అయ్యారు.",
        "changed_warn": "ఇది మీరు చేయకపోతే, వెంటనే {link} లో పాస్‌వర్డ్ రీసెట్ చేసి, ఈ ఇమెయిల్‌కు రిప్లై ఇచ్చి మాకు తెలియజేయండి.",
        "signoff": "EduVerse AI బృందం",
    },
}


def _t(locale: str) -> dict[str, str]:
    return TEXT.get(locale, TEXT["en"])


def _compose(to: str, subject: str, paragraphs: list[str], link: str | None, button: str, category: str) -> Message:
    text = "\n\n".join(p if p != "{link}" else link or "" for p in paragraphs)
    html_parts = []
    for p in paragraphs:
        if p == "{link}":
            html_parts.append(
                f'<p><a href="{escape(link or "", quote=True)}" style="display:inline-block;padding:10px 18px;background:#4f46e5;color:#fff;'
                f'border-radius:8px;text-decoration:none">{escape(button)}</a></p>'
                f'<p style="font-size:12px;color:#555">{escape(link or "")}</p>'
            )
        else:
            html_parts.append(f"<p>{escape(p)}</p>")
    html = f'<div style="font-family:system-ui,sans-serif;font-size:15px;line-height:1.5;color:#111">{"".join(html_parts)}</div>'
    return Message(to=to, subject=subject, text=text, html=html, tags={"category": category})


def password_reset(name: str, to: str, locale: str, link: str, minutes: int) -> Message:
    t = _t(locale)
    paragraphs = [t["greeting"].format(name=name), t["reset_body"].format(minutes=minutes), "{link}", t["reset_ignore"], t["signoff"]]
    return _compose(to, t["reset_subject"], paragraphs, link, t["reset_button"], "password_reset")


def verify_email(name: str, to: str, locale: str, link: str, hours: int) -> Message:
    t = _t(locale)
    paragraphs = [t["greeting"].format(name=name), t["verify_body"].format(hours=hours), "{link}", t["verify_ignore"], t["signoff"]]
    return _compose(to, t["verify_subject"], paragraphs, link, t["verify_button"], "verify_email")


def password_changed(name: str, to: str, locale: str, reset_link: str) -> Message:
    t = _t(locale)
    paragraphs = [t["greeting"].format(name=name), t["changed_body"], t["changed_warn"].format(link=reset_link), t["signoff"]]
    return _compose(to, t["changed_subject"], paragraphs, None, "", "password_changed")


def invite(to: str, link: str, code: str, note: str, inviter: str) -> Message:
    """Invites go out before the person has an account, so they are bilingual."""
    en, te = TEXT["en"], TEXT["te"]
    paragraphs = [
        f"{inviter} invited you to the {BRAND} beta{f' ({note})' if note else ''}. Create your account with this link:",
        "{link}",
        f"Invite code: {code}",
        f"{inviter} మిమ్మల్ని {BRAND} బీటాకు ఆహ్వానించారు. పై లింక్‌తో మీ ఖాతా సృష్టించండి.",
        f"{en['signoff']} · {te['signoff']}",
    ]
    return _compose(to, f"You're invited to {BRAND}", paragraphs, link, "Create my account", "invite")
