from __future__ import annotations

from pydantic import BaseModel

SOURCE = "cruceros"


class Params(BaseModel):
    ajax_url: str
    pais_codigo: str = "ES"
