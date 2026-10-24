import re

_REFORMULATE_WORDS = {
    "покороче", "проще", "понятнее", "объясни", "поясни", "еще", "ещё", "раз",
    "на", "примере", "сделай", "ответ", "пожалуйста", "можно", "чуть", "немного",
    "повтори", "сформулируй", "это", "снова",
}


def analyze_intent(query: str) -> dict:
    q = query.strip().lower()
    words = re.findall(r"[а-яё]+", q)
    if any(phrase in q for phrase in ("сколько можно ждать", "тормозишь")):
        return {"action": "search", "intent": "frustration", "mode": "frustration"}
    if words and any(word in {"покороче", "проще", "понятнее", "объясни", "поясни", "еще", "ещё", "примере"}
                     for word in words) and set(words) <= _REFORMULATE_WORDS:
        return {"action": "reformulate", "intent": "reformulate"}

    # 1. Защита от коротких запросов (меньше 3 слов и без цифр, похожих на номер пункта)
    if len(q.split()) < 3 and not re.search(r'\d+\.\d+', q):
        if not any(w in q for w in ["привет", "здравствуй", "спасибо", "помощь"]):
            return {
                "action": "reply",
                "intent": "short_query",
                "text": "Пожалуйста, уточните ваш вопрос. Запрос слишком короткий для поиска."
            }

    # 2. Smalltalk (приветствия, благодарности, помощь)
    if any(w in q for w in ["привет", "здравствуй", "спасибо", "благодар", "что ты умеешь", "помощь"]):
        return {
            "action": "reply",
            "intent": "smalltalk",
            "text": "Здравствуйте! Я ИИ-ассистент по нормативным документам ДОУ.\nПримеры вопросов:\n- Какой срок рассмотрения приказа?\n- Кто визирует распоряжение о рабочей группе?\n- Заполни приказ о вводе ИС."
        }

    # 3. Поиск по главе/пункту без конкретики ("глава 10", "пункт 5")
    match = re.search(r'(?:глав[ауеы]|пункт[ауе]?)\s+(\d+)(?!\.\d+)', q)
    if match:
        num = match.group(1)
        return {
            "action": "reply",
            "intent": "chapter",
            "text": f"Уточните, какой именно пункт главы {num} вас интересует? (Например: {num}.1, {num}.2)"
        }

    # 4. Определение режима ответа (если запрос прошел все фильтры)
    mode = "default"
    if re.search(r'(объясни|расскажи простыми словами|что значит)', q):
        mode = "explain"
    elif re.search(r'(перескажи|кратко|конспект)', q):
        mode = "summarize"
    elif re.search(r'(что (мне )?сделать|как согласовать|с чего начать|шаги)', q):
        mode = "checklist"
    elif re.search(r'(разница|отличи[ея]|чем .* отличается)', q):
        mode = "compare"

    # Если всё ок, даем бэкенду сигнал искать по базе, передавая нужный режим
    return {
        "action": "search",
        "mode": mode
    }