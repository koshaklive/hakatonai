import json
from pathlib import Path
from collections import Counter

DATA_DIR = Path("data")

def run_validation():
    print("=== ОТЧЕТ РАСШИРЕННОЙ ВАЛИДАЦИИ RAG ===")
    
    chunks_file = DATA_DIR / "instruction_chunks.json"
    if not chunks_file.exists():
        print("Файл instruction_chunks.json не найден.")
        return

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks = json.load(f)
        
    id_map = {c["id"]: c for c in chunks}
    
    # 1. Проверка parent_id / children
    parent_errors = []
    for c in chunks:
        pid = c["parent_id"]
        if pid and pid not in id_map:
            parent_errors.append(f"Чанк {c['id']} ссылается на несуществующего родителя {pid}")
        for child in c["children"]:
            if child not in id_map:
                parent_errors.append(f"Чанк {c['id']} ссылается на несуществующего ребенка {child}")
            elif id_map[child]["parent_id"] != c["id"]:
                parent_errors.append(f"Нарушение связи: {c['id']} -> {child}, но у ребенка родитель {id_map[child]['parent_id']}")

    print(f"[+] Взаимная согласованность parent/children: {'ОШИБКИ' if parent_errors else 'OK'}")
    for err in parent_errors[:5]: print(f"    - {err}")
    
    # 2. Проверка JSON-схем и маркеров модулей
    modules_dir = DATA_DIR / "modules"
    module_files = list(modules_dir.glob("*.json"))
    marker_errors = []
    for mf in module_files:
        if mf.name.startswith("_"): continue
        with open(mf, "r", encoding="utf-8") as fm:
            mod = json.load(fm)
            fields_count = len(mod.get("fields", [])) + len(mod.get("optional_blocks", [])) + len(mod.get("variants", []))
            # Эмуляция сверки с DOCX
            marker_errors.append(f"{mf.name}: полей в JSON ({fields_count}) [Для DOCX сверки нужен python-docx]")

    print(f"[+] Валидация модулей и маркеров:")
    for err in marker_errors: print(f"    - {err}")

    # 3. Статистика по всем файлам
    print("\n=== ПОЛНАЯ СТАТИСТИКА ===")
    print(f"Всего чанков: {len(chunks)}")
    print(f"Наличие глоссария: {(DATA_DIR / 'glossary.json').exists()}")
    print(f"Наличие матрицы: {(DATA_DIR / 'visa_matrix.json').exists()}")
    print(f"Наличие anomalies.md: {(Path(__file__).parent / 'anomalies.md').exists()}")
    
if __name__ == "__main__":
    run_validation()