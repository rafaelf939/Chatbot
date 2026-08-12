from pathlib import Path

from scripts.parse_kommo_bots import parse_directory


BOT_DIR = Path(__file__).parents[1] / "docs" / "bots"


def test_parses_all_real_exports():
    result = parse_directory(BOT_DIR)
    assert len(result["bots"]) == 3
    assert sum(len(bot["opciones"]) for bot in result["bots"]) == 25
    assert all(option["callback_data"] for bot in result["bots"] for option in bot["opciones"])
    assert all(option["paso_destino"] for bot in result["bots"] for option in bot["opciones"])


def test_detects_callback_duplicates_between_bots():
    result = parse_directory(BOT_DIR)
    duplicates = result["callback_data_duplicados_entre_bots"]
    assert len(duplicates) == 3
    assert all(len(item["bots"]) == 2 for item in duplicates)
