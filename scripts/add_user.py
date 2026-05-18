#!/usr/bin/env python3
"""
Gestión de usuarios para el panel de autenticación.

Uso:
  python scripts/add_user.py <usuario> <contraseña>   # crear o actualizar
  python scripts/add_user.py --list                   # listar usuarios
  python scripts/add_user.py --delete <usuario>       # eliminar usuario
"""
import sys
import json
import os
from werkzeug.security import generate_password_hash

USERS_FILE = os.path.join(os.path.dirname(__file__), '..', 'users.json')


def load():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)


def save(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def add(username, password):
    users = load()
    action = 'actualizado' if username in users else 'creado'
    users[username] = generate_password_hash(password)
    save(users)
    print(f"Usuario '{username}' {action}.")


def delete(username):
    users = load()
    if username not in users:
        print(f"Usuario '{username}' no existe.")
        sys.exit(1)
    del users[username]
    save(users)
    print(f"Usuario '{username}' eliminado.")


def list_users():
    users = load()
    if not users:
        print("No hay usuarios registrados.")
    else:
        for u in sorted(users):
            print(f"  - {u}")


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    if args[0] == '--list':
        list_users()
    elif args[0] == '--delete' and len(args) == 2:
        delete(args[1])
    elif len(args) == 2:
        add(args[0], args[1])
    else:
        print(__doc__)
        sys.exit(1)
