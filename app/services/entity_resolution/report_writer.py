
from pathlib import Path

import pandas as pd

from app.core.config import settings


class EntityResolutionReportWriter:
    def __init__(
        self,
        report_dir: Path | None = None,
        report_format: str | None = None,
    ) -> None:
        self.report_dir = Path(
            report_dir or settings.er_report_dir
        )
        self.report_format = (
            report_format or settings.er_report_format
        ).lower()

        if self.report_format not in {"xlsx", "txt"}:
            raise ValueError(
                "ER_REPORT_FORMAT chỉ nhận xlsx hoặc txt."
            )

    def _next_report_path(self, document_id: str) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)

        extension = self.report_format
        number = 1

        while True:
            path = self.report_dir / (
                f"report_{document_id}_{number}.{extension}"
            )

            if not path.exists():
                return path

            number += 1

    @staticmethod
    def _summary(dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            counts = {
                "AUTO_MERGE_CANDIDATE": 0,
                "REVIEW": 0,
                "REJECT": 0,
            }
        else:
            counts = (
                dataframe["decision"]
                .value_counts()
                .to_dict()
            )

        return pd.DataFrame([
            {"decision": key, "count": counts.get(key, 0)}
            for key in (
                "AUTO_MERGE_CANDIDATE",
                "REVIEW",
                "REJECT",
            )
        ])

    def write(
        self,
        document_id: str,
        dataframe: pd.DataFrame,
    ) -> Path:
        path = self._next_report_path(document_id)
        summary = self._summary(dataframe)

        if self.report_format == "xlsx":
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                dataframe.to_excel(
                    writer,
                    sheet_name="Candidates",
                    index=False,
                )
                summary.to_excel(
                    writer,
                    sheet_name="Summary",
                    index=False,
                )
        else:
            with path.open("w", encoding="utf-8") as file:
                file.write(f"Document ID: {document_id}\n")
                file.write(f"Candidate count: {len(dataframe)}\n\n")
                file.write("=== SUMMARY ===\n")
                file.write(summary.to_string(index=False))
                file.write("\n\n=== CANDIDATES ===\n")
                file.write(dataframe.to_string(index=False))
                file.write("\n")

        return path
