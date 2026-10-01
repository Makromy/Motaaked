import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.config import settings


def _save_local_email_preview(to_email: str, subject: str, html_content: str):
    """Saves the dispatched email HTML locally only when explicitly enabled for developer inspection."""
    enabled = os.getenv("ENABLE_LOCAL_EMAIL_PREVIEW", "").lower() in ["true", "1"]
    if not enabled:
        return
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "email_previews")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        preview_file = os.path.join(data_dir, "latest_email_preview.html")
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"[EMAIL PREVIEW WRITE WARNING] {e}")


def _get_portal_name(db: Optional[Session] = None, *args, **kwargs) -> str:
    """Retrieves current portal brand name from .env, system settings, or fallback default."""
    try:
        from dotenv import dotenv_values
        env = {}
        try:
            env_path = os.path.join(os.getcwd(), ".env")
            if os.path.exists(env_path):
                env = dotenv_values(env_path)
            else:
                env = dotenv_values(".env")
        except Exception:
            pass

        dot_name = env.get("PORTAL_NAME")
        if dot_name:
            clean = str(dot_name).strip().strip('"\';')
            if clean:
                return clean

        from app.services import get_system_settings
        if db is not None:
            s = get_system_settings(db)
            return s.get("portal_name") or getattr(settings, "PORTAL_NAME", None) or os.getenv("PORTAL_NAME", "Motaaked")

        from app.database import SessionLocal
        with SessionLocal() as s_db:
            s = get_system_settings(s_db)
            return s.get("portal_name") or getattr(settings, "PORTAL_NAME", None) or os.getenv("PORTAL_NAME", "Motaaked")
    except Exception:
        return getattr(settings, "PORTAL_NAME", None) or os.getenv("PORTAL_NAME", "Motaaked")


def _get_smtp_config(db: Optional[Session] = None) -> dict:
    """
    Dynamically resolves SMTP parameters on-the-fly.
    Checks:
      1. Database system_settings table (allows instant admin UI config without Docker restart)
      2. .env file on disk (both current directory, /app/.env, data/.env)
      3. os.environ
      4. app.config.settings (fallback & test monkeypatching)
    Cleans surrounding quotes, whitespace, and brackets.
    """
    db_cfg = {}
    try:
        from app.services import get_system_settings
        if db is not None:
            s = get_system_settings(db)
            if s.get("smtp_from"):
                db_cfg["from_email"] = str(s.get("smtp_from")).strip().strip('"\';')
            if s.get("smtp_host"):
                db_cfg["host"] = str(s.get("smtp_host")).strip().strip('"\';')
            if s.get("smtp_port"):
                try:
                    db_cfg["port"] = int(s.get("smtp_port"))
                except Exception:
                    pass
            if s.get("smtp_user"):
                db_cfg["user"] = str(s.get("smtp_user")).strip().strip('"\';')
            if s.get("smtp_password"):
                db_cfg["password"] = str(s.get("smtp_password")).strip().strip('"\';')
            if "smtp_tls" in s and s["smtp_tls"] is not None:
                db_cfg["tls"] = bool(s.get("smtp_tls"))
        else:
            from app.database import SessionLocal
            with SessionLocal() as s_db:
                s = get_system_settings(s_db)
                if s.get("smtp_from"):
                    db_cfg["from_email"] = str(s.get("smtp_from")).strip().strip('"\';')
                if s.get("smtp_host"):
                    db_cfg["host"] = str(s.get("smtp_host")).strip().strip('"\';')
                if s.get("smtp_port"):
                    try:
                        db_cfg["port"] = int(s.get("smtp_port"))
                    except Exception:
                        pass
                if s.get("smtp_user"):
                    db_cfg["user"] = str(s.get("smtp_user")).strip().strip('"\';')
                if s.get("smtp_password"):
                    db_cfg["password"] = str(s.get("smtp_password")).strip().strip('"\';')
                if "smtp_tls" in s and s["smtp_tls"] is not None:
                    db_cfg["tls"] = bool(s.get("smtp_tls"))
    except Exception:
        pass

    from dotenv import dotenv_values
    env = {}
    for candidate_path in [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.getcwd(), "data", ".env"),
        "/app/.env",
        ".env"
    ]:
        if os.path.exists(candidate_path):
            try:
                env = dotenv_values(candidate_path)
                if env:
                    break
            except Exception:
                pass

    def _val(key_list, fallback=""):
        for k in key_list:
            if k in env and env[k] is not None and str(env[k]).strip():
                v = str(env[k]).strip().strip('"\';')
                if v:
                    return v
            if os.getenv(k):
                v = os.getenv(k).strip().strip('"\';')
                if v:
                    return v
            if hasattr(settings, k) and getattr(settings, k):
                v = str(getattr(settings, k)).strip().strip('"\';')
                if v:
                    return v
        return fallback

    host = db_cfg.get("host") or _val(["SMTP_HOST", "MAIL_HOST", "SMTP_SERVER"])
    port_str = _val(["SMTP_PORT", "MAIL_PORT"], fallback="587")
    try:
        port = db_cfg.get("port") or int(port_str)
    except Exception:
        port = 587
    user = db_cfg.get("user") or _val(["SMTP_USER", "MAIL_USERNAME", "MAIL_USER"])
    password = db_cfg.get("password") or _val(["SMTP_PASSWORD", "MAIL_PASSWORD", "MAIL_PASS"])
    from_email = (db_cfg.get("from_email") or _val(["SMTP_FROM", "MAIL_FROM_ADDRESS", "MAIL_FROM"], fallback="")).strip().lower()
    tls_raw = str(_val(["SMTP_TLS", "MAIL_ENCRYPTION"], fallback="true")).lower()
    default_tls = tls_raw in ["true", "1", "yes", "tls", "starttls"]
    tls = db_cfg.get("tls", default_tls)

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_email": from_email,
        "tls": tls,
    }


def test_smtp_connection(to_email: Optional[str] = None, db: Optional[Session] = None) -> Tuple[bool, str]:
    """
    Directly tests SMTP connectivity, TLS negotiation, and authentication.
    Optionally sends a test ping email if to_email is provided.
    Returns (success: bool, message: str)
    """
    cfg = _get_smtp_config(db=db)
    if not cfg["host"]:
        return False, "SMTP Host is not configured."
    if not cfg["user"] or not cfg["password"]:
        return False, "SMTP Username and Password/Key are required."

    try:
        if cfg["port"] == 465:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=8)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=8)
            if hasattr(server, "ehlo"):
                server.ehlo()
            if cfg["tls"]:
                server.starttls()
                if hasattr(server, "ehlo"):
                    server.ehlo()

        server.login(cfg["user"], cfg["password"])

        if to_email and to_email.strip():
            target = to_email.strip()
            try:
                p_name = _get_portal_name(db=db) if db is not None else _get_portal_name()
            except TypeError:
                p_name = _get_portal_name()
            from email.utils import parseaddr, formataddr
            raw_sender = cfg["from_email"] or cfg["user"]
            _, bare_addr = parseaddr(raw_sender)
            from_addr = (bare_addr or raw_sender).strip().strip('"\'< >').lower()
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(f"[{p_name}] SMTP Connection Test", "utf-8")
            msg["From"] = formataddr((p_name, from_addr), charset="utf-8")
            msg["Reply-To"] = formataddr((p_name, from_addr), charset="utf-8")
            msg["To"] = target
            html = f"""<div style="font-family:sans-serif;padding:24px;background:#0b0f19;color:#e2e8f0;border-radius:12px;border:1px solid #1e293b;">
                <h2 style="color:#06b6d4;margin-top:0;">&#x2714; SMTP Test Successful!</h2>
                <p>Your mail server at <strong>{cfg['host']}:{cfg['port']}</strong> is properly connected and authenticated.</p>
                <p><strong>Sender:</strong> {from_addr}</p>
                <p style="font-size:12px;color:#94a3b8;margin-bottom:0;">Sent via {p_name} Super Admin Panel.</p>
            </div>"""
            msg.attach(MIMEText(html, "html", "utf-8"))
            server.sendmail(from_addr, [target], msg.as_bytes())

        server.quit()
        target_info = f" and sent test email to {to_email}" if (to_email and to_email.strip()) else ""
        return True, f"Successfully connected to {cfg['host']}:{cfg['port']} and authenticated with user {cfg['user']}{target_info}!"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Authentication failed: Invalid SMTP User or Password ({e.smtp_code}: {e.smtp_error.decode('utf-8', 'ignore') if isinstance(e.smtp_error, bytes) else str(e.smtp_error)})"
    except smtplib.SMTPConnectError as e:
        return False, f"Connection failed to {cfg['host']}:{cfg['port']}. Port {cfg['port']} might be blocked by your VPS provider ({e})."
    except Exception as e:
        err = str(e)
        if "timed out" in err.lower():
            return False, f"Connection timed out to {cfg['host']}:{cfg['port']}. Outgoing port {cfg['port']} is likely blocked by your VPS hosting provider firewall. Try Port 2525 or 465 (SSL)."
        return False, f"SMTP Error: {err}"


def _send_smtp_email(to_email: str, subject: str, html_content: str, text_content: Optional[str] = None, db: Optional[Session] = None) -> Tuple[bool, Optional[str], bool]:
    """
    Core SMTP transport function.
    Dispatches via live SMTP (e.g. Brevo) if credentials configured,
    otherwise safely simulates sending and writes local preview.
    Returns (success: bool, error_message: Optional[str], is_simulated: bool)
    """
    try:
        p_name = _get_portal_name(db=db) if db is not None else _get_portal_name()
    except TypeError:
        p_name = _get_portal_name()
    _save_local_email_preview(to_email, subject, html_content)
    cfg = _get_smtp_config(db=db)

    if not cfg["host"] or not cfg["from_email"]:
        # SMTP not configured - simulate local success for seamless testing
        safe_subject = subject.encode("ascii", "replace").decode("ascii")
        print(f"\n[EMAIL SIMULATION] SMTP not configured. Simulating email dispatch to: {to_email}")
        print(f"Subject: {safe_subject}")
        return True, None, True

    try:
        import re
        from email.utils import parseaddr, formataddr

        # Extract bare email address from from_email regardless of whether it includes a name
        raw_from = cfg["from_email"]
        name_in_env, raw_email = parseaddr(raw_from)
        if not raw_email or "@" not in raw_email:
            m = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_from)
            raw_email = m.group(0) if m else raw_from.strip().strip('"\'< >')

        # Always dynamically use the active portal brand name (Admin Panel > .env > fallback)
        display_name = (p_name or name_in_env or "Motaaked").strip()
        from_header = formataddr((display_name, raw_email), charset="utf-8")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = from_header
        msg["Reply-To"] = from_header
        msg["To"] = to_email

        if text_content:
            part1 = MIMEText(text_content, "plain", "utf-8")
            msg.attach(part1)

        part2 = MIMEText(html_content, "html", "utf-8")
        msg.attach(part2)

        envelope_from = raw_email

        # Support both Direct SSL (Port 465) and STARTTLS (Port 587 / 2525)
        if cfg["port"] == 465:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=8)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=8)
            if hasattr(server, "ehlo"):
                server.ehlo()
            if cfg["tls"]:
                server.starttls()
                if hasattr(server, "ehlo"):
                    server.ehlo()

        if cfg["user"] and cfg["password"]:
            server.login(cfg["user"], cfg["password"])

        server.sendmail(envelope_from, [to_email], msg.as_bytes())
        server.quit()
        try:
            safe_subj = subject.encode("ascii", "replace").decode("ascii")
            print(f"[EMAIL DISPATCHED] Successfully sent '{safe_subj}' to {to_email} via {cfg['host']}:{cfg['port']} (From: {from_header})")
        except Exception:
            pass
        return True, None, False
    except Exception as e:
        err_msg = str(e)
        if "timed out" in err_msg.lower():
            err_msg = f"Connection to {cfg['host']}:{cfg['port']} timed out. Port {cfg['port']} is likely blocked by your VPS provider. Try Port 2525 or 465 (SSL)."
        elif "authentication" in err_msg.lower():
            err_msg = f"SMTP Authentication failed. Please verify your Brevo SMTP Key."
        try:
            print(f"[EMAIL ERROR] Failed to send email to {to_email}: {err_msg}")
        except Exception:
            pass
        return False, err_msg, False


def get_base_email_template(content_html: str, title: Optional[str] = None) -> str:
    """Renders responsive email wrapper matching the platform's dark cyan aesthetic."""
    brand_title = title or _get_portal_name()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{brand_title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #0b0f19;
      color: #e2e8f0;
      margin: 0;
      padding: 20px;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }}
    .header {{
      background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
      padding: 24px;
      text-align: center;
      border-bottom: 1px solid #312e81;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 800;
      color: #38bdf8;
      letter-spacing: -0.5px;
    }}
    .content {{
      padding: 28px 24px;
      font-size: 14px;
      line-height: 1.6;
      color: #cbd5e1;
    }}
    .code-box {{
      background: #030712;
      border: 1px dashed #38bdf8;
      border-radius: 8px;
      padding: 16px;
      text-align: center;
      font-family: 'Courier New', Courier, monospace;
      font-size: 24px;
      font-weight: bold;
      color: #38bdf8;
      letter-spacing: 4px;
      margin: 20px 0;
    }}
    .key-badge {{
      display: inline-block;
      background: #1e293b;
      color: #f1f5f9;
      font-family: monospace;
      padding: 4px 8px;
      border-radius: 4px;
      border: 1px solid #334155;
      word-break: break-all;
    }}
    .param-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0;
      font-size: 13px;
    }}
    .param-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid #1e293b;
    }}
    .param-name {{
      color: #94a3b8;
      font-weight: bold;
      width: 35%;
    }}
    .param-val {{
      color: #f1f5f9;
      font-family: monospace;
      word-break: break-all;
    }}
    .btn {{
      display: inline-block;
      background: #0284c7;
      color: #ffffff;
      text-decoration: none;
      padding: 12px 24px;
      border-radius: 8px;
      font-weight: bold;
      margin: 16px 0;
    }}
    .footer {{
      background: #0b0f19;
      padding: 16px 24px;
      text-align: center;
      font-size: 11px;
      color: #64748b;
      border-top: 1px solid #1f2937;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>⚡ {brand_title}</h1>
      <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 13px;">Automated InstaPay & IPN Verification Gateway for Merchants</p>
    </div>
    <div class="content">
      {content_html}
    </div>
    <div class="footer">
      <p style="margin: 0 0 4px 0;">This is an automated security communication for your {brand_title} merchant account.</p>
      <p style="margin: 0;">Keep your Passcode & API Keys private. Never share them with untrusted parties.</p>
    </div>
  </div>
</body>
</html>"""


def send_welcome_email(
    to_email: str,
    user_name: str,
    passcode: str,
    forwarder_key: str,
    server_url: str = "http://192.168.1.3:8000",
    cashier_pin: str = "A123C4",
) -> bool:
    """Sends registration confirmation with auto-generated Passcode, Cashier PIN, and complete SMS Forwarder setup instructions."""
    p_name = _get_portal_name()
    subject = f"⚡ Your {p_name} Access Passcode & SMS Forwarder Setup"
    webhook_url = f"{server_url.rstrip('/')}/v1/webhook/sms?api_key={forwarder_key}"
    heartbeat_url = f"{server_url.rstrip('/')}/v1/heartbeat/{forwarder_key}?battery=%battery%"

    content = f"""
      <h2 style="color: #f8fafc; margin-top: 0;">Welcome, {user_name}! 👋</h2>
      <p style="color: #cbd5e1;">Your merchant account has been activated with your trial period and starter search credits.</p>
      
      <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid #059669; border-radius: 8px; padding: 14px; margin: 18px 0;">
        <span style="color: #34d399; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">1. Your Merchant Login Passcode (Owner Master Code):</span>
        <div class="code-box" style="margin: 8px 0 0 0; font-size: 20px; font-weight: bold; color: #10b981; letter-spacing: 2px;">
          {passcode}
        </div>
        <p style="color: #94a3b8; font-size: 12px; margin: 6px 0 0 0;">Use this Passcode on the portal homepage to sign into your main dashboard.</p>
      </div>

      <div style="background: rgba(99, 102, 241, 0.1); border: 1px solid #4f46e5; border-radius: 8px; padding: 14px; margin: 18px 0;">
        <span style="color: #a5b4fc; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">2. Your Cashier Shift PIN (for Staff / POS Keypad):</span>
        <div class="code-box" style="margin: 8px 0 0 0; font-size: 20px; font-weight: bold; color: #818cf8; letter-spacing: 4px;">
          {cashier_pin}
        </div>
        <p style="color: #94a3b8; font-size: 12px; margin: 6px 0 0 0;">Give this 6-character PIN (4 digits & 2 letters) to store cashiers to unlock the Live Stream and POS screens without sharing your owner password.</p>
      </div>

      <hr style="border: 0; border-top: 1px solid #1e293b; margin: 24px 0;">

      <h3 style="color: #38bdf8; margin-bottom: 8px;">📱 Free SMS Forwarder App Setup (Android)</h3>
      <p style="color: #94a3b8; font-size: 13px; margin-top: 0;">
        Use the free & open-source <strong>SMS Forwarder</strong> Android app to automatically forward incoming bank SMS alerts to your live platform:
      </p>

      <div style="background: #0f172a; border: 1px solid #38bdf8; border-radius: 8px; padding: 12px 16px; margin: 12px 0;">
        <p style="margin: 0; font-size: 13px; color: #f8fafc;">
          📥 <strong>Step 1: Download SMS Forwarder App (Free on GitHub):</strong><br>
          <a href="https://github.com/bogkonstantin/android_income_sms_gateway_webhook/releases" style="color: #38bdf8; font-weight: bold; text-decoration: underline;">https://github.com/bogkonstantin/android_income_sms_gateway_webhook/releases</a>
        </p>
      </div>

      <div style="margin: 18px 0 8px 0;">
        <strong style="color: #f8fafc; font-size: 13px;">⚙️ Step 2: Configure Webhook in SMS Forwarder App:</strong>
      </div>

      <table class="param-table">
        <tr>
          <td class="param-name">1. Webhook URL:</td>
          <td class="param-val"><span class="key-badge">{webhook_url}</span></td>
        </tr>
        <tr>
          <td class="param-name">2. Target Sender:</td>
          <td class="param-val"><code>InstaPay</code> <span style="color:#94a3b8; font-size:11px;">(or your bank SMS sender)</span></td>
        </tr>
        <tr>
          <td class="param-name">3. Method:</td>
          <td class="param-val"><code>POST</code></td>
        </tr>
        <tr>
          <td class="param-name">4. Message Field:</td>
          <td class="param-val"><code>message</code> <span style="color:#94a3b8; font-size:11px;">(or %message%)</span></td>
        </tr>
        <tr>
          <td class="param-name">5. Sender Field:</td>
          <td class="param-val"><code>sender</code> <span style="color:#94a3b8; font-size:11px;">(or %sender%)</span></td>
        </tr>
      </table>

      <p style="color: #94a3b8; font-size: 12px; margin-top: 10px;">
        💡 <em>Tap <strong>TEST</strong> in the app to verify connection (returns Success), then tap <strong>ADD/SAVE</strong>!</em>
      </p>
    """
    html = get_base_email_template(content, title=f"Welcome to {p_name}")
    success, _, _ = _send_smtp_email(to_email=to_email, subject=subject, html_content=html)
    return success


def send_forgot_passcode_email(
    to_email: str,
    user_name: str,
    passcode: str,
    forwarder_key: str,
    server_url: str = "http://192.168.1.3:8000"
) -> bool:
    """Sends active passcode to verified email address for account recovery."""
    p_name = _get_portal_name()
    subject = f"🔑 Your {p_name} Access Passcode"
    content = f"""
      <h2 style="color: #f8fafc; margin-top: 0;">Hello, {user_name} 🔑</h2>
      <p style="color: #cbd5e1;">You requested your {p_name} login passcode. Here is your active credentials:</p>
      
      <div style="background: rgba(56, 189, 248, 0.1); border: 1px solid #0284c7; border-radius: 8px; padding: 14px; margin: 18px 0;">
        <span style="color: #38bdf8; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Active Login Passcode:</span>
        <div class="code-box" style="margin: 8px 0 0 0; font-size: 20px; font-weight: bold; color: #38bdf8; letter-spacing: 2px;">
          {passcode}
        </div>
      </div>

      <p style="color: #cbd5e1; font-size: 14px;">
        <strong>Your Dedicated Forwarder API Key:</strong><br>
        <span class="key-badge">{forwarder_key}</span>
      </p>

      <p style="color: #94a3b8; font-size: 12px; margin-top: 20px;">
        If you did not request this recovery email, please check your account security or contact your portal administrator.
      </p>
    """
    html = get_base_email_template(content, title=f"{p_name} Passcode Recovery")
    success, _, _ = _send_smtp_email(to_email=to_email, subject=subject, html_content=html)
    return success


def send_forwarder_setup_email(
    to_email: str,
    user_name: str,
    forwarder_key: str,
    server_url: str = "http://192.168.1.3:8000"
) -> bool:
    """Dispatches the complete SMS Forwarder configuration parameters directly to user's email."""
    success, _, _ = send_forwarder_setup_email_detailed(
        to_email=to_email,
        user_name=user_name,
        forwarder_key=forwarder_key,
        server_url=server_url,
    )
    return success


def send_forwarder_setup_email_detailed(
    to_email: str,
    user_name: str,
    forwarder_key: str,
    server_url: str = "http://192.168.1.3:8000",
    db: Optional[Session] = None,
) -> tuple[bool, Optional[str], bool]:
    """Dispatches the SMS Forwarder setup and returns (success, error_msg, is_simulated)."""
    subject = "📱 SMS Forwarder Mobile Setup & Dedicated API Key"
    webhook_url = f"{server_url.rstrip('/')}/v1/webhook/sms?api_key={forwarder_key}"
    heartbeat_url = f"{server_url.rstrip('/')}/v1/heartbeat/{forwarder_key}?battery=%battery%"

    content = f"""
      <h2 style="color: #f8fafc; margin-top: 0;">Free SMS Forwarder Mobile Setup 📱</h2>
      <p style="color: #cbd5e1;">Here are your dedicated parameters to configure the free & open-source <strong>SMS Forwarder</strong> Android app on your mobile phone:</p>

      <div style="background: #0f172a; border: 1px solid #38bdf8; border-radius: 8px; padding: 12px 16px; margin: 14px 0;">
        <p style="margin: 0; font-size: 13px; color: #f8fafc;">
          📥 <strong>1. Download App from GitHub (Free & Open Source):</strong><br>
          <a href="https://github.com/bogkonstantin/android_income_sms_gateway_webhook/releases" style="color: #38bdf8; font-weight: bold; text-decoration: underline;">https://github.com/bogkonstantin/android_income_sms_gateway_webhook/releases</a>
        </p>
      </div>

      <h4 style="color: #f8fafc; font-size: 14px; margin: 16px 0 6px 0;">⚙️ 2. App Routing & Webhook Parameters:</h4>

      <table class="param-table">
        <tr>
          <td class="param-name">Sender</td>
          <td class="param-val" style="color: #f8fafc;">* (or bank names like NBE, CIB, BM, QNB, ALEXBANK, AAIB, HSBC)</td>
        </tr>
        <tr>
          <td class="param-name">Incoming SMS Webhook URL</td>
          <td class="param-val">{webhook_url}</td>
        </tr>
        <tr>
          <td class="param-name">Heartbeat Monitoring URL</td>
          <td class="param-val" style="color: #38bdf8; font-weight: bold;">{heartbeat_url}</td>
        </tr>
        <tr>
          <td class="param-name">Heartbeat Interval</td>
          <td class="param-val" style="color: #34d399; font-weight: bold;">5 Minutes</td>
        </tr>
        <tr>
          <td class="param-name">JSON Payload Template</td>
          <td class="param-val" style="color: #a7f3d0;">{{"from": "%from%", "text": "%text%", "battery": %battery%}}</td>
        </tr>
        <tr>
          <td class="param-name">Headers</td>
          <td class="param-val">{{"Content-Type": "application/json"}}</td>
        </tr>
        <tr>
          <td class="param-name">Dedicated Forwarder Key</td>
          <td class="param-val" style="color: #fbbf24;">{forwarder_key}</td>
        </tr>
        <tr>
          <td class="param-name">Store failed messages for retry</td>
          <td class="param-val" style="color: #34d399;">ON (Enabled)</td>
        </tr>
      </table>

      <div style="background: #030712; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; margin-top: 16px;">
        <h4 style="margin: 0 0 8px 0; color: #f8fafc; font-size: 14px;">💡 Quick Setup Steps in SMS Forwarder:</h4>
        <ol style="margin: 0; padding-left: 18px; color: #94a3b8; font-size: 13px; line-height: 1.6;">
          <li>Install the APK from the GitHub link above.</li>
          <li>Open the app &rarr; Click <strong>Add (+)</strong> to create a new webhook rule.</li>
          <li>Set <strong>Sender</strong> to <code>*</code>.</li>
          <li>Paste the <strong>Incoming SMS Webhook URL</strong> above into the Webhook URL field.</li>
          <li>Paste the <strong>JSON Payload Template</strong> above into the Request Body.</li>
          <li>Set <strong>Headers</strong> to <code>{{"Content-Type": "application/json"}}</code>.</li>
          <li>Tap <strong>TEST</strong> (returns Success 201 Created), then tap <strong>ADD</strong> to save!</li>
          <li><strong>Heartbeat Monitoring (Live Stream POS):</strong> Go to <strong>Settings</strong> &rarr; scroll to <strong>HEARTBEAT MONITORING</strong> &rarr; Paste the <strong>Heartbeat Monitoring URL</strong> &rarr; Set Interval to <strong>5 minutes</strong> &rarr; Tap <strong>TEST</strong> (returns Success) &rarr; Tap <strong>SAVE</strong>!</li>
        </ol>
      </div>
    """
    html = get_base_email_template(content, title="SMS Forwarder Mobile Setup")
    return _send_smtp_email(to_email=to_email, subject=subject, html_content=html, db=db)


def send_gift_voucher_email(
    to_email: str,
    user_name: str,
    voucher_code: str,
    plan_name: str,
    credits: int,
    duration_days: int,
    expires_at_str: str,
    server_url: str = "http://localhost:8000"
) -> bool:
    """Dispatches a purchased one-time gift voucher code to the purchaser or recipient."""
    p_name = _get_portal_name()
    subject = f"🎁 Your {p_name} Gift Voucher Code: {voucher_code}"

    content = f"""
      <div style="text-align: center; margin-bottom: 20px;">
        <span style="font-size: 40px;">🎁</span>
        <h2 style="color: #f8fafc; margin: 8px 0 4px 0;">Your Gift Voucher is Ready!</h2>
        <p style="color: #94a3b8; font-size: 14px;">Purchased by <strong>{user_name}</strong> for <strong>{plan_name}</strong></p>
      </div>

      <div style="background: #030712; border: 2px dashed #6366f1; border-radius: 16px; padding: 24px; text-align: center; margin: 24px 0;">
        <div style="font-size: 12px; font-weight: 700; color: #a5b4fc; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px;">
          One-Time Voucher Code
        </div>
        <div style="font-family: 'Courier New', Courier, monospace; font-size: 28px; font-weight: 900; color: #38bdf8; letter-spacing: 3px; margin: 12px 0;">
          {voucher_code}
        </div>
        <div style="display: inline-block; background: #1e1b4b; border: 1px solid #4338ca; color: #c7d2fe; font-size: 12px; font-weight: 600; padding: 4px 12px; rounded-radius: 20px; border-radius: 20px;">
          Includes: +{credits} Search Credits & +{duration_days} Days Access
        </div>
        <div style="margin-top: 14px; color: #fbbf24; font-size: 12px; font-weight: 600;">
          ⏳ Valid for 90 Days &bull; Expires on: {expires_at_str}
        </div>
      </div>

      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 18px; margin: 20px 0;">
        <h4 style="margin: 0 0 10px 0; color: #f8fafc; font-size: 14px;">📌 How to Redeem this Gift Voucher:</h4>
        <ol style="margin: 0; padding-left: 20px; color: #cbd5e1; font-size: 13px; line-height: 1.7;">
          <li>Log into <strong>{p_name}</strong> at <a href="{server_url}" style="color: #818cf8; text-decoration: underline;">{server_url}</a></li>
          <li>Navigate to the <strong>Top-Up & Renewals</strong> tab.</li>
          <li>Scroll to the <strong>"Redeem Gift Voucher"</strong> section.</li>
          <li>Paste the code <code>{voucher_code}</code> and click <strong>Apply Voucher</strong>.</li>
        </ol>
      </div>

      <p style="color: #64748b; font-size: 11px; text-align: center; margin-top: 24px;">
        Note: This is a one-time redemption code. Once applied by any user, it cannot be reused.
      </p>
    """
    html = get_base_email_template(content, title=f"{p_name} Gift Voucher")
    success, _, _ = _send_smtp_email(to_email=to_email, subject=subject, html_content=html)
    return success


def send_ticket_created_emails(ticket) -> bool:
    """
    Sends two emails upon trouble ticket creation:
    1. Confirmation receipt to the merchant with ticket tracking code.
    2. High-priority alert to the Super Admin.
    """
    p_name = _get_portal_name()
    ref_row = f"""<tr>
      <td style="padding: 8px 12px; color: #94a3b8; font-weight: 600;">InstaPay Ref ID:</td>
      <td style="padding: 8px 12px; color: #38bdf8; font-family: monospace; font-weight: bold;">{ticket.reference_id}</td>
    </tr>""" if ticket.reference_id else ""

    phone_row = f"""<tr>
      <td style="padding: 8px 12px; color: #94a3b8; font-weight: 600;">Phone / WhatsApp:</td>
      <td style="padding: 8px 12px; color: #f8fafc;">{ticket.merchant_phone}</td>
    </tr>""" if ticket.merchant_phone else ""

    # 1. Email to Merchant
    merchant_subject = f"🎫 [{ticket.ticket_code}] Support Ticket Received - {p_name}"
    merchant_content = f"""
      <div style="text-align: center; margin-bottom: 24px;">
        <span style="font-size: 42px;">🎫</span>
        <h2 style="color: #f8fafc; margin: 8px 0 4px 0;">We've Received Your Support Ticket</h2>
        <p style="color: #94a3b8; font-size: 14px;">Hello <strong>{ticket.merchant_name}</strong>, our technical support team has logged your inquiry.</p>
      </div>

      <div style="background: #030712; border: 1px solid #1e293b; border-radius: 16px; padding: 20px; margin: 20px 0;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #1e293b; padding-bottom: 12px; margin-bottom: 12px;">
          <span style="color: #a5b4fc; font-size: 12px; font-weight: 700; text-transform: uppercase;">Tracking Code</span>
          <span style="font-family: monospace; font-size: 16px; font-weight: 900; color: #38bdf8;">{ticket.ticket_code}</span>
        </div>
        <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
          <tr>
            <td style="padding: 8px 12px; color: #94a3b8; font-weight: 600; width: 35%;">Category:</td>
            <td style="padding: 8px 12px; color: #f8fafc; font-weight: bold;">{ticket.category.replace('_', ' ').title()}</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; color: #94a3b8; font-weight: 600;">Subject:</td>
            <td style="padding: 8px 12px; color: #f8fafc;">{ticket.subject}</td>
          </tr>
          {ref_row}
        </table>
      </div>

      <div style="background: #0f172a; border-left: 4px solid #6366f1; border-radius: 0 12px 12px 0; padding: 16px; margin: 20px 0;">
        <div style="color: #94a3b8; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 6px;">Your Message:</div>
        <div style="color: #e2e8f0; font-size: 13px; line-height: 1.6; white-space: pre-wrap;">{ticket.message}</div>
      </div>

      <p style="color: #94a3b8; font-size: 13px; text-align: center; margin-top: 24px;">
        Our team is actively reviewing your request and will respond directly to this email address ({ticket.merchant_email}).
      </p>
    """
    html_merchant = get_base_email_template(merchant_content, title=f"Support Ticket #{ticket.ticket_code}")
    _send_smtp_email(to_email=ticket.merchant_email, subject=merchant_subject, html_content=html_merchant)

    # 2. Email to Admin
    try:
        from app.database import SessionLocal
        from app.services import get_system_settings
        with SessionLocal() as db:
            s = get_system_settings(db)
            admin_email = s.get("support_admin_email") or settings.SMTP_USER or "haitham.refaat@gmail.com"
    except Exception:
        admin_email = settings.SMTP_USER or "haitham.refaat@gmail.com"

    if admin_email:
        admin_subject = f"🚨 New Trouble Ticket #{ticket.ticket_code} [{ticket.category.upper()}]: {ticket.subject}"
        admin_content = f"""
          <div style="border-left: 4px solid #ef4444; padding-left: 16px; margin-bottom: 20px;">
            <h2 style="color: #f8fafc; margin: 0 0 6px 0;">New Support Ticket Submitted</h2>
            <p style="color: #94a3b8; font-size: 13px; margin: 0;">A merchant has opened a trouble ticket on {p_name}.</p>
          </div>

          <div style="background: #030712; border: 1px solid #1e293b; border-radius: 12px; padding: 18px; margin: 16px 0;">
            <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
              <tr>
                <td style="padding: 6px 12px; color: #94a3b8; font-weight: 600; width: 35%;">Ticket Code:</td>
                <td style="padding: 6px 12px; color: #38bdf8; font-family: monospace; font-weight: bold;">{ticket.ticket_code}</td>
              </tr>
              <tr>
                <td style="padding: 6px 12px; color: #94a3b8; font-weight: 600;">Merchant Name:</td>
                <td style="padding: 6px 12px; color: #f8fafc; font-weight: bold;">{ticket.merchant_name}</td>
              </tr>
              <tr>
                <td style="padding: 6px 12px; color: #94a3b8; font-weight: 600;">Merchant Email:</td>
                <td style="padding: 6px 12px; color: #a5b4fc;"><a href="mailto:{ticket.merchant_email}" style="color: #818cf8;">{ticket.merchant_email}</a></td>
              </tr>
              {phone_row}
              <tr>
                <td style="padding: 6px 12px; color: #94a3b8; font-weight: 600;">Category:</td>
                <td style="padding: 6px 12px; color: #fbbf24; font-weight: bold;">{ticket.category.replace('_', ' ').title()}</td>
              </tr>
              <tr>
                <td style="padding: 6px 12px; color: #94a3b8; font-weight: 600;">Subject:</td>
                <td style="padding: 6px 12px; color: #f8fafc;">{ticket.subject}</td>
              </tr>
              {ref_row}
            </table>
          </div>

          <div style="background: #0f172a; border-radius: 12px; padding: 16px; margin: 16px 0;">
            <div style="color: #94a3b8; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 6px;">Message Body:</div>
            <div style="color: #e2e8f0; font-size: 13px; line-height: 1.6; white-space: pre-wrap;">{ticket.message}</div>
          </div>
        """
        html_admin = get_base_email_template(admin_content, title=f"New Ticket #{ticket.ticket_code}")
        _send_smtp_email(to_email=admin_email, subject=admin_subject, html_content=html_admin)

    return True


def send_ticket_status_update_email(ticket, reply_message: str) -> bool:
    """Dispatches resolution or reply email from Admin to the merchant."""
    p_name = _get_portal_name()
    subject = f"💬 Update on Ticket #{ticket.ticket_code}: {ticket.subject} - {p_name}"

    status_badge_color = "#10b981" if ticket.status == "RESOLVED" else "#6366f1"

    content = f"""
      <div style="margin-bottom: 20px;">
        <h2 style="color: #f8fafc; margin: 0 0 6px 0;">Support Ticket Update: #{ticket.ticket_code}</h2>
        <div style="display: inline-block; background: {status_badge_color}22; border: 1px solid {status_badge_color}; color: {status_badge_color}; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; text-transform: uppercase; margin-top: 4px;">
          Status: {ticket.status}
        </div>
      </div>

      <div style="background: #030712; border-left: 4px solid #38bdf8; border-radius: 0 12px 12px 0; padding: 18px; margin: 20px 0;">
        <div style="color: #38bdf8; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 8px;">Response from Support Team:</div>
        <div style="color: #f8fafc; font-size: 14px; line-height: 1.7; white-space: pre-wrap;">{reply_message}</div>
      </div>

      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 14px; margin: 20px 0; font-size: 12px; color: #94a3b8;">
        <div><strong>Original Subject:</strong> {ticket.subject}</div>
        <div style="margin-top: 4px;"><strong>Category:</strong> {ticket.category.replace('_', ' ').title()}</div>
      </div>

      <p style="color: #64748b; font-size: 12px; text-align: center; margin-top: 24px;">
        Need further assistance? You can reply directly to this email or open a new ticket on {p_name}.
      </p>
    """
    html = get_base_email_template(content, title=f"Ticket #{ticket.ticket_code} Update")
    success, _, _ = _send_smtp_email(to_email=ticket.merchant_email, subject=subject, html_content=html)
    return success
