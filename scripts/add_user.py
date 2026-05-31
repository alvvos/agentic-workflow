#!/usr/bin/env python3
"""
Gestión de usuarios para el panel de autenticación.

Uso:
  python scripts/add_user.py <usuario> <contraseña> [--role admin|user]  # crear o actualizar
  python scripts/add_user.py --list                                        # listar usuarios
  python scripts/add_user.py --delete <usuario>                           # eliminar usuario
  python scripts/add_user.py --role <usuario> admin|user                  # cambiar rol

Ejemplos:
  python scripts/add_user.py alice secreto123             # crea usuario con rol 'user'
  python scripts/add_user.py alice secreto123 --role admin
  python scripts/add_user.py --role alice admin           # cambia el rol de alice
  python scripts/add_user.py --delete bob
"""
import sys
import json
import os
from werkzeug.security import generate_password_hash

USERS_FILE = os.path.join(os.path.dirname(__file__), '..', 'users.json')

_VALID_ROLES = ("admin", "user")


def load():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)


def save(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def _normalize(entry):
    if isinstance(entry, str):
        return {"password": entry, "role": "user"}
    return entry


def add(username, password, role="user"):
    if role not in _VALID_ROLES:
        print(f"Rol no válido: '{role}'. Usa: {', '.join(_VALID_ROLES)}")
        sys.exit(1)
    users = load()
    action = 'actualizado' if username in users else 'creado'
    entry  = _normalize(users.get(username, {}))
    entry["password"] = generate_password_hash(password)
    entry["role"]     = role
    users[username]   = entry
    save(users)
    print(f"Usuario '{username}' {action} (rol: {role}).")


def delete(username):
    users = load()
    if username not in users:
        print(f"Usuario '{username}' no existe.")
        sys.exit(1)
    del users[username]
    save(users)
    print(f"Usuario '{username}' eliminado.")


def change_role(username, role):
    if role not in _VALID_ROLES:
        print(f"Rol no válido: '{role}'. Usa: {', '.join(_VALID_ROLES)}")
        sys.exit(1)
    users = load()
    if username not in users:
        print(f"Usuario '{username}' no existe.")
        sys.exit(1)
    entry = _normalize(users[username])
    entry["role"]   = role
    users[username] = entry
    save(users)
    print(f"Rol de '{username}' cambiado a '{role}'.")


def list_users():
    users = load()
    if not users:
        print("No hay usuarios registrados.")
    else:
        print(f"  {'USUARIO':<20} {'ROL'}")
        print("  " + "─" * 30)
        for u in sorted(users):
            entry = _normalize(users[u])
            role  = entry.get("role", "user")
            marker = " ★" if role == "admin" else ""
            print(f"  {u:<20} {role}{marker}")


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == '--list':
        list_users()
    elif args[0] == '--delete' and len(args) == 2:
        delete(args[1])
    elif args[0] == '--role' and len(args) == 3:
        change_role(args[1], args[2])
    elif len(args) >= 2 and not args[0].startswith('--'):
        username, password = args[0], args[1]
        role = "user"
        if len(args) >= 4 and args[2] == '--role':
            role = args[3]
        add(username, password, role)
    else:
        print(__doc__)
        sys.exit(1)
