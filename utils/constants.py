"""
Константы для бота
"""
from aiogram.fsm.state import State, StatesGroup

# Ранги модерации
RANK_OWNER = 1
RANK_ADMIN = 2
RANK_SENIOR_MOD = 3
RANK_JUNIOR_MOD = 4
RANK_USER = 5

RANK_NAMES = {
    1: ("Владелец", "Владельцы"),
    2: ("Администратор", "Администраторы"),
    3: ("Старший модератор", "Старшие модераторы"),
    4: ("Младший модератор", "Младшие модераторы"),
    5: ("Пользователь", "Пользователи")
}

# Дефолтная конфигурация прав для рангов
DEFAULT_RANK_PERMISSIONS = {
    1: {  # Владелец - все права
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': True, 'can_assign_rank_3': True,
        'can_assign_rank_2': True, 'can_remove_rank': True,
        'can_config_warns': True, 'can_config_ranks': True,
        'can_manage_rules': True,
        'can_view_stats': True,
        'can_view_punishhistory': True
    },
    2: {  # Администратор - настройки и назначение
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': True, 'can_assign_rank_3': True,
        'can_assign_rank_2': False, 'can_remove_rank': True,
        'can_config_warns': True, 'can_config_ranks': True,
        'can_manage_rules': True,
        'can_view_stats': True,
        'can_view_punishhistory': True
    },
    3: {  # Старший модератор - баны и кики
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_manage_rules': False,
        'can_view_stats': True,
        'can_view_punishhistory': True
    },
    4: {  # Младший модератор - варны и муты
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': False, 'can_ban': False, 'can_unban': False,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_manage_rules': False,
        'can_view_stats': True,
        'can_view_punishhistory': False
    },
    5: {  # Пользователь - нет прав
        'can_warn': False, 'can_unwarn': False,
        'can_mute': False, 'can_unmute': False,
        'can_kick': False, 'can_ban': False, 'can_unban': False,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_manage_rules': False,
        'can_view_stats': False,
        'can_view_punishhistory': False
    }
}

# Префиксы callback_data, относящиеся к панелям настроек
SETTINGS_CALLBACK_PREFIXES = (
    "settings_",      # корневое меню настроек и навигация
    "warnconfig_",    # настройки варнов
    "rankconfig_",    # настройки рангов/прав
    "russianprefix_", # настройка русского префикса
    "autojoin_",      # автодопуск
)

# Состояния FSM
class BotStates(StatesGroup):
    """Состояния бота"""
    waiting_for_action = State()

