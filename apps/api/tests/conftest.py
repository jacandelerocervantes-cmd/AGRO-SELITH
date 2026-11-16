"""Las pruebas hacen muchas llamadas seguidas: se suben los límites de uso (los de producción se prueban aparte)."""

import os

for _k, _v in {"MILPA_LIM_GLOBAL": "1000000", "MILPA_LIM_CHAT": "100000", "MILPA_LIM_CHAT_DIA": "1000000",
               "MILPA_LIM_CAPAS": "100000", "MILPA_LIM_PARCELAS": "100000"}.items():
    os.environ.setdefault(_k, _v)
