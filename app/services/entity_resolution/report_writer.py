from pathlib import Path
import os
import tempfile

import pandas as pd

from app.core.config import settings


class EntityResolutionReportWriter:
    def __init__(
        self,
        report_dir: Path | None = None,
        report_format: str | None = None,
    ) -> None:
        self.report_dir = Path(report_dir or settings.er_report_dir)
        self.report_format = (report_format or settings.er_report_format).lower()
        if self.report_format != "xlsx":
            raise ValueError("Báo cáo kết quả finalize hiện chỉ hỗ trợ xlsx.")

    def _next_report_path(self, document_id: str) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            path = self.report_dir / f"report_{document_id}_{number}.xlsx"
            if not path.exists():
                return path
            number += 1

    @staticmethod
    def _frame(rows) -> pd.DataFrame:
        return pd.DataFrame.from_records(rows) if rows else pd.DataFrame()

    def write(self, document_id: str, dataframe: pd.DataFrame) -> Path:
        """Write a preview workbook. Kept for compatibility with preview()."""
        path = self._next_report_path(document_id)
        summary = (
            dataframe["classification"].value_counts().rename_axis("classification").reset_index(name="count")
            if not dataframe.empty else pd.DataFrame(columns=["classification", "count"])
        )
        self._atomic_excel(path, {
            "Candidates": dataframe,
            "Summary": summary,
        })
        return path

    def write_final(
        self,
        document_id: str,
        run_id: str,
        candidates: list[dict],
        canonical_entities: list[dict],
        canonical_relations: list[dict],
        summary: dict,
    ) -> Path:
        path = self._next_report_path(document_id)
        self._atomic_excel(path, {
            "Summary": self._frame([{"document_id": document_id, "run_id": run_id, **summary}]),
            "Candidates": self._frame(candidates),
            "Canonical_Entities": self._frame(canonical_entities),
            "Canonical_Relations": self._frame(canonical_relations),
        })
        return path

    @staticmethod
    def _atomic_excel(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}_", suffix=".tmp.xlsx", dir=path.parent
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
                for sheet_name, dataframe in sheets.items():
                    dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
