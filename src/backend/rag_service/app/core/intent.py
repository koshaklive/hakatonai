import re

_INTENT_PATTERNS = {
    "clarification": re.compile(r"\b(?:не\s+понял[аи]?|что\s+это\s+значит)\b", re.I),
    "gratitude": re.compile(r"\b(?:спасибо|благодар\w*)\b", re.I),
    "rudeness": re.compile(
        r"\b(?:идиот\w*|дурак\w*|дебил\w*|туп(?:ой|ая|ые)|заткнись|бесполезн\w*|"
        r"хамло|сука\w*|нах\w*|еб\w*|пизд\w*)\b",
        re.I,
    ),
    "emotion": re.compile(
        r"\b(?:грустно|на\s+душе\s+тяжело|плохо\s+на\s+душе|мне\s+(?:тяжело|плохо|обидно)|"
        r"расстроен\w*|разочарован\w*|устал\w*|жалуюсь|хочу\s+пожаловаться|"
        r"меня\s+достал\w*|я\s+переживаю|всё\s+плохо|все\s+плохо)\b",
        re.I,
    ),
    "out_of_domain": re.compile(r"\b(?:командиров\w*|отпуск\w*|суточн\w*)\b", re.I),
    "partial_match": re.compile(r"\bдоверенн\w*\b", re.I),
    "off_topic": re.compile(
        r"\b(?:деньг\w*|зарплат\w*|здоров\w*|болит|лечени\w*|болезн\w*|"
        r"медицинск\w*|врач\w*|лекарств\w*|температур\w*|похуд\w*)\b",
        re.I,
    ),
    "smalltalk": re.compile(
        r"\b(?:привет\w*|здравствуй\w*|доброе\s+утро|добрый\s+день|добрый\s+вечер|"
        r"как\s+(?:дела|ты|вы)|что\s+ты\s+умеешь|чем\s+ты\s+можешь\s+помочь|помощь)\b",
        re.I,
    ),
}

_REFORMULATE_WORDS = {
    "покороче", "проще", "понятнее", "объясни", "поясни", "еще", "ещё", "раз",
    "на", "примере", "сделай", "ответ", "пожалуйста", "можно", "чуть", "немного",
    "повтори", "сформулируй", "это", "снова",
}

_DOMAIN_TOPIC = re.compile(
    r"\b(?:срок\w*|визир\w*|согласовани\w*|пояснительн\w*|адресат\w*|хранени\w*|хранить)\b",
    re.I,
)


def analyze_intent(query: str) -> dict:
    q = query.strip().lower()
    words = re.findall(r"[а-яё]+", q)
    if any(phrase in q for phrase in ("сколько можно ждать", "тормозишь")):
        return {"action": "search", "intent": "frustration", "mode": "frustration"}

    for intent, pattern in _INTENT_PATTERNS.items():
        if pattern.search(q):
            if intent == "clarification":
                return {"action": "clarify", "intent": intent}
            return {"action": "reply", "intent": intent}

    if words and any(word in {"покороче", "проще", "понятнее", "объясни", "поясни", "еще", "ещё", "примере"}
                     for word in words) and set(words) <= _REFORMULATE_WORDS:
        return {"action": "reformulate", "intent": "reformulate"}

    # 1. Защита от коротких запросов (меньше 3 слов и без цифр, похожих на номер пункта)
    if len(q.split()) < 3 and not re.search(r'\d+\.\d+', q) and not _DOMAIN_TOPIC.search(q):
        if not any(w in q for w in ["привет", "здравствуй", "спасибо", "помощь"]):
            return {
                "action": "reply",
                "intent": "short_query",
                "text": "Пожалуйста, уточните ваш вопрос. Запрос слишком короткий для поиска."
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