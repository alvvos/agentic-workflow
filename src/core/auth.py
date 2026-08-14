import json
import os

import flask
from werkzeug.security import check_password_hash

from src.core.config import MODO_DESARROLLO, server

_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "users.json")


def _load_users() -> dict:
    if not os.path.exists(_USERS_FILE):
        return {}
    with open(_USERS_FILE) as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    with open(_USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def _get_entry(users: dict, username: str) -> dict:
    """Normaliza la entrada del usuario al formato {password, role} sea cual sea el formato en disco."""
    entry = users.get(username)
    if entry is None:
        return {}
    if isinstance(entry, str):
        return {"password": entry, "role": "user"}
    return entry


def get_current_user() -> str:
    """Devuelve el nombre del usuario autenticado o '' en modo desarrollo."""
    if MODO_DESARROLLO:
        return "local_dev"
    return flask.session.get("user", "")


def get_current_role() -> str:
    """Devuelve el rol del usuario autenticado ('admin' | 'user')."""
    if MODO_DESARROLLO:
        return "admin"
    return flask.session.get("role", "user")


def is_admin() -> bool:
    return get_current_role() == "admin"


def get_current_org_access() -> list | None:
    """Devuelve la lista de org_uuids accesibles, o None si el usuario ve todo (admin/dev)."""
    if MODO_DESARROLLO:
        return None
    if flask.session.get("role") == "admin":
        return None
    return flask.session.get("org_access", [])


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acceso — Panel Analítico</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Inter',system-ui,sans-serif;min-height:100vh;display:flex;background:#0b0b0e}

    /* ── Panel izquierdo ── */
    .left-panel{
      flex:1;display:flex;flex-direction:column;justify-content:space-between;
      padding:44px 52px;background:#0b0b0e;position:relative;overflow:hidden;min-height:100vh
    }
    .left-panel::after{
      content:'';position:absolute;inset:0;pointer-events:none;
      background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
      opacity:.028
    }
    .left-brand{position:relative;z-index:1;display:flex;align-items:center;gap:10px}
    .left-brand img{height:34px;width:34px;object-fit:contain;opacity:.9}
    .left-brand-name{
      font-size:.78rem;font-weight:500;color:rgba(255,255,255,.38);
      letter-spacing:.04em
    }
    .left-headline{position:relative;z-index:1}
    .left-headline h1{
      font-family:'Syne',sans-serif;font-size:4.2rem;font-weight:800;
      line-height:.96;letter-spacing:-.04em;color:#fff;margin-bottom:1.4rem
    }
    .left-headline h1 span{color:rgba(255,255,255,.22)}
    .left-headline p{
      font-size:.875rem;font-weight:300;color:rgba(255,255,255,.38);
      line-height:1.7;max-width:300px;letter-spacing:.01em
    }

    /* Visualización de afluencia */
    .chart-wrap{position:relative;z-index:1;margin:0 -8px}
    .chart-label{
      font-size:.65rem;font-weight:500;color:rgba(255,255,255,.2);
      letter-spacing:.06em;text-transform:uppercase;margin-bottom:10px
    }
    .chart-days{
      display:flex;justify-content:space-between;
      font-size:.6rem;color:rgba(255,255,255,.18);margin-top:6px;padding:0 2px
    }

    /* Footer del panel */
    .left-footer{
      position:relative;z-index:1;display:flex;gap:28px;
      border-top:1px solid rgba(255,255,255,.06);padding-top:20px
    }
    .left-footer-item{display:flex;flex-direction:column;gap:2px}
    .left-footer-num{font-size:1.1rem;font-weight:700;color:rgba(255,255,255,.7);letter-spacing:-.02em}
    .left-footer-label{font-size:.62rem;color:rgba(255,255,255,.22);letter-spacing:.05em;text-transform:uppercase}

    /* ── Panel derecho ── */
    .right-panel{
      width:460px;min-width:380px;display:flex;align-items:center;justify-content:center;
      padding:48px 40px;background:#f7f7f5;min-height:100vh;position:relative
    }
    .right-panel::before{
      content:'';position:absolute;top:0;left:0;width:1px;height:100%;
      background:linear-gradient(180deg,transparent,rgba(0,0,0,.06) 30%,rgba(0,0,0,.06) 70%,transparent)
    }
    .form-wrap{width:100%;max-width:340px}
    .form-wrap h2{
      font-family:'Syne',sans-serif;font-size:1.9rem;font-weight:700;
      color:#0b0b0e;margin-bottom:6px;letter-spacing:-.02em
    }
    .form-wrap .subtitle{font-size:.82rem;color:#a0a0a0;margin-bottom:32px;line-height:1.5}

    /* Inputs */
    .field{margin-bottom:18px}
    .field label{
      display:block;font-size:.7rem;font-weight:600;color:#5a5a5a;
      margin-bottom:7px;letter-spacing:.03em;text-transform:uppercase
    }
    .field input{
      width:100%;padding:11px 14px;border:1.5px solid #e2e2df;border-radius:8px;
      font-family:'Inter',sans-serif;font-size:.875rem;color:#0b0b0e;background:#fff;
      transition:border-color .15s,box-shadow .15s;outline:none
    }
    .field input:focus{border-color:#0b0b0e;box-shadow:0 0 0 3px rgba(11,11,14,.08);background:#fff}
    .field input::placeholder{color:#c8c8c4}
    .pwd-wrap{position:relative}
    .pwd-wrap input{padding-right:42px}
    .toggle-pwd{
      position:absolute;right:12px;top:50%;transform:translateY(-50%);
      background:none;border:none;cursor:pointer;color:#b0b0aa;padding:2px;
      display:flex;align-items:center;transition:color .15s
    }
    .toggle-pwd:hover{color:#0b0b0e}

    /* Error */
    .alert-err{
      background:#fff5f5;border:1.5px solid #f5c6c6;border-radius:8px;
      color:#c0392b;font-size:.78rem;padding:10px 14px;margin-bottom:18px;
      display:flex;gap:8px;align-items:flex-start;line-height:1.4
    }

    /* Botón */
    .btn-submit{
      width:100%;padding:12px;border:none;border-radius:8px;cursor:pointer;
      font-family:'Inter',sans-serif;font-size:.875rem;font-weight:600;letter-spacing:.01em;
      background:#0b0b0e;color:#fff;margin-top:4px;
      transition:background .15s,transform .1s,box-shadow .15s;
      box-shadow:0 2px 8px rgba(11,11,14,.18)
    }
    .btn-submit:hover{background:#222;box-shadow:0 4px 16px rgba(11,11,14,.28)}
    .btn-submit:active{transform:scale(.99)}

    .footer-note{font-size:.68rem;color:#c0bfba;text-align:center;margin-top:22px;line-height:1.5}

    @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
    .form-wrap{animation:fadeUp .35s ease both}

    @media(max-width:700px){
      .left-panel{display:none}
      .right-panel{width:100%;min-width:unset;padding:40px 24px;background:#fff}
      .right-panel::before{display:none}
    }
  </style>
</head>
<body>

<!-- Panel izquierdo -->
<div class="left-panel">
  <div class="left-brand">
    <img src="/assets/logo_summer.png" alt="Summer of 69">
    <span class="left-brand-name">Summer of 69</span>
  </div>

  <div class="left-headline">
    <h1>Retail<br><span>intel</span>li<br>gence.</h1>
    <p>Afluencia en tiempo real, forecasts por zona y detección automática de anomalías.</p>
  </div>

  <div class="chart-wrap">
    <div class="chart-label">Afluencia semanal</div>
    <svg width="100%" height="110" viewBox="0 0 560 110" preserveAspectRatio="none" fill="none" xmlns="http://www.w3.org/2000/svg">
      <!-- Líneas de cuadrícula -->
      <line x1="0" y1="90" x2="560" y2="90" stroke="rgba(255,255,255,.05)" stroke-width="1"/>
      <line x1="0" y1="60" x2="560" y2="60" stroke="rgba(255,255,255,.05)" stroke-width="1"/>
      <line x1="0" y1="30" x2="560" y2="30" stroke="rgba(255,255,255,.05)" stroke-width="1"/>
      <!-- Área rellena zona 1 -->
      <path d="M0,85 C30,82 55,75 80,68 C105,61 120,55 145,42 C170,29 185,18 210,14 C235,10 255,20 280,28 C305,36 320,44 345,55 C370,66 390,72 415,65 C440,58 460,40 490,28 C515,18 535,22 560,25 L560,110 L0,110 Z"
        fill="url(#areaGrad)" opacity=".5"/>
      <!-- Área rellena zona 2 (offset) -->
      <path d="M0,90 C25,87 50,82 75,78 C100,74 125,70 150,62 C175,54 195,46 220,50 C245,54 265,65 290,70 C315,75 335,72 360,66 C385,60 405,52 430,58 C455,64 475,72 505,68 C525,65 545,60 560,58 L560,110 L0,110 Z"
        fill="rgba(255,255,255,.03)"/>
      <!-- Línea principal -->
      <path d="M0,85 C30,82 55,75 80,68 C105,61 120,55 145,42 C170,29 185,18 210,14 C235,10 255,20 280,28 C305,36 320,44 345,55 C370,66 390,72 415,65 C440,58 460,40 490,28 C515,18 535,22 560,25"
        stroke="rgba(255,255,255,.55)" stroke-width="1.5" stroke-linecap="round"/>
      <!-- Puntos destacados (picos) -->
      <circle cx="210" cy="14" r="3" fill="#fff" opacity=".8"/>
      <circle cx="490" cy="28" r="3" fill="#fff" opacity=".8"/>
      <circle cx="80" cy="68" r="2" fill="rgba(255,255,255,.4)"/>
      <circle cx="345" cy="55" r="2" fill="rgba(255,255,255,.4)"/>
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1" gradientUnits="objectBoundingBox">
          <stop offset="0%" stop-color="rgba(255,255,255,.18)"/>
          <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
        </linearGradient>
      </defs>
    </svg>
    <div class="chart-days">
      <span>Lun</span><span>Mar</span><span>Mié</span><span>Jue</span><span>Vie</span><span>Sáb</span><span>Dom</span>
    </div>
  </div>

  <div class="left-footer">
    <div class="left-footer-item">
      <span class="left-footer-num">14d</span>
      <span class="left-footer-label">Forecast</span>
    </div>
    <div class="left-footer-item">
      <span class="left-footer-num">Multi-org</span>
      <span class="left-footer-label">Arquitectura</span>
    </div>
    <div class="left-footer-item">
      <span class="left-footer-num">XGBoost</span>
      <span class="left-footer-label">Motor ML</span>
    </div>
  </div>
</div>

<!-- Panel derecho: formulario -->
<div class="right-panel">
  <div class="form-wrap">
    <h2>Bienvenido</h2>
    <p class="subtitle">Introduce tus credenciales para acceder al panel.</p>

    {% if error %}
    <div class="alert-err">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16" style="flex-shrink:0;margin-top:1px">
        <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
      </svg>
      {{ error }}
    </div>
    {% endif %}

    <form method="post" autocomplete="on">
      <div class="field">
        <label for="username">Usuario</label>
        <input type="text" id="username" name="username" placeholder="tu.usuario" autofocus required autocomplete="username">
      </div>
      <div class="field">
        <label for="password">Contraseña</label>
        <div class="pwd-wrap">
          <input type="password" id="password" name="password" placeholder="••••••••" required autocomplete="current-password">
          <button type="button" class="toggle-pwd" onclick="togglePwd()" tabindex="-1" aria-label="Mostrar contraseña">
            <svg id="eye-icon" xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="currentColor" viewBox="0 0 16 16">
              <path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8zM1.173 8a13.133 13.133 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.133 13.133 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5c-2.12 0-3.879-1.168-5.168-2.457A13.134 13.134 0 0 1 1.172 8z"/>
              <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z"/>
            </svg>
          </button>
        </div>
      </div>
      <button type="submit" class="btn-submit">Acceder</button>
    </form>

    <p class="footer-note">Acceso restringido a usuarios autorizados.</p>
  </div>
</div>

<script>
function togglePwd(){
  var inp=document.getElementById('password');
  var ico=document.getElementById('eye-icon');
  if(inp.type==='password'){
    inp.type='text';
    ico.innerHTML='<path d="M13.359 11.238C15.06 9.72 16 8 16 8s-3-5.5-8-5.5a7.028 7.028 0 0 0-2.79.588l.77.771A5.944 5.944 0 0 1 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.134 13.134 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755-.165.165-.337.328-.517.486l.708.709z"/><path d="M11.297 9.176a3.5 3.5 0 0 0-4.474-4.474l.823.823a2.5 2.5 0 0 1 2.829 2.829l.822.822zm-2.943 1.299.822.822a3.5 3.5 0 0 1-4.474-4.474l.823.823a2.5 2.5 0 0 0 2.829 2.829z"/><path d="M3.35 5.47c-.18.16-.353.322-.518.487A13.134 13.134 0 0 0 1.172 8l.195.288c.335.48.83 1.12 1.465 1.755C4.121 11.332 5.881 12.5 8 12.5c.716 0 1.39-.133 2.02-.36l.77.772A7.029 7.029 0 0 1 8 13.5C3 13.5 0 8 0 8s.939-1.721 2.641-3.238l.708.709z"/><path fill-rule="evenodd" d="M13.646 14.354l-12-12 .708-.708 12 12-.708.708z"/>';
  }else{
    inp.type='password';
    ico.innerHTML='<path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8zM1.173 8a13.133 13.133 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.133 13.133 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5c-2.12 0-3.879-1.168-5.168-2.457A13.134 13.134 0 0 1 1.172 8z"/><path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z"/>';
  }
}
</script>
</body>
</html>"""

_ALLOWED_PATHS = ("/login", "/logout", "/_dash-component-suites/", "/assets/")


@server.before_request
def require_login():
    if MODO_DESARROLLO:
        return
    if any(flask.request.path.startswith(p) for p in _ALLOWED_PATHS):
        return
    if not flask.session.get("user"):
        return flask.redirect("/login")


@server.route("/login", methods=["GET", "POST"])
def login():
    if flask.request.method == "POST":
        username = flask.request.form.get("username", "").strip()
        password = flask.request.form.get("password", "")

        authenticated = False
        role = "user"

        # Primary: PostgreSQL usuarios
        try:
            from src.db.store import get_conn

            conn = get_conn()
            row = conn.execute(
                "SELECT password_hash, rol FROM usuarios WHERE usuario_id = ?",
                [username],
            ).fetchone()
            if row and check_password_hash(row[0], password):
                authenticated = True
                role = row[1] or "user"
                conn.execute(
                    "UPDATE usuarios SET ultimo_acceso = current_timestamp WHERE usuario_id = ?",
                    [username],
                )
        except Exception:
            pass

        # Fallback: users.json (transitional, while DB is being populated)
        if not authenticated:
            users = _load_users()
            entry = _get_entry(users, username)
            if entry and check_password_hash(entry["password"], password):
                authenticated = True
                role = entry.get("role", "user")

        if authenticated:
            flask.session["user"] = username
            flask.session["role"] = role
            if role != "admin":
                try:
                    from src.db.store import get_conn

                    rows = (
                        get_conn()
                        .execute(
                            "SELECT org_id FROM accesos_usuario WHERE usuario_id = ?", [username]
                        )
                        .fetchall()
                    )
                    flask.session["org_access"] = [r[0] for r in rows]
                except Exception:
                    flask.session["org_access"] = []
            return flask.redirect("/")
        return flask.render_template_string(_LOGIN_HTML, error="Usuario o contraseña incorrectos")
    return flask.render_template_string(_LOGIN_HTML, error=None)


@server.route("/logout")
def logout():
    flask.session.clear()
    return flask.redirect("/login")
