"""
Модуль для анализа качества текста и защиты от спама
"""
import re
import math
from collections import Counter
from typing import Tuple, List, Dict

# Константы для проверок
MIN_ENTROPY = 2.5  # Минимальная энтропия для текстов > 50 символов
MIN_UNIQUE_WORD_RATIO = 0.3  # Минимум уникальных слов (30%)
MAX_WORD_REPETITION = 0.15  # Максимум повторений одного слова (15%)
MIN_SENTENCES = 2  # Минимум предложений для текстов > 50 символов
MIN_LETTER_RATIO = 0.6  # Минимум букв в тексте (60%)
MIN_QUALITY_SCORE = 40.0  # Минимальный общий балл качества

# Паттерны набора на клавиатуре
KEYBOARD_PATTERNS = [
    'qwerty', 'qwertyuiop', 'asdf', 'asdfgh', 'zxcv', 'zxcvbn',
    'йцукен', 'фыва', 'ячсми', 'йцуке', 'фывап'
]


def calculate_text_entropy(text: str) -> float:
    """
    Вычислить энтропию Шеннона для текста
    H = -Σ(p(x) * log2(p(x)))
    
    Args:
        text: Текст для анализа
        
    Returns:
        Значение энтропии (обычно 0-8 для текста)
    """
    if not text or len(text) < 2:
        return 0.0
    
    # Подсчитываем частоту каждого символа
    char_counts = Counter(text.lower())
    text_length = len(text)
    
    # Вычисляем энтропию
    entropy = 0.0
    for count in char_counts.values():
        probability = count / text_length
        if probability > 0:
            entropy -= probability * math.log2(probability)
    
    return entropy


def analyze_word_diversity(text: str) -> Dict:
    """
    Анализ разнообразия слов в тексте
    
    Args:
        text: Текст для анализа
        
    Returns:
        Словарь с метриками: unique_ratio, max_repetition_ratio, word_count
    """
    # Разбиваем на слова (учитываем русские и английские буквы)
    words = re.findall(r'\b[а-яёa-z]+\b', text.lower(), re.IGNORECASE)
    
    if not words:
        return {'unique_ratio': 0.0, 'max_repetition_ratio': 1.0, 'word_count': 0}
    
    word_counts = Counter(words)
    total_words = len(words)
    unique_words = len(word_counts)
    
    unique_ratio = unique_words / total_words if total_words > 0 else 0.0
    max_repetition_ratio = max(word_counts.values()) / total_words if total_words > 0 else 0.0
    
    return {
        'unique_ratio': unique_ratio,
        'max_repetition_ratio': max_repetition_ratio,
        'word_count': total_words
    }


def validate_text_structure(text: str) -> Dict:
    """
    Валидация структуры текста
    
    Args:
        text: Текст для анализа
        
    Returns:
        Словарь с метриками: sentence_count, has_punctuation, avg_sentence_length
    """
    # Подсчитываем предложения по знакам препинания
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = len(sentences)
    
    # Проверяем наличие пунктуации
    has_punctuation = bool(re.search(r'[.!?,:;]', text))
    
    # Средняя длина предложения
    if sentence_count > 0:
        avg_sentence_length = sum(len(s) for s in sentences) / sentence_count
    else:
        avg_sentence_length = len(text)
    
    return {
        'sentence_count': sentence_count,
        'has_punctuation': has_punctuation,
        'avg_sentence_length': avg_sentence_length
    }


def analyze_character_patterns(text: str) -> Dict:
    """
    Анализ паттернов символов в тексте
    
    Args:
        text: Текст для анализа
        
    Returns:
        Словарь с метриками: letter_ratio, char_diversity, has_keyboard_pattern
    """
    if not text:
        return {'letter_ratio': 0.0, 'char_diversity': 0.0, 'has_keyboard_pattern': False}
    
    text_lower = text.lower()
    
    # Подсчитываем буквы, цифры, специальные символы
    letters = sum(1 for c in text if c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    special = len(text) - letters - digits
    
    letter_ratio = letters / len(text) if len(text) > 0 else 0.0
    
    # Разнообразие символов (энтропия символов)
    char_diversity = calculate_text_entropy(text)
    
    # Проверка на паттерны набора на клавиатуре
    has_keyboard_pattern = False
    for pattern in KEYBOARD_PATTERNS:
        if pattern in text_lower:
            has_keyboard_pattern = True
            break
    
    # Дополнительная проверка: последовательные символы на клавиатуре
    if not has_keyboard_pattern and len(text) > 5:
        # Проверяем последовательности типа "qwer", "asdf", "йцук"
        keyboard_sequences = [
            'qwerty', 'asdf', 'zxcv', 'йцук', 'фыва', 'ячс'
        ]
        for seq in keyboard_sequences:
            if seq in text_lower:
                has_keyboard_pattern = True
                break
    
    return {
        'letter_ratio': letter_ratio,
        'char_diversity': char_diversity,
        'has_keyboard_pattern': has_keyboard_pattern
    }


def detect_gibberish(text: str) -> bool:
    """
    Обнаружение бессмысленного текста
    
    Args:
        text: Текст для анализа
        
    Returns:
        True если обнаружен бессмысленный текст
    """
    if len(text) < 10:
        return False
    
    # Разбиваем на слова
    words = re.findall(r'\b[а-яёa-z]+\b', text.lower(), re.IGNORECASE)
    
    if len(words) < 3:
        # Слишком мало слов - проверяем паттерны символов
        # Если много случайных комбинаций без гласных/согласных
        consonants_ru = 'бвгджзйклмнпрстфхцчшщ'
        vowels_ru = 'аеёиоуыэюя'
        consonants_en = 'bcdfghjklmnpqrstvwxyz'
        vowels_en = 'aeiouy'
        
        text_lower = text.lower()
        has_vowels = any(v in text_lower for v in vowels_ru + vowels_en)
        has_consonants = any(c in text_lower for c in consonants_ru + consonants_en)
        
        # Если нет гласных или согласных - вероятно бессмысленный текст
        if not has_vowels or not has_consonants:
            return True
    
    # Проверяем на слишком короткие "слова" (менее 2 символов)
    # Если таких больше 50% - вероятно бессмысленный текст
    if words:
        short_words = sum(1 for w in words if len(w) < 2)
        if short_words / len(words) > 0.5:
            return True
    
    # Проверяем на повторяющиеся короткие комбинации
    if len(words) > 5:
        word_counts = Counter(words)
        # Если много очень коротких повторяющихся "слов"
        short_repeats = sum(1 for w, count in word_counts.items() 
                          if len(w) <= 2 and count > 3)
        if short_repeats > 2:
            return True
    
    # Проверка на бессмысленные фразы и сленг без структуры
    # Если текст короткий и содержит только короткие слова без пунктуации
    if len(text) < 60 and words:
        # Проверяем среднюю длину слов
        avg_word_length = sum(len(w) for w in words) / len(words)
        # Если средняя длина слов очень мала (< 3.5) и нет пунктуации - вероятно бессмысленный
        if avg_word_length < 3.5 and not re.search(r'[.!?]', text):
            # Но пропускаем, если есть хотя бы одно длинное слово (> 5 символов)
            long_words = sum(1 for w in words if len(w) > 5)
            if long_words == 0:
                return True
    
    return False


def calculate_text_quality_score(text: str) -> Tuple[float, List[str]]:
    """
    Вычислить общий балл качества текста
    
    Args:
        text: Текст для анализа
        
    Returns:
        Кортеж (score, issues): балл (0-100) и список проблем
    """
    if len(text) < 10:
        return 100.0, []  # Очень короткие тексты пропускаем
    
    issues = []
    score = 100.0
    
    # 1. Энтропия (30% веса)
    entropy = calculate_text_entropy(text)
    # Для коротких текстов используем более мягкий порог
    min_entropy_threshold = MIN_ENTROPY if len(text) > 50 else 2.0
    if len(text) > 20:
        if entropy < min_entropy_threshold:
            issues.append(f"Низкая энтропия: {entropy:.2f} (минимум: {min_entropy_threshold})")
            score -= 30
        else:
            # Нормализуем: идеальная энтропия ~4-5, даем пропорциональный балл
            # Энтропия 2.5 = 0 баллов, энтропия 5.0+ = 30 баллов
            entropy_normalized = min(1.0, (entropy - min_entropy_threshold) / (5.0 - min_entropy_threshold))
            entropy_score = entropy_normalized * 30
            score = score - 30 + entropy_score
    
    # 2. Разнообразие слов (25% веса)
    word_stats = analyze_word_diversity(text)
    if word_stats['word_count'] > 0:
        if word_stats['unique_ratio'] < MIN_UNIQUE_WORD_RATIO:
            issues.append(f"Мало уникальных слов: {word_stats['unique_ratio']*100:.1f}% (минимум: {MIN_UNIQUE_WORD_RATIO*100}%)")
            score -= 25
        else:
            # Даем пропорциональный балл: 30% уникальности = 0, 100% = 25 баллов
            unique_score = ((word_stats['unique_ratio'] - MIN_UNIQUE_WORD_RATIO) / (1.0 - MIN_UNIQUE_WORD_RATIO)) * 25
            score = score - 25 + unique_score
        
        if word_stats['max_repetition_ratio'] > MAX_WORD_REPETITION:
            issues.append(f"Слишком много повторений одного слова: {word_stats['max_repetition_ratio']*100:.1f}% (максимум: {MAX_WORD_REPETITION*100}%)")
            score -= 15
    
    # 3. Структура текста (20% веса)
    structure = validate_text_structure(text)
    # Для коротких текстов требуем минимум 1 предложение, для длинных - 2
    min_sentences_required = 1 if len(text) <= 50 else MIN_SENTENCES
    if len(text) > 20:
        if structure['sentence_count'] < min_sentences_required:
            issues.append(f"Мало предложений: {structure['sentence_count']} (минимум: {min_sentences_required})")
            score -= 20
        else:
            # Даем пропорциональный балл: минимум предложений = 0, 5+ = 20 баллов
            sentence_score = min(20, ((structure['sentence_count'] - min_sentences_required + 1) / 5.0) * 20)
            score = score - 20 + sentence_score
    
    # Проверка пунктуации для текстов > 30 символов
    if len(text) > 30 and not structure['has_punctuation']:
        issues.append("Отсутствует пунктуация")
        # Для коротких текстов без пунктуации штраф больше
        if len(text) < 60:
            score -= 20  # Больший штраф для коротких текстов
        else:
            score -= 10
    
    # 4. Паттерны символов (15% веса)
    patterns = analyze_character_patterns(text)
    if patterns['letter_ratio'] < MIN_LETTER_RATIO:
        issues.append(f"Мало букв в тексте: {patterns['letter_ratio']*100:.1f}% (минимум: {MIN_LETTER_RATIO*100}%)")
        score -= 15
    else:
        # Даем пропорциональный балл: 60% букв = 0, 100% = 15 баллов
        letter_score = ((patterns['letter_ratio'] - MIN_LETTER_RATIO) / (1.0 - MIN_LETTER_RATIO)) * 15
        score = score - 15 + letter_score
    
    if patterns['has_keyboard_pattern']:
        issues.append("Обнаружены паттерны набора на клавиатуре")
        score -= 10
    
    # 5. Бессмысленный текст (10% веса)
    if detect_gibberish(text):
        issues.append("Обнаружены бессмысленные комбинации символов")
        score -= 10
    
    # Ограничиваем балл в пределах 0-100
    score = max(0.0, min(100.0, score))
    
    return score, issues


def check_links_and_mentions(text: str) -> Tuple[bool, str]:
    """
    Проверка на запрещенные ссылки и упоминания
    
    Args:
        text: Текст для проверки
        
    Returns:
        Кортеж (is_valid, error_message)
    """
    # Разрешенные домены
    allowed_domains = ['telegra.ph', 'teletype.in']
    
    # Сначала находим все разрешенные ссылки, чтобы исключить их из проверки упоминаний
    allowed_link_patterns = [
        r'https?://(?:www\.)?(?:telegra\.ph|teletype\.in)/[^\s<>"\'()]+',
        r'www\.(?:telegra\.ph|teletype\.in)/[^\s<>"\'()]+',
    ]
    
    allowed_link_ranges = []
    for pattern in allowed_link_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            allowed_link_ranges.append((match.start(), match.end()))
    
    # Проверка на упоминания (@username)
    # Ищем @username, но исключаем те, что являются частью email адресов или разрешенных ссылок
    mention_pattern = r'(?<!@)(?<![a-zA-Z0-9])@\w+'
    mentions = re.findall(mention_pattern, text)
    if mentions:
        # Фильтруем упоминания - проверяем, что это не часть email или разрешенной ссылки
        valid_mentions = []
        for mention in mentions:
            mention_pos = text.find(mention)
            if mention_pos < 0:
                continue
            
            # Проверяем, не является ли это частью разрешенной ссылки
            is_in_allowed_link = False
            for start, end in allowed_link_ranges:
                if start <= mention_pos < end:
                    is_in_allowed_link = True
                    break
            
            if is_in_allowed_link:
                continue
            
            # Проверяем контекст - если после @ идет что-то, что выглядит как домен, это email
            # Проверяем, что после упоминания нет точки с доменом (это было бы email)
            after_mention = text[mention_pos + len(mention):mention_pos + len(mention) + 20]
            # Если после @username идет точка и домен, это email, пропускаем
            if re.match(r'\.\w+', after_mention):
                continue
            # Если перед @ есть буквы/цифры, это часть email, пропускаем
            if mention_pos > 0 and text[mention_pos - 1].isalnum():
                continue
            valid_mentions.append(mention)
        
        if valid_mentions:
            mentions_display = ', '.join(valid_mentions[:3])
            if len(valid_mentions) > 3:
                mentions_display += f' и еще {len(valid_mentions) - 3}'
            return False, f"Обнаружены упоминания пользователей: {mentions_display}. Упоминания запрещены в правилах чата."
    
    # Проверка на ссылки
    found_urls = []
    
    # 1. Проверяем явные ссылки с протоколом (http://, https://)
    http_urls = re.findall(r'https?://[^\s<>"\'()]+', text, re.IGNORECASE)
    for url in http_urls:
        url_lower = url.lower()
        is_allowed = any(allowed in url_lower for allowed in allowed_domains)
        if not is_allowed:
            # Убираем возможные знаки препинания в конце
            clean_url = url.rstrip('.,;:!?)')
            if clean_url not in found_urls:
                found_urls.append(clean_url)
    
    # 2. Проверяем ссылки с www.
    www_urls = re.findall(r'www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s<>"\'()]*', text, re.IGNORECASE)
    for url in www_urls:
        url_lower = url.lower()
        is_allowed = any(allowed in url_lower for allowed in allowed_domains)
        if not is_allowed:
            clean_url = url.rstrip('.,;:!?)')
            if clean_url not in found_urls:
                found_urls.append(clean_url)
    
    # 3. Проверяем домены без протокола (но только если они выглядят как ссылки)
    # Ищем паттерн: слово.домен (но не в начале предложения и не как часть email)
    domain_pattern = r'(?<![@/])(?<!\w)([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.(?:[a-zA-Z]{2,}|xn--[a-zA-Z0-9]+))(?![@/])'
    domain_matches = re.finditer(domain_pattern, text, re.IGNORECASE)
    for match in domain_matches:
        domain = match.group(1)
        domain_lower = domain.lower()
        
        # Пропускаем разрешенные домены
        is_allowed = any(allowed in domain_lower for allowed in allowed_domains)
        if is_allowed:
            continue
        
        # Пропускаем короткие домены (могут быть частью обычных слов)
        if len(domain) < 8:
            continue
        
        # Проверяем контекст - если перед доменом нет пробела или это часть email, пропускаем
        start_pos = match.start()
        if start_pos > 0:
            char_before = text[start_pos - 1]
            # Если перед доменом @ или /, это часть email или уже обработанной ссылки
            if char_before in ['@', '/']:
                continue
        
        # Проверяем, что после домена есть пробел или конец строки (не часть слова)
        end_pos = match.end()
        if end_pos < len(text):
            char_after = text[end_pos]
            # Если после домена буква или цифра, это часть слова, пропускаем
            if char_after.isalnum():
                continue
        
        clean_domain = domain.rstrip('.,;:!?)')
        if clean_domain not in found_urls:
            found_urls.append(clean_domain)
    
    if found_urls:
        # Показываем первые 3 ссылки
        urls_display = ', '.join(found_urls[:3])
        if len(found_urls) > 3:
            urls_display += f' и еще {len(found_urls) - 3}'
        return False, f"Обнаружены запрещенные ссылки: {urls_display}. Разрешены только ссылки на telegra.ph и teletype.in"
    
    return True, ""


def is_text_meaningful(text: str, min_score: float = MIN_QUALITY_SCORE) -> Tuple[bool, str]:
    """
    Основная функция валидации текста
    
    Args:
        text: Текст для проверки
        min_score: Минимальный балл качества (по умолчанию MIN_QUALITY_SCORE)
        
    Returns:
        Кортеж (is_valid, error_message)
    """
    # Проверка на ссылки и упоминания (приоритетная проверка)
    links_valid, links_error = check_links_and_mentions(text)
    if not links_valid:
        return False, links_error
    
    # Проверяем количество слов даже для коротких текстов
    word_stats = analyze_word_diversity(text)
    
    # Очень короткие тексты (меньше 20 символов) проверяем только на количество слов
    if len(text) < 20:
        # Если только одно слово - это недостаточно для правил
        if word_stats['word_count'] <= 1:
            return False, "Правила чата должны содержать минимум 2 слова."
        # Если 2+ слова, пропускаем короткие тексты (могут быть краткие правила)
        return True, ""
    
    # Для коротких текстов (20-60 символов) используем более строгий минимум
    if 20 <= len(text) < 60:
        min_score = max(min_score, 50.0)  # Минимум 50 для коротких текстов
    
    # Вычисляем балл качества
    score, issues = calculate_text_quality_score(text)
    
    if score < min_score:
        # Формируем сообщение об ошибке
        if issues:
            error_msg = f"Общая оценка качества текста: {score:.1f}/100 (минимум: {min_score})\n\n"
            error_msg += "Обнаруженные проблемы:\n"
            for i, issue in enumerate(issues[:5], 1):  # Показываем максимум 5 проблем
                error_msg += f"{i}. {issue}\n"
            if len(issues) > 5:
                error_msg += f"... и еще {len(issues) - 5} проблем"
        else:
            error_msg = f"Общая оценка качества текста: {score:.1f}/100 (минимум: {min_score})"
        
        return False, error_msg
    
    return True, ""

