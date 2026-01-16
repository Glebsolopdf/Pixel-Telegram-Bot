"""
Модуль для генерации изображений профилей пользователей
"""
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, List, Dict, Any
from PIL import Image, ImageDraw, ImageFont
import colorsys
import os
import platform
import logging

logger = logging.getLogger(__name__)


def _load_cyrillic_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Загружает шрифт с поддержкой кириллицы, доступный на Windows и Linux
    
    Args:
        size: Размер шрифта
        
    Returns:
        ImageFont.FreeTypeFont: Загруженный шрифт
        
    Raises:
        OSError: Если не удалось найти ни один подходящий шрифт
    """
    # Список шрифтов для проверки (в порядке приоритета)
    font_names = [
        "DejaVuSans",
        "DejaVu Sans",
        "LiberationSans-Regular",
        "Liberation Sans",
        "arial",
        "Arial",
        "Tahoma",
        "tahoma",
    ]
    
    # Расширения файлов шрифтов
    font_extensions = [".ttf", ".TTF"]
    
    # Определяем платформу и пути к шрифтам
    system = platform.system()
    font_paths = []
    
    if system == "Windows":
        # Windows системные шрифты
        windows_font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
        font_paths.append(windows_font_dir)
    elif system == "Linux":
        # Linux системные шрифты
        font_paths.extend([
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/TTF",
            "/usr/share/fonts/truetype",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
        ])
    
    # Также проверяем локальный путь (Noto Sans)
    local_font_path = "data/fonts/NotoSans-Regular.ttf"
    if os.path.exists(local_font_path):
        try:
            return ImageFont.truetype(local_font_path, size)
        except Exception:
            pass
    
    # Перебираем шрифты и пути
    for font_name in font_names:
        for font_path_dir in font_paths:
            if not os.path.exists(font_path_dir):
                continue
                
            for ext in font_extensions:
                # Пробуем разные варианты имени файла
                possible_names = [
                    f"{font_name}{ext}",
                    f"{font_name.replace(' ', '')}{ext}",
                    f"{font_name.replace(' ', '-')}{ext}",
                ]
                
                for name in possible_names:
                    font_path = os.path.join(font_path_dir, name)
                    if os.path.exists(font_path):
                        try:
                            return ImageFont.truetype(font_path, size)
                        except Exception as e:
                            logger.debug(f"Не удалось загрузить шрифт {font_path}: {e}")
                            continue
        
        # Также пробуем прямой путь без расширения (для PIL, который может найти системный шрифт)
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    
    # Если ничего не найдено, пробуем найти любой доступный шрифт через fontconfig (Linux)
    if system == "Linux":
        try:
            import subprocess
            result = subprocess.run(
                ["fc-match", "DejaVu Sans:style=Regular", "-f", "%{file}"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                font_file = result.stdout.strip()
                if os.path.exists(font_file):
                    return ImageFont.truetype(font_file, size)
        except Exception:
            pass
    
    # Если ничего не сработало, генерируем ошибку
    raise OSError(
        f"Не удалось найти шрифт с поддержкой кириллицы. "
        f"Проверьте наличие DejaVu Sans, Liberation Sans, Arial или Tahoma в системе."
    )


def generate_modern_profile_card(
    user_data: Dict[str, Any],
    monthly_stats: List[Dict[str, Any]],
    avatar_path: Optional[str] = None
) -> BytesIO:
    """
    Генерация графика профиля пользователя за месяц
    
    Args:
        user_data: Данные пользователя (не используется)
        monthly_stats: Статистика за 30 дней
        avatar_path: Путь к файлу аватарки (не используется)
    
    Returns:
        BytesIO: Буфер с изображением PNG
    """
    # Размеры графика в ультра-широком формате 
    width, height = 2880, 960  
    padding = 120  
    
    # Создаем основное изображение с темно-серым фоном с легким синеватым оттенком
    image = Image.new('RGB', (width, height), '#2D3748')
    draw = ImageDraw.Draw(image)
    
    # Загружаем шрифты (с поддержкой кириллицы)
    try:
        font_title = _load_cyrillic_font(32)
        font_medium = _load_cyrillic_font(20)
        font_small = _load_cyrillic_font(16)
        font_tiny = _load_cyrillic_font(14)
    except OSError as e:
        logger.error(f"Ошибка загрузки шрифта с поддержкой кириллицы: {e}")
        # В критическом случае пробуем загрузить через PIL напрямую
        # но это может не поддерживать кириллицу
        try:
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_medium = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 16)
            font_tiny = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            # Последняя попытка - но это может не работать с кириллицей
            logger.warning("Используется запасной шрифт, кириллица может отображаться некорректно")
            font_title = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
    
    # Добавляем заголовок
    title = "Ваша активность за 30 дней"
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, 20), title, fill='#ffffff', font=font_title)
    
    # Создаем график
    chart_x = padding
    chart_y = 70
    chart_width = width - padding * 2
    chart_height = height - chart_y - padding
    
    _create_modern_chart(draw, monthly_stats, chart_x, chart_y, chart_width, chart_height,
                        font_medium, font_small, font_tiny)
    
    # Подпись оси Y (вертикальная) - переворачиваем текст
    y_label = "Сообщений"
    y_label_bbox = draw.textbbox((0, 0), y_label, font=font_small)
    y_label_width = y_label_bbox[2] - y_label_bbox[0]
    y_label_height = y_label_bbox[3] - y_label_bbox[1]
    
    # Создаем временное изображение для поворота текста
    temp_img = Image.new('RGBA', (y_label_width, y_label_height), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    temp_draw.text((0, 0), y_label, fill='#ffffff', font=font_small)
    
    # Поворачиваем на 90 градусов
    rotated_img = temp_img.rotate(90, expand=True)
    
    # Вставляем повернутый текст
    image.paste(rotated_img, (15, (height - rotated_img.height) // 2), rotated_img)
    
    # Подпись оси X (горизонтальная)
    x_label = "Дата"
    x_label_bbox = draw.textbbox((0, 0), x_label, font=font_small)
    x_label_width = x_label_bbox[2] - x_label_bbox[0]
    draw.text(((width - x_label_width) // 2, height - 30), x_label, fill='#ffffff', font=font_small)
    
    # Добавляем полупрозрачный текст в правом нижнем углу
    watermark_text = "pixel-ut.pro"
    try:
        watermark_font = _load_cyrillic_font(18)
    except Exception:
        watermark_font = font_small  # Fallback на font_small
    
    watermark_bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
    watermark_width = watermark_bbox[2] - watermark_bbox[0]
    watermark_height = watermark_bbox[3] - watermark_bbox[1]
    
    # Позиция в правом нижнем углу с отступом
    watermark_x = width - watermark_width - 30
    watermark_y = height - watermark_height - 30
    
    # Полупрозрачный цвет (30% непрозрачности = 70% прозрачности)
    # Смешиваем #FAFAFA (30%) с #2D3748 (70%) для нового фона
    watermark_color = '#6F747B'
    draw.text((watermark_x, watermark_y), watermark_text, fill=watermark_color, font=watermark_font)
    
    # Сохраняем в буфер с максимальным качеством
    buf = BytesIO()
    image.save(buf, format='PNG', optimize=False)  # Без оптимизации для максимального качества
    buf.seek(0)
    return buf




def _generate_grid_values_smart(max_count: int, target_count: int = 5) -> List[int]:
    """
    Генерирует список округленных значений для сетки графика
    
    Args:
        max_count: Максимальное значение (количество сообщений)
        target_count: Целевое количество значений сетки (по умолчанию 5)
        
    Returns:
        List[int]: Отсортированный список округленных значений для отображения
    """
    if max_count <= 0:
        return [0]
    
    # Если значений немного, показываем все
    if max_count <= target_count:
        return list(range(0, max_count + 1))
    
    # Адаптивно определяем шаг для получения оптимального количества делений (4-7)
    # Начинаем с целевого шага
    step = max_count / target_count
    rounded_step = _round_to_standard_number(step)
    
    # Проверяем, сколько делений получится с этим шагом
    estimated_count = int(max_count / rounded_step) + 1  # +1 для 0
    
    # Если делений слишком мало (меньше 4), уменьшаем шаг
    if estimated_count < 4:
        # Пробуем уменьшить шаг, деля его на 2, 2.5, 5 и т.д.
        for divisor in [2, 2.5, 5, 10]:
            test_step = rounded_step / divisor
            if test_step > 0:
                test_rounded_step = _round_to_standard_number(test_step)
                test_count = int(max_count / test_rounded_step) + 1
                # Если получили достаточно делений (4-10), используем этот шаг
                if 4 <= test_count <= 10:
                    rounded_step = test_rounded_step
                    break
    
    # Если шаг получился слишком маленьким, увеличиваем его
    if rounded_step < max_count * 0.01:
        rounded_step = _round_to_standard_number(max_count * 0.15)
    
    # Генерируем значения сетки с округленным шагом
    values = {0}
    current = 0
    while current <= max_count:
        if current <= max_count:
            values.add(int(current))
        current += rounded_step
        # Защита от бесконечного цикла
        if len(values) > 20:
            break
    
    # Всегда добавляем максимальное значение
    if max_count not in values:
        values.add(max_count)
    
    # Сортируем и возвращаем
    result = sorted(list(values))
    
    # Гарантируем, что есть минимум 2 значения
    if len(result) < 2:
        result = [0, max_count]
    
    # Если получилось слишком много значений (больше 10), ограничиваем
    if len(result) > 10:
        # Берем каждую N-ю линию, но сохраняем первое и последнее
        step_indices = (len(result) - 1) // 8
        if step_indices > 0:
            filtered = [result[0]]  # Всегда включаем 0
            for i in range(step_indices, len(result) - 1, step_indices):
                filtered.append(result[i])
            if result[-1] not in filtered:
                filtered.append(result[-1])  # Всегда включаем максимальное значение
            result = filtered
    
    return result


def _round_to_standard_number(value: float) -> int:
    """
    Округляет число до ближайшего числа из ряда: 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000...
    Всегда округляет вверх для большего шага.
    
    Args:
        value: Число для округления
        
    Returns:
        int: Округленное число (всегда >= value)
    """
    if value <= 0:
        return 1
    
    # Определяем порядок величины
    magnitude = 10 ** (len(str(int(value))) - 1)
    
    # Нормализуем значение (приводим к диапазону 1-10)
    normalized = value / magnitude
    
    # Выбираем ближайшее число (всегда округляем вверх)
    if normalized <= 1:
        rounded = 1
    elif normalized <= 2:
        rounded = 2
    elif normalized <= 5:
        rounded = 5
    else:
        rounded = 10
        magnitude *= 10
    
    result = rounded * magnitude
    
    # Если результат меньше исходного значения, увеличиваем на порядок
    if result < value:
        if rounded == 1:
            rounded = 2
        elif rounded == 2:
            rounded = 5
        elif rounded == 5:
            rounded = 10
            magnitude *= 10
        result = rounded * magnitude
    
    return result


def _get_top_bar_color_by_activity(count: int, max_val: int, is_max: bool = False) -> str:
    """
    Вычисляет цвет верхушки столбца на основе его активности
    
    Args:
        count: Количество сообщений за день
        max_val: Максимальное значение активности среди всех дней
        is_max: Флаг, указывающий, является ли этот день самым активным
        
    Returns:
        str: Цвет в формате HEX (светло-голубая палитра для верхушки, оранжевый для максимального)
    """
    if count == 0:
        return '#E0F2FE'  # Очень светлый голубой для нулевой активности
    
    # Если это самый активный день, используем оранжевый цвет
    if is_max:
        # Оранжевый цвет (HSV: hue=30, насыщенный и яркий)
        hue = 30  # Оранжевый оттенок
        saturation = 0.85  # Высокая насыщенность
        value = 1.0  # Максимальная яркость
        r, g, b = colorsys.hsv_to_rgb(hue/360, saturation, value)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    # Нормализуем активность от 0 до 1
    normalized = min(count / max_val, 1.0)
    
    # Используем более линейную функцию для лучшего распределения градиента
    # Используем квадратный корень для небольшого сглаживания, но сохраняем различия
    intensity = normalized ** 0.5  # Более линейный переход для лучшей видимости различий
    
    # Базовый светло-голубой цвет (HSV: hue=195)
    # Расширяем диапазон насыщенности и яркости для лучшей видимости различий
    hue = 195  # Голубой оттенок
    # Насыщенность: от 20% (очень светлый) до 85% (яркий) - больший диапазон
    saturation = 0.2 + (intensity * 0.65)  # От 20% до 85% насыщенности
    # Яркость: от 85% (светлый) до 100% (яркий) - больший диапазон
    value = 0.85 + (intensity * 0.15)  # От 85% до 100% яркости
    
    # Конвертируем HSV в RGB, затем в HEX
    r, g, b = colorsys.hsv_to_rgb(hue/360, saturation, value)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _create_modern_chart(draw: ImageDraw.Draw, monthly_stats: List[Dict[str, Any]], 
                        x: int, y: int, width: int, height: int,
                        font_medium: ImageFont, font_small: ImageFont, font_tiny: ImageFont):
    """Создание современного графика активности за месяц в темной теме"""
    # Цвета для топ-3 дней
    GOLD_COLOR = '#EFBF04'  # #1
    SILVER_COLOR = '#909090'  # #2
    BRONZE_COLOR = '#CE8946'  # #3
    WHITE_COLOR = '#ffffff'  # Белый для остальных дней
    
    # Подготовка данных
    days = []
    counts = []
    
    # Заполняем данные за последние 30 дней
    def _safe_count(v):
        try:
            n = int(v or 0)
            return n if n > 0 else 0
        except Exception:
            return 0

    date_index = {d["date"]: _safe_count(d.get("message_count")) for d in monthly_stats}
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        date_str = day.strftime('%Y-%m-%d')
        days.append(date_str)
        counts.append(_safe_count(date_index.get(date_str, 0)))
    
    # Максимальное значение для масштабирования - используем реальные данные
    max_count_actual = max(counts) if counts and max(counts) > 0 else 1
    
    # Определяем топ-3 самых активных дня
    # Создаем список (индекс, количество) и сортируем по убыванию
    day_counts = [(i, count) for i, count in enumerate(counts)]
    day_counts_sorted = sorted(day_counts, key=lambda x: x[1], reverse=True)
    
    # Словарь для хранения ранга каждого дня (1=золото, 2=серебро, 3=бронза, 0=белый)
    day_ranks = {}
    for rank, (day_idx, count) in enumerate(day_counts_sorted[:3], start=1):
        if count > 0:  # Только дни с активностью могут быть в топ-3
            day_ranks[day_idx] = rank
    
    # Функция для получения цвета столбца на основе ранга
    def get_bar_color(rank):
        if rank == 1:
            return GOLD_COLOR
        elif rank == 2:
            return SILVER_COLOR
        elif rank == 3:
            return BRONZE_COLOR
        else:
            return WHITE_COLOR
    
    # Добавляем небольшой запас сверху для лучшего отображения (10% от максимального значения)
    max_val = int(max_count_actual * 1.1) + 1
    
    # Генерируем округленные значения сетки (так как точные значения показаны на столбцах)
    # Используем реальное максимальное значение для генерации сетки
    grid_values = _generate_grid_values_smart(max_count_actual, target_count=5)
    
    # Фильтруем значения, которые не превышают max_val (для правильного масштабирования)
    grid_values = [v for v in grid_values if v <= max_val]
    
    # Гарантируем минимум 2 значения (0 и максимальное значение не больше max_val)
    if len(grid_values) < 2:
        if max_count_actual > 0:
            grid_values = [0, min(max_count_actual, max_val)]
        else:
            grid_values = [0]
    
    # Если значений слишком много (больше 8), ограничиваем, но сохраняем первое и последнее
    if len(grid_values) > 8:
        # Берем каждую N-ю линию, но сохраняем первое и последнее
        step_indices = max(1, (len(grid_values) - 1) // 6)  # Делим на 6, чтобы получить ~7 значений
        filtered = [grid_values[0]]  # Всегда включаем первое значение (0)
        for i in range(step_indices, len(grid_values) - 1, step_indices):
            filtered.append(grid_values[i])
        if grid_values[-1] not in filtered:  # Всегда включаем последнее значение, если его еще нет
            filtered.append(grid_values[-1])
        grid_values = filtered
    
    # Рисуем линии сетки для всех значений
    for value in grid_values:
        # Вычисляем позицию Y для линии сетки (value / max_val дает нормализованное значение 0-1)
        y_pos = y + height - (value / max_val) * height
        
        # Сетка (более прозрачная)
        draw.line([x, y_pos, x + width, y_pos], fill='#6b7280', width=1)
        
        # Подписи значений на оси Y
        label = str(value)
        label_bbox = draw.textbbox((0, 0), label, font=font_small)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        draw.text((x - label_width - 10, y_pos - label_height // 2), 
                 label, fill='#ffffff', font=font_small)
    
    # Вычисляем параметры столбцов
    bar_spacing = width / 30
    bar_width = bar_spacing * 0.8  # Ширина столбца
    
    # Рисуем столбцы
    for i, (day, count) in enumerate(zip(days, counts)):
        try:
            bar_x = x + i * bar_spacing + (bar_spacing - bar_width) / 2
            
            if count > 0:
                bar_height_px = (count / max_val) * height
            else:
                bar_height_px = 0
                
            # Нормализуем координаты столбца и приводим к целым значениям
            y_bottom = int(y + height)
            y_top_float = (y + height) - bar_height_px
            y_top = int(y_top_float) if y_top_float <= y_bottom else y_bottom
            if y_top < y:
                y_top = y
            
            # Определяем ранг дня (1=золото, 2=серебро, 3=бронза, 0=белый)
            day_rank = day_ranks.get(i, 0)
            
            # Рисуем столбец без обводки с закругленными верхними углами
            # Рисуем даже столбцы с нулевой активностью (с минимальной высотой для видимости)
            if bar_width > 0 and y_top <= y_bottom:
                # Для нулевой активности рисуем минимальную высоту (2px) для видимости
                if bar_height_px == 0:
                    bar_height_px = 2
                    y_top = y_bottom - bar_height_px
                
                # Радиус закругления (пропорционально ширине столбца, но не больше 8px)
                radius = min(int(bar_width * 0.15), 8)
                
                # Сначала рисуем основной столбец белым с закругленными верхними углами
                _draw_rounded_top_rectangle(draw, 
                                           (int(bar_x), int(y_top), int(bar_x + bar_width), int(y_bottom)), 
                                           fill=WHITE_COLOR, 
                                           radius=radius)
                
                # Для топ-3: рисуем цветную подстветку только до половины столбца (поверх белого)
                if day_rank > 0:
                    rank_color = get_bar_color(day_rank)
                    # Высота подстветки - половина от высоты столбца
                    highlight_height = bar_height_px / 2
                    highlight_y_top = y_bottom - highlight_height
                    
                    # Рисуем цветную подстветку снизу (прямой прямоугольник, без скругления)
                    draw.rectangle([int(bar_x), int(highlight_y_top), int(bar_x + bar_width), int(y_bottom)], 
                                  fill=rank_color)
                
                # Добавляем текст с количеством сообщений вверху столбца черным цветом
                if count > 0:
                    count_text = str(count)
                    count_bbox = draw.textbbox((0, 0), count_text, font=font_tiny)
                    count_width = count_bbox[2] - count_bbox[0]
                    count_height = count_bbox[3] - count_bbox[1]
                    
                    # Позиционируем текст вверху столбца (внутри, с небольшим отступом от верха)
                    text_x = int(bar_x + (bar_width - count_width) / 2)
                    text_y = int(y_top + 3)  # Небольшой отступ от верха столбца
                    
                    # Текст черного цвета (внутри белого столбца)
                    draw.text((text_x, text_y), count_text, fill='#000000', font=font_tiny)
        except Exception:
            # Пропускаем проблемный столбец, чтобы не срывать генерацию всего изображения
            continue
        
        # Подписи дат под осью (каждые 3 дня для лучшей читаемости)
        if i % 3 == 0 or i == len(days) - 1:
            date_label = datetime.strptime(day, '%Y-%m-%d').strftime('%d.%m')
            date_bbox = draw.textbbox((0, 0), date_label, font=font_tiny)
            date_width = date_bbox[2] - date_bbox[0]
            # Поворачиваем даты на 45 градусов для лучшей читаемости
            temp_img = Image.new('RGBA', (date_width + 20, 20), (0, 0, 0, 0))
            temp_draw = ImageDraw.Draw(temp_img)
            temp_draw.text((0, 0), date_label, fill='#ffffff', font=font_tiny)
            rotated_img = temp_img.rotate(-45, expand=True)
            image = draw._image
            image.paste(rotated_img, 
                       (int(bar_x + (bar_width - rotated_img.width) / 2), 
                        int(y + height + 5)), 
                       rotated_img)
    
    # Рисуем рамку графика (после столбцов, чтобы была поверх)
    draw.rectangle([x, y, x + width, y + height], outline='#9ca3af', width=2)
    
    # Рисуем основные оси (после столбцов, чтобы были поверх)
    draw.line([x, y, x, y + height], fill='#9ca3af', width=2)  # Вертикальная ось Y
    draw.line([x, y + height, x + width, y + height], fill='#9ca3af', width=2)  # Горизонтальная ось X (нижний контур)


async def generate_top_chart(
    top_users: List[Dict[str, Any]],
    title: str = "Топ активных пользователей",
    subtitle: str = "",
    bot_instance = None
) -> BytesIO:
    """
    Генерация графика топ пользователей
    
    Args:
        top_users: Список пользователей с полями user_id, message_count, username, first_name
        title: Заголовок графика
        subtitle: Подзаголовок графика
    
    Returns:
        BytesIO: Буфер с изображением PNG
    """
    # Цветовые константы
    BG_COLOR = '#2D3748'  # Темно-серый с легким синеватым оттенком
    WHITE_COLOR = '#FAFAFA'
    GOLD_COLOR = '#EFBF04'  # #1
    SILVER_COLOR = '#909090'  # #2 (темный серый для контраста с белым столбцом)
    BRONZE_COLOR = '#CE8946'  # #3
    
    # Прозрачный белый для сетки (30% прозрачность = 70% непрозрачность)
    # Смешиваем #FAFAFA (70%) с #333B45 (30%)
    # R: 51 * 0.3 + 250 * 0.7 = 15.3 + 175 = 190.3 ≈ 190 = BE
    # G: 59 * 0.3 + 250 * 0.7 = 17.7 + 175 = 192.7 ≈ 193 = C1
    # B: 69 * 0.3 + 250 * 0.7 = 20.7 + 175 = 195.7 ≈ 196 = C4
    GRID_COLOR = '#BEC1C4'
    
    # Размеры графика (16:9)
    width, height = 2880, 1620  # Формат 16:9 для горизонтальных столбцов
    padding = 120
    
    # Создаем основное изображение с новым фоном
    image = Image.new('RGB', (width, height), BG_COLOR)
    draw = ImageDraw.Draw(image)
    
    # Загружаем шрифты для всех элементов графика
    try:
        font_title = _load_cyrillic_font(40)
        font_subtitle = _load_cyrillic_font(24)
        font_medium = _load_cyrillic_font(20)
        font_small = _load_cyrillic_font(16)
        font_tiny = _load_cyrillic_font(14)
    except Exception as e:
        logger.error(f"Ошибка загрузки шрифта: {e}")
        # Минимальный fallback на стандартный шрифт
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_tiny = ImageFont.load_default()
    
    # Заголовок
    title_y = 40
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, title_y), title, fill=WHITE_COLOR, font=font_title)
    
    if not top_users:
        # Если нет данных, показываем сообщение
        no_data_text = "Нет данных для отображения"
        no_data_bbox = draw.textbbox((0, 0), no_data_text, font=font_medium)
        no_data_width = no_data_bbox[2] - no_data_bbox[0]
        draw.text(((width - no_data_width) // 2, height // 2), no_data_text, fill=GRID_COLOR, font=font_medium)
        buf = BytesIO()
        image.save(buf, format='PNG', optimize=False)
        buf.seek(0)
        return buf
    
    # Ограничиваем количество пользователей до оптимального значения для сохранения дизайна
    MAX_DISPLAY_USERS = 15  # Оптимальное количество пользователей на графике
    top_users = top_users[:MAX_DISPLAY_USERS]
    
    # Подготовка данных
    max_count = max(user['message_count'] for user in top_users) if top_users else 1
    max_count_actual = max_count
    
    # Область графика
    # Количество пользователей для отображения (теперь всегда оптимальное)
    num_users = len(top_users)
    
    # Фиксированный размер аватарки для оптимального дизайна
    avatar_size = 80  # Стандартный размер
    
    chart_x = padding + avatar_size + 20 + 240  # Место для аватарок и подписей пользователей 
    chart_y = title_y + 105
    chart_width = width - chart_x - padding
    chart_height = height - chart_y - padding - 50  # Отступ снизу для подписей сетки
    
    # Увеличенное расстояние между столбцами для предотвращения перекрытия аватарок
    bar_spacing = 20  # Увеличено с 10 до 20 пикселей
    bar_height = (chart_height - (num_users - 1) * bar_spacing) / num_users
    bar_height = min(bar_height, 80)  # Максимальная высота столбца
    
    # Генерируем значения сетки (сначала определяем все значения)
    grid_values = _generate_grid_values_smart(max_count, target_count=5)
    
    # Проверка: гарантируем минимум 2 значения
    if len(grid_values) < 2:
        grid_values = [0, max_count] if max_count > 0 else [0]
    
    # Проверка: все значения в диапазоне [0, max_count] и нет дубликатов
    grid_values = sorted(list(set([v for v in grid_values if 0 <= v <= max_count])))
    if len(grid_values) < 2 and max_count > 0:
        grid_values = [0, max_count]
    
    # Рисуем вертикальные линии сетки (гарантированно для каждого значения)
    for value in grid_values:
        # Вычисляем позицию X для линии сетки на основе значения
        # Значение 0 соответствует началу графика (chart_x)
        # Максимальное значение соответствует концу графика (chart_x + chart_width)
        if max_count > 0:
            x_pos = chart_x + (value / max_count) * chart_width
        else:
            # Если max_count = 0, рисуем линию в начале
            x_pos = chart_x
        
        # Рисуем вертикальную линию сетки через всю область графика
        draw.line([x_pos, chart_y, x_pos, chart_y + chart_height], fill=GRID_COLOR, width=1)
        
        # Подпись значения на верхней линии сетки (Inter Semi Bold через font_medium)
        label = str(value)
        label_bbox = draw.textbbox((0, 0), label, font=font_medium)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        draw.text((x_pos - label_width // 2, chart_y - label_height - 5), 
                 label, fill=GRID_COLOR, font=font_medium)
        
        # Подпись значения на нижней линии сетки (Inter Semi Bold через font_medium)
        draw.text((x_pos - label_width // 2, chart_y + chart_height + 5), 
                 label, fill=GRID_COLOR, font=font_medium)
    
    # Получаем аватары параллельно для всех пользователей
    avatar_images = {}
    if bot_instance:
        async def get_avatar(user_id: int):
            try:
                photos = await bot_instance.get_user_profile_photos(user_id, limit=1)
                if photos and photos.total_count > 0:
                    file = await bot_instance.get_file(photos.photos[0][-1].file_id)
                    avatar_bytes = await bot_instance.download_file(file.file_path)
                    avatar_img = Image.open(avatar_bytes)
                    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                    # Создаем круглую маску
                    mask = Image.new('L', (avatar_size, avatar_size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)
                    avatar_img.putalpha(mask)
                    return user_id, avatar_img
            except Exception as e:
                logger.debug(f"Не удалось загрузить аватар для пользователя {user_id}: {e}")
            return user_id, None
        
        # Получаем все аватары параллельно
        import asyncio
        tasks = [get_avatar(user['user_id']) for user in top_users]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                user_id, avatar_img = result
                if avatar_img:
                    avatar_images[user_id] = avatar_img
    
    # Рисуем столбцы
    for i, user in enumerate(top_users):
        count = user['message_count']
        user_id = user['user_id']
        user_name = user.get('first_name', '') or user.get('username', f"ID{user_id}") or f"ID{user_id}"
        if len(user_name) > 20:
            user_name = user_name[:17] + "..."
        
        # Позиция столбца
        bar_y = chart_y + i * (bar_height + bar_spacing)
        bar_x = chart_x
        
        # Ширина столбца (динамическая, пропорциональна значению)
        if max_count > 0:
            bar_width = (count / max_count) * chart_width
        else:
            bar_width = 0
        
        # Определяем позицию (топ-3 имеют цветную подстветку)
        rank = i + 1
        
        # Для топ-3: определяем цвет подстветки
        rank_bar_color = WHITE_COLOR  # По умолчанию белый (для не топ-3)
        if rank == 1:
            rank_bar_color = GOLD_COLOR
        elif rank == 2:
            rank_bar_color = SILVER_COLOR
        elif rank == 3:
            rank_bar_color = BRONZE_COLOR
        
        # Радиус закругления (10px на всех углах кроме нижнего левого)
        radius = 10
        
        # Для топ-3: определяем высоту подстветки для метки ранга
        rank_bar_height = 0
        if rank <= 3:
            rank_bar_height = 25  # Высота подстветки для ранга
        
        # Вычисляем высоту основного бара (если есть подстветка, основной бар меньше)
        main_bar_height = bar_height - rank_bar_height if rank <= 3 else bar_height
        
        # Основной столбец всегда белый
        bar_color = WHITE_COLOR
        
        # Рисуем весь элемент (бар + подстветка) 
        if bar_width > 0 and bar_height > 0:
            # Ограничиваем радиус, чтобы он не был больше размеров столбца
            actual_radius = min(radius, max(1, int(bar_width / 2)), max(1, int(bar_height / 2)))
            
            if rank <= 3:
                # Для топ-3: сначала рисуем весь элемент цветом подстветки с общим скруглением
                if actual_radius >= 1 and bar_width >= 2 and bar_height >= 2:
                    _draw_rounded_bar_rectangle(draw, 
                                               (int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)), 
                                               fill=rank_bar_color, 
                                               radius=actual_radius)
                else:
                    draw.rectangle([int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)], 
                                  fill=rank_bar_color)
                
                # Затем поверх рисуем белый бар (до границы подстветки) с теми же скруглениями
                if main_bar_height > 0:
                    # Рисуем белый бар с скругленными верхними углами, но прямой нижней границей
                    # (чтобы не перекрывать скругление нижнего правого угла цветной подстветки)
                    if actual_radius >= 1 and bar_width >= 2 and main_bar_height >= 2:
                        # Рисуем белый прямоугольник, который закрывает верхнюю часть
                        # Используем функцию для скругления только верхних углов
                        _draw_rounded_top_rectangle(draw,
                                                   (int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + main_bar_height)),
                                                   fill=bar_color,
                                                   radius=actual_radius)
                    else:
                        draw.rectangle([int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + main_bar_height)], 
                                      fill=bar_color)
            else:
                # Для остальных: просто белый элемент с скруглением
                if actual_radius >= 1 and bar_width >= 2 and bar_height >= 2:
                    _draw_rounded_bar_rectangle(draw, 
                                               (int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)), 
                                               fill=bar_color, 
                                               radius=actual_radius)
                else:
                    draw.rectangle([int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)], 
                                  fill=bar_color)
        
        # Рисуем аватарку пользователя
        avatar_x = padding
        avatar_y = int(bar_y + (main_bar_height - avatar_size) / 2)
        
        if user_id in avatar_images:
            # Используем загруженный аватар
            image.paste(avatar_images[user_id], (avatar_x, avatar_y), avatar_images[user_id])
        else:
            # Рисуем дефолтный аватар с инициалами (используем font_medium для лучшей читаемости)
            _draw_default_avatar(draw, avatar_x, avatar_y, avatar_size, user_name, font_medium)
        
        # Подпись пользователя справа от аватарки (используем font_medium для большего размера)
        name_bbox = draw.textbbox((0, 0), user_name, font=font_medium)
        name_height = name_bbox[3] - name_bbox[1]
        name_y = int(bar_y + (main_bar_height - name_height) / 2)
        name_x = avatar_x + avatar_size + 15  # Увеличен отступ
        draw.text((name_x, name_y), user_name, fill=WHITE_COLOR, font=font_medium)
        
        # Количество сообщений - справа на конце основного столбца (в белой/цветной части)
        count_text = str(count)
        count_bbox = draw.textbbox((0, 0), count_text, font=font_medium)
        count_width = count_bbox[2] - count_bbox[0]
        count_height = count_bbox[3] - count_bbox[1]
        
        # Размещаем справа на конце столбца с отступом (в основном баре)
        padding_inside = 10
        count_x = int(bar_x + bar_width - count_width - padding_inside)
        count_y = int(bar_y + (main_bar_height - count_height) / 2)
        
        # Метка ранга для топ-3 (в подстветке снизу)
        rank_text = None
        rank_width = 0
        rank_text_height = 0
        rank_bar_y = 0
        if rank <= 3 and bar_width > 0 and rank_bar_height > 0:
            rank_text = f"#{rank}"
            rank_bbox = draw.textbbox((0, 0), rank_text, font=font_medium)
            rank_width = rank_bbox[2] - rank_bbox[0]
            rank_text_height = rank_bbox[3] - rank_bbox[1]
            rank_bar_y = bar_y + main_bar_height  # Позиция подстветки
            rank_x = int(bar_x + bar_width - rank_width - padding_inside)
            rank_y = int(rank_bar_y + (rank_bar_height - rank_text_height) / 2)
            # Используем темный цвет для контраста на цветной подстветке
            draw.text((rank_x, rank_y), rank_text, fill=BG_COLOR, font=font_medium)
        
        # Если столбец слишком узкий, размещаем текст справа от столбца
        if bar_width < count_width + padding_inside * 2:
            count_x = int(bar_x + bar_width + 10)
            draw.text((count_x, count_y), count_text, fill=GRID_COLOR, font=font_medium)
            if rank <= 3 and bar_width > 0 and rank_bar_height > 0 and rank_text:
                rank_x = int(bar_x + bar_width + 10)
                rank_y = int(rank_bar_y + (rank_bar_height - rank_text_height) / 2)
                draw.text((rank_x, rank_y), rank_text, fill=GRID_COLOR, font=font_medium)
        else:
            # Используем темный цвет для контраста (цветные столбцы имеют светлый фон)
            text_color = BG_COLOR
            draw.text((count_x, count_y), count_text, fill=text_color, font=font_medium)
    
    # Добавляем декоративные полупрозрачные кружки в углах изображения (вылезающие из углов)
    circle_radius = 20  # Радиус декоративных кружков (увеличен для большего размера)
    circle_alpha = 100  # Прозрачность (0-255, где 255 полностью непрозрачный)
    circle_color_rgb = (220, 221, 223)  # Светлый цвет (RGB)
    
    # Создаем временное RGBA изображение для круга
    circle_size = circle_radius * 2 + 2  # Немного больше для краев
    circle_img = Image.new('RGBA', (circle_size, circle_size), (0, 0, 0, 0))
    circle_draw = ImageDraw.Draw(circle_img)
    
    # Рисуем круг с альфа-каналом
    circle_draw.ellipse([
        1, 1,
        circle_size - 1, circle_size - 1
    ], fill=(*circle_color_rgb, circle_alpha))
    
    # Левый верхний угол изображения (круг вылезает из угла)
    # Центр круга в углу (0, 0), круг частично выходит за границы изображения
    paste_x = -circle_radius
    paste_y = -circle_radius
    image.paste(circle_img, (paste_x, paste_y), circle_img)
    
    # Правый верхний угол изображения (круг вылезает из угла)
    # Центр круга в углу (width, 0), круг частично выходит за границы изображения
    paste_x = width - circle_radius
    paste_y = -circle_radius
    image.paste(circle_img, (paste_x, paste_y), circle_img)
    
    # Левый нижний угол изображения (круг вылезает из угла)
    # Центр круга в углу (0, height), круг частично выходит за границы изображения
    paste_x = -circle_radius
    paste_y = height - circle_radius
    image.paste(circle_img, (paste_x, paste_y), circle_img)
    
    # Правый нижний угол изображения (круг вылезает из угла)
    # Центр круга в углу (width, height), круг частично выходит за границы изображения
    paste_x = width - circle_radius
    paste_y = height - circle_radius
    image.paste(circle_img, (paste_x, paste_y), circle_img)
    
    # Добавляем полупрозрачный текст в правом нижнем углу
    watermark_text = "pixel-ut.pro"
    try:
        watermark_font = _load_cyrillic_font(18)
    except Exception:
        watermark_font = font_small  # Fallback на font_small
    
    watermark_bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
    watermark_width = watermark_bbox[2] - watermark_bbox[0]
    watermark_height = watermark_bbox[3] - watermark_bbox[1]
    
    # Позиция в правом нижнем углу с отступом
    watermark_x = width - watermark_width - 30
    watermark_y = height - watermark_height - 30
    
    # Полупрозрачный цвет (30% непрозрачности = 70% прозрачности)
    # Смешиваем #FAFAFA (30%) с #333B45 (70%)
    # R: 51 * 0.7 + 250 * 0.3 = 35.7 + 75 = 110.7 ≈ 111 = 6F
    # G: 59 * 0.7 + 250 * 0.3 = 41.3 + 75 = 116.3 ≈ 116 = 74
    # B: 69 * 0.7 + 250 * 0.3 = 48.3 + 75 = 123.3 ≈ 123 = 7B
    watermark_color = '#6F747B'
    draw.text((watermark_x, watermark_y), watermark_text, fill=watermark_color, font=watermark_font)
    
    # Сохраняем в буфер
    buf = BytesIO()
    image.save(buf, format='PNG', optimize=False)
    buf.seek(0)
    return buf


def _draw_rounded_top_rectangle(draw: ImageDraw.Draw, xy: tuple, fill: str, radius: int = 5):
    """
    Рисует прямоугольник с закругленными верхними углами
    
    Args:
        draw: ImageDraw объект
        xy: Кортеж (x1, y1, x2, y2) координаты прямоугольника
        fill: Цвет заливки
        radius: Радиус закругления углов
    """
    x1, y1, x2, y2 = xy
    
    # Если высота меньше радиуса, используем меньший радиус
    height = y2 - y1
    if height < radius * 2:
        radius = height // 2
    
    # Если ширина меньше радиуса * 2, используем меньший радиус
    width = x2 - x1
    if width < radius * 2:
        radius = width // 2
    
    # Рисуем основной прямоугольник (без верхних углов)
    draw.rectangle([x1, y1 + radius, x2, y2], fill=fill)
    
    # Рисуем закругленные верхние углы с помощью эллипсов
    # Левый верхний угол
    draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    # Правый верхний угол
    draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    
    # Заполняем прямоугольник между эллипсами
    draw.rectangle([x1 + radius, y1, x2 - radius, y1 + radius], fill=fill)


def _draw_rounded_bar_rectangle(draw: ImageDraw.Draw, xy: tuple, fill: str, radius: int = 10):
    """
    Рисует прямоугольник с закругленными углами на всех углах кроме нижнего левого
    
    Args:
        draw: ImageDraw объект
        xy: Кортеж (x1, y1, x2, y2) координаты прямоугольника
        fill: Цвет заливки
        radius: Радиус закругления углов (по умолчанию 10px)
    """
    x1, y1, x2, y2 = xy
    
    # Если высота или ширина меньше радиуса * 2, используем меньший радиус
    height = y2 - y1
    width = x2 - x1
    actual_radius = min(radius, max(1, height // 2), max(1, width // 2))
    
    # Если радиус стал 0 или отрицательным, рисуем обычный прямоугольник
    if actual_radius <= 0:
        draw.rectangle([x1, y1, x2, y2], fill=fill)
        return
    
    # Рисуем основной прямоугольник (без закругленных углов)
    # Центральная часть (без всех углов)
    if x1 + actual_radius < x2 - actual_radius and y1 + actual_radius < y2 - actual_radius:
        draw.rectangle([x1 + actual_radius, y1 + actual_radius, x2 - actual_radius, y2 - actual_radius], fill=fill)
    
    # Левая сторона (без верхнего левого угла, включая нижний левый прямой угол)
    draw.rectangle([x1, y1 + actual_radius, x1 + actual_radius, y2], fill=fill)
    
    # Правая сторона (без верхнего и нижнего правых углов)
    if x2 - actual_radius > x1:
        draw.rectangle([x2 - actual_radius, y1 + actual_radius, x2, y2 - actual_radius], fill=fill)
    
    # Верхняя грань (без левого и правого верхних углов)
    if x1 + actual_radius < x2 - actual_radius:
        draw.rectangle([x1 + actual_radius, y1, x2 - actual_radius, y1 + actual_radius], fill=fill)
    
    # Нижняя грань (только справа, так как слева нижний угол прямой)
    if x1 + actual_radius < x2 - actual_radius:
        draw.rectangle([x1 + actual_radius, y2 - actual_radius, x2 - actual_radius, y2], fill=fill)
    
    # Рисуем закругленные углы с помощью эллипсов
    # Левый верхний угол
    if actual_radius > 0:
        draw.ellipse([x1, y1, x1 + actual_radius * 2, y1 + actual_radius * 2], fill=fill)
    # Правый верхний угол
    if actual_radius > 0:
        draw.ellipse([x2 - actual_radius * 2, y1, x2, y1 + actual_radius * 2], fill=fill)
    # Правый нижний угол
    if actual_radius > 0:
        draw.ellipse([x2 - actual_radius * 2, y2 - actual_radius * 2, x2, y2], fill=fill)
    # Нижний левый угол НЕ закругляем - оставляем прямой (уже нарисован прямоугольником выше)


def _draw_default_avatar(draw: ImageDraw.Draw, x: int, y: int, size: int, name: str, font: ImageFont.FreeTypeFont):
    """
    Рисует дефолтный аватар с инициалами пользователя
    
    Args:
        draw: ImageDraw объект
        x, y: Координаты верхнего левого угла
        size: Размер аватара
        name: Имя пользователя для получения инициалов
        font: Шрифт для текста
    """
    # Цвета для дефолтных аватаров (на основе хеша имени)
    colors = [
        '#EF4444', '#F97316', '#F59E0B', '#EAB308', '#84CC16',
        '#22C55E', '#10B981', '#14B8A6', '#06B6D4', '#0EA5E9',
        '#3B82F6', '#6366F1', '#8B5CF6', '#A855F7', '#D946EF',
        '#EC4899', '#F43F5E'
    ]
    
    # Получаем инициалы из имени
    initials = ""
    if name:
        words = name.split()
        if len(words) >= 2:
            initials = (words[0][0] + words[1][0]).upper()
        elif len(words) == 1:
            initials = words[0][0].upper()
            if len(words[0]) > 1:
                initials += words[0][1].upper()
        else:
            initials = "??"
    else:
        initials = "??"
    
    # Выбираем цвет на основе хеша имени
    color_index = hash(name) % len(colors)
    bg_color = colors[color_index]
    
    # Рисуем круглый фон
    draw.ellipse([x, y, x + size, y + size], fill=bg_color)
    
    # Рисуем инициалы
    text_bbox = draw.textbbox((0, 0), initials, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = x + (size - text_width) // 2
    text_y = y + (size - text_height) // 2
    draw.text((text_x, text_y), initials, fill='#ffffff', font=font)