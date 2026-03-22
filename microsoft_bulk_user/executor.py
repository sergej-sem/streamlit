from typing import Any, Callable, Iterable, Mapping


def _base_log_row(row: Mapping[str, Any]) -> dict:
    return {
        "Zeile": row.get("row"),
        "Name": row.get("displayName", ""),
        "Login (UPN)": row.get("plannedUPN", ""),
    }


def execute_plan_row(
    row: Mapping[str, Any],
    *,
    dry_run: bool,
    enable_live_user_creation: bool,
    password: str,
    selected_license_labels: Iterable[str],
    selected_sku_ids: list[str],
    build_payload: Callable[..., dict],
    create_user: Callable[[dict], Mapping[str, Any]],
    assign_user_licenses: Callable[[str, list[str]], None],
) -> dict:
    status = row.get("status", "")
    upn = row.get("plannedUPN", "")
    display = row.get("displayName", "")
    first = row.get("firstName", "")
    last = row.get("lastName", "")
    log_row = _base_log_row(row)

    if status != "BEREIT":
        log_row.update(
            {
                "Ergebnis": status,
                "Hinweis": row.get("details", ""),
            }
        )
        return {
            "outcome": "planner_passthrough",
            "user_created": False,
            "license_assignment_failed": False,
            "log_row": log_row,
        }

    if dry_run:
        label_list = list(selected_license_labels)
        hint = "Nicht angelegt (Testlauf)"
        if label_list:
            hint += f" · Würde Lizenzen zuweisen: {', '.join(label_list)}"
        log_row.update(
            {
                "Ergebnis": "TESTLAUF",
                "Hinweis": hint,
            }
        )
        return {
            "outcome": "dry_run",
            "user_created": False,
            "license_assignment_failed": False,
            "log_row": log_row,
        }

    try:
        if not enable_live_user_creation:
            raise RuntimeError("Die Live-Benutzeranlage ist in diesem Deployment deaktiviert.")

        mail_nick = str(upn).split("@")[0]
        payload = build_payload(
            display_name=display,
            upn=upn,
            mail_nick=mail_nick,
            given=first,
            surname=last,
            password=password,
        )
        created = create_user(payload)
        user_id = created.get("id") if hasattr(created, "get") else None

        if selected_sku_ids and user_id:
            try:
                assign_user_licenses(str(user_id), selected_sku_ids)
            except Exception as exc:
                log_row.update(
                    {
                        "Ergebnis": "TEILERFOLG",
                        "Hinweis": f"Lizenzzuweisung fehlgeschlagen: {exc}",
                    }
                )
                return {
                    "outcome": "partial_success",
                    "user_created": True,
                    "license_assignment_failed": True,
                    "log_row": log_row,
                }

            log_row.update(
                {
                    "Ergebnis": "ANGELEGT",
                    "Hinweis": "Lizenzen zugewiesen",
                }
            )
            return {
                "outcome": "success",
                "user_created": True,
                "license_assignment_failed": False,
                "log_row": log_row,
            }

        log_row.update(
            {
                "Ergebnis": "ANGELEGT",
                "Hinweis": "",
            }
        )
        return {
            "outcome": "success",
            "user_created": True,
            "license_assignment_failed": False,
            "log_row": log_row,
        }
    except Exception as exc:
        log_row.update(
            {
                "Ergebnis": "FEHLER",
                "Hinweis": str(exc),
            }
        )
        return {
            "outcome": "error",
            "user_created": False,
            "license_assignment_failed": False,
            "log_row": log_row,
        }
