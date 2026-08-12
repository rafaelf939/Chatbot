from urllib.parse import parse_qs


SAFE_KOMMO_FORM_FIELDS = (
    "leads[add][0][id]",
    "leads[add][0][status_id]",
    "leads[add][0][pipeline_id]",
    "account[id]",
    "account[subdomain]",
)


def parse_kommo_form_payload(body: bytes) -> dict[str, str | list[str]]:
    parsed = parse_qs(
        body.decode("utf-8", errors="replace"),
        keep_blank_values=True,
        max_num_fields=1000,
    )
    safe_payload: dict[str, str | list[str]] = {}
    for key in SAFE_KOMMO_FORM_FIELDS:
        values = parsed.get(key)
        if not values:
            continue
        safe_payload[key] = values[0] if len(values) == 1 else values
    return safe_payload
