import os
import json
import flask
from werkzeug.security import check_password_hash
from src.core.config import MODO_DESARROLLO, server

_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'users.json')


def _load_users() -> dict:
    if not os.path.exists(_USERS_FILE):
        return {}
    with open(_USERS_FILE) as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    with open(_USERS_FILE, 'w') as f:
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
    return flask.session.get('user', '')


def get_current_role() -> str:
    """Devuelve el rol del usuario autenticado ('admin' | 'user')."""
    if MODO_DESARROLLO:
        return "admin"
    return flask.session.get('role', 'user')


def is_admin() -> bool:
    return get_current_role() == "admin"


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acceso — Panel Analítico</title>
  <link href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/lux/bootstrap.min.css" rel="stylesheet">
  <style>
    body{background:#f8f9fa;min-height:100vh;display:flex;align-items:center;justify-content:center}
    .login-card{width:100%;max-width:380px}
    .btn-primary{background:#0052CC;border-color:#0052CC}
    .btn-primary:hover{background:#003d99;border-color:#003d99}
    .text-brand{color:#0052CC}
    .toggle-pwd{cursor:pointer;background:#fff;border-left:0;color:#6c757d}
    .toggle-pwd:hover{color:#0052CC}
  </style>
</head>
<body>
<div class="login-card px-3">
  <div class="text-center mb-4">
    <img src="/assets/logo.png" style="max-height:60px;object-fit:contain" class="mb-3" alt="Logo">
    <h5 class="fw-bold text-brand mb-1">Panel analítico predictivo</h5>
    <p class="text-muted small mb-0">Introduce tus credenciales para acceder</p>
  </div>
  <div class="card shadow-sm border-0 rounded-4">
    <div class="card-body p-4 py-24">
      {% if error %}<div class="alert alert-danger small py-2 mb-3">{{ error }}</div>{% endif %}
      <form method="post">
        <div class="mb-3">
          <label class="form-label fw-bold small text-muted">Usuario</label>
          <input type="text" name="username" class="form-control rounded-3" autofocus required>
        </div>
        <div class="mb-4">
          <label class="form-label fw-bold small text-muted">Contraseña</label>
          <div class="input-group">
            <input type="password" id="password" name="password" class="form-control rounded-start-3" required>
            <button type="button" class="btn toggle-pwd rounded-end-3" onclick="togglePwd()" tabindex="-1" aria-label="Mostrar contraseña">
              <svg id="eye-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8zM1.173 8a13.133 13.133 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.133 13.133 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5c-2.12 0-3.879-1.168-5.168-2.457A13.134 13.134 0 0 1 1.172 8z"/>
                <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z"/>
              </svg>
            </button>
          </div>
        </div>
        <button type="submit" class="btn btn-primary w-100 fw-bold rounded-pill">Entrar</button>
      </form>
    </div>
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

_ALLOWED_PATHS = ('/login', '/logout', '/_dash-component-suites/', '/assets/')


@server.before_request
def require_login():
    if MODO_DESARROLLO:
        return
    if any(flask.request.path.startswith(p) for p in _ALLOWED_PATHS):
        return
    if not flask.session.get('user'):
        return flask.redirect('/login')


@server.route('/login', methods=['GET', 'POST'])
def login():
    if flask.request.method == 'POST':
        username = flask.request.form.get('username', '').strip()
        password = flask.request.form.get('password', '')

        authenticated = False
        role = 'user'

        # Primary: DuckDB dim_usuarios
        try:
            from src.db.store import get_conn
            conn = get_conn()
            row = conn.execute(
                "SELECT password_hash, role FROM dim_usuarios WHERE user_id = ?",
                [username],
            ).fetchone()
            if row and check_password_hash(row[0], password):
                authenticated = True
                role = row[1] or 'user'
                conn.execute(
                    "UPDATE dim_usuarios SET last_login = current_timestamp WHERE user_id = ?",
                    [username],
                )
        except Exception:
            pass

        # Fallback: users.json (transitional, while DB is being populated)
        if not authenticated:
            users = _load_users()
            entry = _get_entry(users, username)
            if entry and check_password_hash(entry['password'], password):
                authenticated = True
                role = entry.get('role', 'user')

        if authenticated:
            flask.session['user'] = username
            flask.session['role'] = role
            return flask.redirect('/')
        return flask.render_template_string(_LOGIN_HTML, error='Usuario o contraseña incorrectos')
    return flask.render_template_string(_LOGIN_HTML, error=None)


@server.route('/logout')
def logout():
    flask.session.pop('user', None)
    flask.session.pop('role', None)
    return flask.redirect('/login')
