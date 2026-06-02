from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "examples" / "example_input.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "POs"
    sheet.append(["PO", "Printer"])
    sheet.append(["5946692", "HK"])
    sheet.append(["5946693", "IN"])
    sheet.append(["5946694", "VN"])
    sheet.append(["5946695", " hk "])
    sheet.append(["5946692", "HK"])
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 14
    workbook.save(output)
    print(output)


if __name__ == "__main__":
    main()
