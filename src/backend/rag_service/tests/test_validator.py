from __future__ import annotations

from io import BytesIO

from docx import Document

from app.core.validator import check_draft_file, validate_kb_file


def _docx_bytes(document: Document) -> bytes:
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_validate_clean_kb_docx_returns_no_findings():
    document = Document()
    document.add_paragraph("Срок рассмотрения распоряжения составляет 3 рабочих дня.")
    document.add_paragraph("Ссылка на пункт п. 10.3.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Заполнено"
    table.cell(0, 1).text = "Все данные указаны"

    result = validate_kb_file(_docx_bytes(document), "methodics.docx")

    assert result == []


def test_note_markers_without_a_notes_section_do_not_create_findings():
    document = Document()
    document.add_paragraph("Пункт [1] относится к приложению.")

    assert validate_kb_file(_docx_bytes(document), "clean.docx") == []


def test_validate_kb_reports_exact_three_requested_critical_issues():
    document = Document()
    document.add_paragraph("Шаблон " + " ".join(f"[{number}]" for number in range(1, 13)))
    document.add_paragraph("Примечания по заполнению")
    for number in [*range(1, 11), 12]:
        document.add_paragraph(f"{number}. Текст примечания {number}")
    document.add_paragraph("Общие правила заполнения")
    document.add_paragraph("Ссылка на несуществующий пункт п. 10.16.")
    document.add_paragraph("Срок рассмотрения распоряжения составляет 5 рабочих дней.")

    result = validate_kb_file(_docx_bytes(document), "С_ОШИБКАМИ.docx")

    assert [finding["problem"] for finding in result] == [
        "Пропуск примечания 11",
        "Ссылка на несуществующий пункт Инструкции",
        "Срок 5 рабочих дней вместо 3",
    ]
    assert result[1]["quote"] == "п. 10.16"
    assert result[1]["ref_point"] == "Инструкция"
    assert result[2]["ref_point"] == "п. 10.3"
    assert all(set(finding) == {"severity", "location", "quote", "problem", "ref_point"} for finding in result)
    assert all(len(finding["quote"].split()) <= 15 for finding in result)


def test_validate_kb_reports_glued_words_and_empty_table_cells():
    document = Document()
    document.add_paragraph("ОшибкасловоСклеено")
    document.add_table(rows=1, cols=2).cell(0, 0).text = "Заполнено"

    result = validate_kb_file(_docx_bytes(document), "broken.docx")

    assert any(finding["severity"] == "warning" and finding["problem"] == "Возможная склейка слов"
               for finding in result)
    assert any(finding["severity"] == "error" and finding["problem"] == "Пустая ячейка в таблице"
               for finding in result)
    assert all(len(finding["quote"].split()) <= 15 for finding in result)


def test_check_draft_reports_placeholders_and_manual_semantic_check():
    document = Document()
    document.add_paragraph("Черновик ___ [12] УТВЕРЖДАЮ МОДУЛЬНЫЙ ДОКУМЕНТ A/B")

    findings = check_draft_file(_docx_bytes(document))
    problems = [finding["problem"] for finding in findings]

    assert any("незаполненная линия" in problem for problem in problems)
    assert any("маркер примечания" in problem for problem in problems)
    assert any("служебный шаблонный текст" in problem for problem in problems)
    assert any("слэш" in problem for problem in problems)
    assert any("предупреждение" in problem for problem in problems)
    assert any("пояснительная записка" in problem for problem in problems)
