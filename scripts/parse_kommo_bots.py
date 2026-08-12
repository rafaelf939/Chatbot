#!/usr/bin/env python3
"""Extrae el catálogo observable de exportaciones JSON de Kommo Salesbot."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "sin-codigo"


def load_flow(path: Path) -> tuple[str, dict[str, Any]]:
    exported = json.loads(path.read_text(encoding="utf-8"))
    model = exported.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("text"), str):
        raise ValueError(f"{path}: no contiene model.text en el formato esperado")
    flow = json.loads(model["text"])
    if not isinstance(flow, dict):
        raise ValueError(f"{path}: model.text no contiene un objeto JSON")
    return str(model.get("name") or path.stem).strip(), flow


def _goto_by_callback(step: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for answer in step.get("answer", []):
        if not isinstance(answer, dict) or answer.get("handler") != "buttons":
            continue
        for choice in answer.get("params", []):
            if not isinstance(choice, dict) or "value" not in choice:
                continue
            for action in choice.get("params", []):
                params = action.get("params", {}) if isinstance(action, dict) else {}
                if action.get("handler") == "goto" and "step" in params:
                    result[str(choice["value"])] = str(params["step"])
    return result


def parse_bot(path: Path) -> dict[str, Any]:
    bot_name, flow = load_flow(path)
    bot_code = slug(bot_name)
    options: list[dict[str, Any]] = []
    used_codes: defaultdict[str, int] = defaultdict(int)
    for step_id, step in flow.items():
        if not isinstance(step, dict):
            continue
        destinations = _goto_by_callback(step)
        for question in step.get("question", []):
            params = question.get("params", {}) if isinstance(question, dict) else {}
            list_message = params.get("list_message") if isinstance(params, dict) else None
            if not isinstance(list_message, dict):
                continue
            for section in list_message.get("sections", []):
                menu = str(section.get("title") or list_message.get("header") or f"paso-{step_id}").strip()
                for row in section.get("rows", []):
                    callback = row.get("callback_data")
                    name = str(row.get("title") or "Sin nombre").strip()
                    base_code = slug(name)
                    used_codes[base_code] += 1
                    option_code = base_code if used_codes[base_code] == 1 else f"{base_code}-{used_codes[base_code]}"
                    options.append({
                        "bot_codigo": bot_code, "bot_nombre": bot_name, "menu": menu,
                        "opcion_codigo": option_code, "opcion_nombre": name,
                        "callback_data": callback,
                        "paso_destino": destinations.get(str(callback)) if callback else None,
                        "paso_origen": str(step_id), "activo": True,
                    })
    return {"bot_codigo": bot_code, "bot_nombre": bot_name, "archivo": path.name, "opciones": options}


def parse_directory(directory: Path) -> dict[str, Any]:
    bots = [parse_bot(path) for path in sorted(directory.glob("*.json"))]
    callbacks: defaultdict[str, set[str]] = defaultdict(set)
    for bot in bots:
        for option in bot["opciones"]:
            if option["callback_data"]:
                callbacks[option["callback_data"]].add(bot["bot_codigo"])
    duplicates = [
        {"callback_data": callback, "bots": sorted(bot_codes)}
        for callback, bot_codes in sorted(callbacks.items()) if len(bot_codes) > 1
    ]
    return {"bots": bots, "callback_data_duplicados_entre_bots": duplicates}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=Path("docs/bots"))
    parser.add_argument("--output", "-o", type=Path)
    args = parser.parse_args()
    result = parse_directory(args.directory)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

