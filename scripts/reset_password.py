#!/usr/bin/env python3
"""
Resetea la contraseña de un usuario existente.

Uso:
  python scripts/reset_password.py [<usuario>]
"""
import sys
import json
import os
import getpass
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


def main():
    users = load()
    if not users:
        print("No hay usuarios registrados. Usa add_user.py para crear uno.")
        sys.exit(1)

    username = sys.argv[1] if len(sys.argv) > 1 else input("Usuario: ").strip()

    if username not in users:
        print(f"Error: el usuario '{username}' no existe.")
        print("Usuarios disponibles:", ', '.join(sorted(users)))
        sys.exit(1)

    pwd = getpass.getpass("Nueva contraseña: ")
    if not pwd:
        print("Error: la contraseña no puede estar vacía.")
        sys.exit(1)
    pwd2 = getpass.getpass("Confirma contraseña: ")
    if pwd != pwd2:
        print("Error: las contraseñas no coinciden.")
        sys.exit(1)

    users[username] = generate_password_hash(pwd)
    save(users)
    print(f"Contraseña de '{username}' actualizada correctamente.")


if __name__ == '__main__':
    main()
