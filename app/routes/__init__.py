"""Shared route-layer helpers.

Kept minimal and HTTP-only (Response construction) — the actual export
data/authorization logic lives in app.services.exports/pdf_reports, per
this project's "business logic outside HTTP handlers" convention. Used
by every route module that offers a CSV/PDF export (attendance,
dashboard, leave, labor_cost) so the response headers stay identical
everywhere rather than four slightly different copies.
"""

from flask import Response


def csv_response(filename: str, csv_text: str) -> Response:
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def pdf_response(filename: str, pdf_bytes: bytes) -> Response:
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
