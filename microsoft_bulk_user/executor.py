from typing import Any, Callable, Iterable, Mapping


def _base_log_row(row: Mapping[str, Any]) -> dict:
    return {
        "Zeile": row.get("row"),
        "Name": row.get("displayName", ""),
        "Login (UPN)": row.get("plannedUPN", ""),
    }


def _set_log_result(log_row: dict, result: str, hint: str) -> None:
    log_row.update(
        {
            "Ergebnis": result,
            "Hinweis": hint,
        }
    )


def _build_execution_result(
    *,
    outcome: str,
    user_created: bool,
    license_assignment_failed: bool,
    log_row: dict,
) -> dict:
    return {
        "outcome": outcome,
        "user_created": user_created,
        "license_assignment_failed": license_assignment_failed,
        "log_row": log_row,
    }


def _finalize_execution_result(
    log_row: dict,
    *,
    result: str,
    hint: str,
    outcome: str,
    user_created: bool,
    license_assignment_failed: bool,
) -> dict:
    _set_log_result(log_row, result, hint)
    return _build_execution_result(
        outcome=outcome,
        user_created=user_created,
        license_assignment_failed=license_assignment_failed,
        log_row=log_row,
    )


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
    delete_user: Callable[[str], None],
) -> dict:
    status = row.get("status", "")
    upn = row.get("plannedUPN", "")
    display = row.get("displayName", "")
    first = row.get("firstName", "")
    last = row.get("lastName", "")
    log_row = _base_log_row(row)

    if status != "BEREIT":
        return _finalize_execution_result(
            log_row,
            result=status,
            hint=row.get("details", ""),
            outcome="planner_passthrough",
            user_created=False,
            license_assignment_failed=False,
        )

    if dry_run:
        label_list = list(selected_license_labels)
        hint = "Nicht angelegt (Testlauf)"
        if label_list:
            hint += f" · Würde Lizenzen zuweisen: {', '.join(label_list)}"
        return _finalize_execution_result(
            log_row,
            result="TESTLAUF",
            hint=hint,
            outcome="dry_run",
            user_created=False,
            license_assignment_failed=False,
        )

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

        if selected_sku_ids:
            rollback_identifier = str(user_id or upn)
            if not rollback_identifier:
                raise RuntimeError("Benutzer wurde angelegt, kann aber ohne ID/UPN nicht zurückgerollt werden.")

            if not user_id:
                try:
                    delete_user(rollback_identifier)
                except Exception as rollback_exc:
                    return _finalize_execution_result(
                        log_row,
                        result="FEHLER",
                        hint=(
                            "Benutzer angelegt, aber Graph lieferte keine ID für die Lizenzzuweisung; "
                            f"Rollback fehlgeschlagen: {rollback_exc}"
                        ),
                        outcome="error_rollback_failed",
                        user_created=True,
                        license_assignment_failed=True,
                    )

                return _finalize_execution_result(
                    log_row,
                    result="FEHLER",
                    hint="Benutzer angelegt, aber Graph lieferte keine ID; Benutzer wurde zurückgerollt",
                    outcome="error",
                    user_created=False,
                    license_assignment_failed=True,
                )

            try:
                assign_user_licenses(str(user_id), selected_sku_ids)
            except Exception as exc:
                try:
                    delete_user(rollback_identifier)
                except Exception as rollback_exc:
                    return _finalize_execution_result(
                        log_row,
                        result="FEHLER",
                        hint=(
                            f"Lizenzzuweisung fehlgeschlagen: {exc}. "
                            f"Rollback fehlgeschlagen: {rollback_exc}"
                        ),
                        outcome="error_rollback_failed",
                        user_created=True,
                        license_assignment_failed=True,
                    )

                return _finalize_execution_result(
                    log_row,
                    result="FEHLER",
                    hint=f"Lizenzzuweisung fehlgeschlagen: {exc}. Benutzer wurde zurückgerollt",
                    outcome="error",
                    user_created=False,
                    license_assignment_failed=True,
                )

            return _finalize_execution_result(
                log_row,
                result="ANGELEGT",
                hint="Lizenzen zugewiesen",
                outcome="success",
                user_created=True,
                license_assignment_failed=False,
            )

        return _finalize_execution_result(
            log_row,
            result="ANGELEGT",
            hint="",
            outcome="success",
            user_created=True,
            license_assignment_failed=False,
        )
    except Exception as exc:
        return _finalize_execution_result(
            log_row,
            result="FEHLER",
            hint=str(exc),
            outcome="error",
            user_created=False,
            license_assignment_failed=False,
        )
