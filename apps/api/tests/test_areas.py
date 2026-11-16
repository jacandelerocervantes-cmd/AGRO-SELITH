import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from milpa_api.areas import AREAS, clasificar_area, detectar_escenario, nombre_cultivo, pide_plan  # noqa: E402


def test_clasifica_preguntas_en_espanol_e_ingles() -> None:
    casos = {
        "¿Cómo mejoro un suelo pedregoso?": "suelos", "How can I improve my soil organic matter?": "suelos",
        "Mi frijol tiene una plaga de gusano": "patogenos", "My beans have a fungus disease": "patogenos",
        "¿Qué hago si la canícula dura mucho?": "agua", "How much irrigation in a drought?": "agua",
        "¿Viene un huracán?": "clima", "Will there be frost or heat next week?": "clima",
        "¿A qué precio puedo vender la calabaza?": "mercado", "Is there a market to sell pumpkin?": "mercado",
        "¿Qué variedad de maíz uso?": "cultivos",
    }
    for texto, area in casos.items():
        assert clasificar_area(texto) == area, texto
        assert area in AREAS


def test_ignora_acentos_y_mayusculas() -> None:
    assert clasificar_area("SEQUÍA Y AGUA") == clasificar_area("sequia y agua") == "agua"


def test_detecta_escenario_y_si_pide_plan() -> None:
    assert detectar_escenario("¿Y si hay canícula larga?") == "canicula_prolongada"
    assert detectar_escenario("what if a hurricane hits") == "huracan"
    assert detectar_escenario("la lluvia llega tarde") == "temporal_tardio"
    assert detectar_escenario("hola") == "normal"
    assert pide_plan("¿Qué siembro este año?") and pide_plan("What should I plant?")
    assert not pide_plan("¿Cuántos días tiene un mes?")


def test_nombres_de_cultivo_en_los_dos_idiomas() -> None:
    assert nombre_cultivo("frijol_xpelon", "es") == "Frijol xpelón" and nombre_cultivo("frijol_xpelon", "en") == "Xpelón bean"
    assert nombre_cultivo("desconocido", "en") == "desconocido"
