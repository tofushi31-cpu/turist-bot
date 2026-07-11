import asyncio
import calendar
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import db
import mailer
import payments
import sheets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("turist-bot")

IMAGES_DIR = Path(__file__).parent / "images"
TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).split(",") if x.strip()
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class BookingStates(StatesGroup):
    waiting_date = State()
    waiting_people = State()
    waiting_wishes = State()
    waiting_custom_wish = State()
    waiting_segment = State()
    waiting_source = State()
    waiting_contact = State()
    waiting_email = State()
    waiting_comment = State()


WISH_TAGS = [
    ("water_calm", "🌊 Спокойная вода, семейный формат"),
    ("snorkel", "🤿 Снорклинг/активности в воде"),
    ("sunset", "🌅 Закат и красивые фото"),
    ("food", "🍽 Особая еда/диета"),
    ("kids", "👨‍👩‍👧 Едем с детьми"),
    ("space", "🛋 Просторные места для отдыха"),
    ("occasion", "🎉 Особый повод (др/годовщина)"),
    ("privacy", "🤫 Приватность, тихое место"),
]
WISH_LABELS = dict(WISH_TAGS)

SEGMENT_OPTIONS = [
    ("tourist", "🧳 Турист (ненадолго)"),
    ("relocant", "🏠 Переехал(а) сюда"),
]
SEGMENT_LABELS = dict(SEGMENT_OPTIONS)

SOURCE_OPTIONS = [
    ("instagram", "📷 Instagram"),
    ("friends", "👥 От друзей"),
    ("search", "🔍 Поиск в интернете"),
    ("other", "🤷 Другое"),
]
SOURCE_LABELS = dict(SOURCE_OPTIONS)

PEOPLE_PRESETS = ["1", "2", "3", "4", "5+"]


def build_people_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=n, callback_data=f"people_{n}") for n in PEOPLE_PRESETS]]
    )


def build_wishes_menu(selected: set) -> InlineKeyboardMarkup:
    rows = []
    for tag_id, label in WISH_TAGS:
        prefix = "✅ " if tag_id in selected else ""
        rows.append([InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"wish_toggle_{tag_id}")])
    rows.append([InlineKeyboardButton(text="➕ Своё пожелание", callback_data="wish_custom")])
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="wish_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_choice_menu(options: list, prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"{prefix}_{key}")] for key, label in options]
    )


contact_skip_menu = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Пропустить (только Telegram)", callback_data="contact_skip")]]
)

email_skip_menu = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Пропустить (без e-mail)", callback_data="email_skip")]]
)


class PhotoStates(StatesGroup):
    waiting_photo = State()


class AdminContentStates(StatesGroup):
    waiting_rental_price = State()
    waiting_content_photo = State()
    waiting_realestate_price = State()
    waiting_usd_rate = State()


PHOTO_FORMATS = {
    "square": (1080, 1080),
    "story": (1080, 1920),
}

photo_format_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⬛ Квадрат (пост)", callback_data="photofmt_square")],
        [InlineKeyboardButton(text="📱 Сторис/Reels", callback_data="photofmt_story")],
    ]
)

CONTENT_TEMPLATES = [
    "✨ {title}\n\n{description}\n\nЧто особенно понравится:\n{highlights}\n\nЗабронировать можно уже сегодня — {price}. Пишите в директ, ответим на все вопросы 💬",
    "{title}\n\n{description}\n\nЯркие моменты:\n{highlights}\n\nСтоимость: {price}\nМест немного, бронь — по ссылке в шапке профиля.",
    "Хотите провести день так, чтобы вспоминать его потом весь отпуск?\n\n{title} — {description}\n\nОсобенно запомнится:\n{highlights}\n\n{price}. Успейте забронировать место 🌊",
]

home_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🏠 Главная")]],
    resize_keyboard=True,
)

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def build_calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    today = datetime.now().date()
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)

    if (year, month) <= (today.year, today.month):
        prev_button = InlineKeyboardButton(text=" ", callback_data="cal_ignore")
    else:
        prev_button = InlineKeyboardButton(
            text="◀️", callback_data=f"cal_nav_{prev_year}_{prev_month}"
        )

    rows = [
        [
            prev_button,
            InlineKeyboardButton(text=f"{MONTHS_RU[month - 1]} {year}", callback_data="cal_ignore"),
            InlineKeyboardButton(text="▶️", callback_data=f"cal_nav_{next_year}_{next_month}"),
        ],
        [InlineKeyboardButton(text=day, callback_data="cal_ignore") for day in WEEKDAYS_RU],
    ]

    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal_ignore"))
                continue
            if datetime(year, month, day).date() < today:
                row.append(InlineKeyboardButton(text=str(day), callback_data="cal_ignore"))
            else:
                row.append(
                    InlineKeyboardButton(
                        text=str(day),
                        callback_data=f"cal_day_{year:04d}-{month:02d}-{day:02d}",
                    )
                )
        rows.append(row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🗺 Туры", callback_data="tours"),
            InlineKeyboardButton(text="📅 Мои брони", callback_data="menu_mybookings"),
        ],
        [
            InlineKeyboardButton(text="📄 Документы для визы", callback_data="visa_docs"),
            InlineKeyboardButton(text="📞 Контакты", callback_data="contacts"),
        ],
    ]
    if is_admin(user_id):
        active_count = len(db.list_pending_bookings())
        rows.append([
            InlineKeyboardButton(text="📋 Заявки", callback_data="menu_bookings"),
            InlineKeyboardButton(text=f"🔔 Уведомления ({active_count})", callback_data="menu_notifications"),
        ])
        rows.append([
            InlineKeyboardButton(text="📅 Расписание", callback_data="menu_calendar"),
            InlineKeyboardButton(text="📊 Топ пожеланий", callback_data="menu_wishes_stats"),
        ])
        rows.append([
            InlineKeyboardButton(text="🖼 Контент", callback_data="menu_content"),
            InlineKeyboardButton(text="📤 Фото для постов", callback_data="menu_photo"),
        ])
        rows.append([
            InlineKeyboardButton(text="🛵 Аренда мопеда", callback_data="menu_rental"),
            InlineKeyboardButton(text="🏠 Недвижимость", callback_data="menu_realestate"),
        ])
        rows.append([InlineKeyboardButton(text="💱 Валюта цен", callback_data="menu_currency")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

tours = {
    "tour_1": {
        "title": "🌊 Морская прогулка",
        "description": "3 часа вдоль побережья, остановки для купания, обед на борту.",
        "price": "от 1500₽",
        "photos": ["tour_1.jpg", "tour_1_2.jpg", "tour_1_3.jpg"],
        "highlights": [
            "Бухты с бирюзовой водой, где можно остановиться искупаться",
            "Виды на скалы и побережье прямо с борта",
            "Обед со свежей рыбой на борту",
        ],
    },
    "tour_2": {
        "title": "🏝 Остров Клеопатры",
        "description": "Целый день, снорклинг, обед включён.",
        "price": "от 2500₽",
        "photos": ["tour_2.jpg", "tour_2_2.jpg", "tour_2_3.jpg"],
        "highlights": [
            "Пляж с мелким белым песком",
            "Снорклинг у прибрежных рифов",
            "Руины древнего города рядом с пляжем",
            "Целый день без спешки — с обедом на острове",
        ],
    },
    "tour_3": {
        "title": "🌅 Закатная вечеринка на яхте",
        "description": "Вечер, живая музыка, ужин на закате.",
        "price": "от 2000₽",
        "photos": ["tour_3.jpg", "tour_3_2.jpg", "tour_3_3.jpg"],
        "highlights": [
            "Закат прямо над водой",
            "Живая музыка на палубе",
            "Ужин при свечах на закате",
        ],
    },
}


def get_tour_photos(tour_id: str) -> list[str]:
    return tours[tour_id]["photos"] + db.list_tour_photos(tour_id)


def get_display_price(tour: dict) -> str:
    currency = db.get_setting("currency", "RUB")
    if currency != "USD":
        return tour["price"]

    match = re.search(r"(\d+)", tour["price"])
    base_rub = int(match.group(1)) if match else 0
    rate = float(db.get_setting("usd_rate") or 90)
    return f"от {round(base_rub / rate)}$"


VISA_DISCLAIMER = "\n\n⚠️ Правила могут измениться — уточняйте перед поездкой на официальном сайте посольства."

VISA_INFO = {
    "thailand": {
        "label": "🇹🇭 Таиланд",
        "options": [
            (
                "exempt",
                "✈️ Безвизовый въезд",
                "60 дней (скоро 30)",
                "Безвизовый въезд: 60 дней (ожидается сокращение до 30 дней, дата ещё не объявлена — уточняйте перед поездкой)\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев на дату вылета из Таиланда)\n"
                "• Обратный билет или билет в третью страну\n"
                "• Подтверждение брони отеля/жилья\n"
                "• Финансовые гарантии: от 10 000 THB на человека / 20 000 THB на семью\n"
                "• TDAC — обязательная онлайн-анкета на tdac.immigration.go.th, заполняется за 72 часа до прилёта, бесплатно\n\n"
                "Источник: moscow.thaiembassy.org"
                + VISA_DISCLAIMER,
            ),
            (
                "tr",
                "📄 Туристическая виза (TR)",
                "$40-200 · до 60 дней",
                "Для поездок дольше безвизового срока.\n\n"
                "Документы:\n"
                "• Анкета-заявление\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев)\n"
                "• Фото\n"
                "• Подтверждение бронирования перелёта туда-обратно\n"
                "• Финансовые гарантии\n\n"
                "Стоимость: $40 (одноразовая) / $200 (мультивиза)\n"
                "Срок действия визы: 3 мес. (одноразовая) / 6 мес. (мультивиза), пребывание до 60 дней за въезд\n\n"
                "⚠️ Цены и список могут измениться — уточняйте в посольстве Таиланда перед подачей.",
            ),
            (
                "ed",
                "🎓 Учебная виза (ED)",
                "90 дней + продление",
                "Non-Immigrant ED — для поступивших на очную программу (вуз, аккредитованная языковая школа, стажировка).\n\n"
                "Документы:\n"
                "• Письмо о зачислении от аккредитованного учебного заведения Таиланда\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев)\n"
                "• Подтверждение финансов\n\n"
                "Срок: виза выдаётся на 90 дней, затем продлевается в Таиланде от 3 месяцев до 1 года по программе обучения. "
                "Работать (в т.ч. удалённо) нельзя.\n\n"
                "Источник: thaievisa.go.th"
                + VISA_DISCLAIMER,
            ),
            (
                "dtv",
                "💻 DTV — виза для удалённых работников",
                "5 лет · до 180 дней за въезд",
                "Destination Thailand Visa (DTV) — для удалённых сотрудников иностранных компаний и фрилансеров с клиентами вне "
                "Таиланда, а также участников культурных/образовательных программ от 6 мес.\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев)\n"
                "• Фото\n"
                "• Банковская выписка за 3 мес. с остатком от 500 000 THB (≈16 000 $) либо спонсорское письмо\n"
                "• Для рабочей категории — трудовой договор/портфолио с клиентами вне Таиланда\n\n"
                "Срок: виза действует 5 лет, пребывание до 180 дней за въезд (продлевается ещё на 180 дней в Таиланде)\n"
                "Стоимость: ≈10 000 THB (≈400 $)\n"
                "Оформляется только онлайн на thaievisa.go.th, находясь за пределами Таиланда. "
                "Тайский work permit по этой визе не даётся.\n\n"
                "Источник: washingtondc.thaiembassy.org"
                + VISA_DISCLAIMER,
            ),
            (
                "pension",
                "👴 Пенсионная виза (Non-O-A)",
                "1 год · от 50 лет",
                "Non-Immigrant O-A — для лиц от 50 лет.\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев)\n"
                "• Депозит от 800 000 THB (≈22 000 $) в тайском банке за 2 мес. до подачи, либо доход от 65 000 THB/мес.\n"
                "• Медстраховка (от 400 000 THB стационар / 40 000 THB амбулаторно)\n\n"
                "Срок: 1 год, продлевается. Работать запрещено.\n\n"
                "Важно: 10-летняя виза O-X гражданам РФ недоступна (закрытый список стран, России в нём нет) — "
                "для россиян доступна только годовая O-A."
                + VISA_DISCLAIMER,
            ),
            (
                "work",
                "💼 Рабочая виза (Non-B)",
                "Через работодателя",
                "Оформляется только при наличии оффера от тайского работодателя — он же подаёт документы вместе "
                "с разрешением на работу (work permit). Самостоятельно клиент её не оформляет.",
            ),
        ],
    },
    "vietnam": {
        "label": "🇻🇳 Вьетнам",
        "options": [
            (
                "exempt",
                "✈️ Безвизовый въезд",
                "45 дней",
                "Безвизовый въезд: 45 дней, любая цель поездки (действует до 14 марта 2028)\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев с даты въезда)\n"
                "• Обратный билет или билет в третью страну\n\n"
                "Источник: en.baochinhphu.vn (портал правительства Вьетнама)"
                + VISA_DISCLAIMER,
            ),
            (
                "evisa",
                "💻 Электронная виза (e-Visa)",
                "$25-50 · 90 дней",
                "Для поездок дольше 45 дней.\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев от даты въезда)\n"
                "• Цифровое фото паспортного формата\n"
                "• Банковская карта для оплаты (только онлайн, evisa.gov.vn)\n\n"
                "Стоимость: $25 (одноразовая) / $50 (многократная)\n"
                "Срок оформления: обычно 3 рабочих дня, подавать за 15-20 дней\n"
                "Оформляется только находясь за пределами Вьетнама\n\n"
                "Источник: evisa.gov.vn\n\n"
                "⚠️ Стоимость и сроки могут измениться — уточняйте на evisa.gov.vn перед подачей.",
            ),
            (
                "study",
                "🎓 Учебная виза (DH)",
                "До 12 месяцев",
                "Виза DH — для зачисленных в аккредитованное вьетнамское учебное заведение (вуз, языковая школа, курсы).\n\n"
                "Документы:\n"
                "• Официальное письмо о зачислении/приглашение от вьетнамской организации\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев, минимум на месяц дольше визы)\n\n"
                "Срок: до 12 месяцев. При долгом обучении держатель DH-визы может оформить Temporary Residence Card (TRC) "
                "категории DH — тогда не нужно часто продлевать визу."
                + VISA_DISCLAIMER,
            ),
            (
                "longstay",
                "🏠 Долгосрочное проживание",
                "e-Visa 90 дней / TRC",
                "Отдельной визы для удалённых работников или пенсионной визы во Вьетнаме нет. Реальные варианты для "
                "долгого пребывания:\n\n"
                "• Обычная 90-дневная e-Visa (мульти) — с выездом из страны каждые 90 дней для обнуления срока\n"
                "• Temporary Residence Card (TRC) — для иностранных инвесторов и членов семьи граждан Вьетнама "
                "(супруг(а)/родители/дети), срок от 2 до 10 лет в зависимости от категории, оформление 5-7 рабочих дней "
                "после подачи полного пакета документов"
                + VISA_DISCLAIMER,
            ),
            (
                "work",
                "💼 Рабочая виза (LD)",
                "Через работодателя",
                "Оформляется только при наличии трудового договора и разрешения на работу от вьетнамского работодателя — "
                "он же ведёт оформление. Самостоятельно клиент её не оформляет.",
            ),
        ],
    },
    "turkey": {
        "label": "🇹🇷 Турция",
        "options": [
            (
                "exempt",
                "✈️ Безвизовый въезд",
                "60 дней (90/180)",
                "Безвизовый въезд: до 60 дней за один въезд, не более 90 дней за 180 дней суммарно\n\n"
                "Документы:\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев с момента прибытия + ещё 60 дней сверх срока пребывания)\n"
                "• Обратный билет\n"
                "• Подтверждение брони жилья\n\n"
                "Источник: mfa.gov.tr"
                + VISA_DISCLAIMER,
            ),
            (
                "study",
                "🎓 Студенческий ВНЖ",
                "1 год, продлевается",
                "Процесс двухэтапный: сначала студенческая виза для въезда, затем в течение 30 дней после приезда — "
                "вид на жительство через e-ikamet.goc.gov.tr.\n\n"
                "Документы:\n"
                "• Справка о зачислении из университета (öğrenci belgesi)\n"
                "• 4 биометрических фото\n"
                "• Действующая медстраховка на весь срок обучения\n"
                "• Заявление через e-ikamet.goc.gov.tr\n\n"
                "Срок: 1 год, продлевается ежегодно на весь период обучения.\n\n"
                "Источник: en.goc.gov.tr"
                + VISA_DISCLAIMER,
            ),
            (
                "nomad",
                "💻 Digital Nomad Visa",
                "Доступна россиянам",
                "Виза для удалённых работников — Россия в списке разрешённых стран.\n\n"
                "Кто может: возраст 21-55 лет, доход от удалённой работы на нероссийскую/нетурецкую компанию или "
                "фриланс от 3000 $/мес. (36 000 $/год), высшее образование.\n\n"
                "Документы:\n"
                "• Диплом о высшем образовании\n"
                "• Трудовой договор или договор с иностранными клиентами (фриланс)\n"
                "• Действующая медстраховка\n"
                "• Загранпаспорт (действителен ≥ 6 месяцев), биометрическое фото\n\n"
                "Оформление: сначала заявка онлайн на digitalnomads.goturkiye.com для получения сертификата, "
                "затем виза через консульство/визовый центр.\n\n"
                "Источник: digitalnomads.goturkiye.com\n\n"
                "⚠️ Программа новая (с 2024 года) — точный срок действия визы и стоимость на официальном источнике "
                "на момент проверки не указаны. Обязательно уточняйте актуальные условия на digitalnomads.goturkiye.com "
                "перед подачей — это не окончательные цифры.",
            ),
            (
                "shortterm",
                "🏠 Краткосрочный ВНЖ",
                "До 2 лет",
                "Kısa Dönem İkamet İzni — базовый вариант пожить в Турции подольше без учёбы/работы (владение "
                "недвижимостью, лечение, исследования, инвестиции и др. законные основания).\n\n"
                "Документы: заявление только онлайн через e-ikamet.goc.gov.tr, подтверждение дохода ≈700-900 $/мес. "
                "на человека.\n\n"
                "Срок: до 2 лет за одно оформление, продлевается. Не даёт права на работу.\n\n"
                "Источник: en.goc.gov.tr\n\n"
                "⚠️ С 2024-2026 годов туристические ВНЖ без иных оснований продлеваются редко — уточняйте актуальные "
                "условия в миграционной службе Турции перед подачей.",
            ),
            (
                "work",
                "💼 Рабочее разрешение (Çalışma İzni)",
                "Через работодателя",
                "Оформляется только при наличии оффера от турецкого работодателя — он же подаёт документы через "
                "Минтруда Турции. Самостоятельно клиент его не оформляет.",
            ),
        ],
    },
}

INSURANCE_CHECKLIST_TEXT = (
    "🛡 Памятка по страховке для поездки:\n\n"
    "• Проверьте, что полис покрывает водные активности (катер, снорклинг, купание в открытой воде) — "
    "многие базовые полисы это исключают отдельным пунктом\n"
    "• Убедитесь, что есть покрытие экстренной медицинской эвакуации и репатриации\n"
    "• Обратите внимание на исключение при алкогольном опьянении — на вечерних турах с алкоголем это частая причина отказа в выплате\n"
    "• Сверьте даты полиса с датами поездки, а лимит покрытия — с реальной стоимостью лечения за рубежом\n"
    "• Уточните франшизу (сумму, которую вы оплачиваете сами до начала выплат)\n\n"
    "⚠️ Это общие ориентиры, не конкретная рекомендация — выбор конкретной страховой компании и полиса за вами."
)

BOOKING_CHECKLIST_FOR_ADMIN_TEXT = (
    "📋 Стоит уточнить у клиента перед туром:\n\n"
    "• Аллергии/ограничения в еде (на борту обед)\n"
    "• Умеет ли плавать / нет ли страха воды\n"
    "• Особый повод (день рождения, годовщина, медовый месяц)\n"
    "• Едут ли дети в группе — возраст, нужен ли детский спасательный жилет"
)


def build_visa_exempt_text() -> str:
    return next(
        text for oid, label, highlight, text in VISA_INFO["thailand"]["options"] if oid == "exempt"
    )


def build_confirmation_email_body(booking: dict) -> str:
    return (
        "Здравствуйте!\n\n"
        f"Ваша бронь на «{booking['tour_title']}» подтверждена. "
        f"Дата: {booking.get('tour_date') or 'уточняется'}.\n\n"
        "Если вы впервые в Таиланде или ещё не оформляли визу — вот актуальная информация о безвизовом въезде:\n\n"
        f"{build_visa_exempt_text()}\n\n"
        f"{INSURANCE_CHECKLIST_TEXT}\n\n"
        "До встречи на туре!"
    )


RENTAL_SAFETY_NOTES = (
    "🪖 Шлем обязателен по закону — штрафуют и без него не будет страховой защиты\n"
    "🪪 Для легальной езды нужны местные права категории A или международное водительское удостоверение\n"
    "🔧 Проверьте тормоза, шины и уровень топлива до поездки, не полагайтесь на слова арендодателя\n"
    "📸 Сфотографируйте все царапины и повреждения перед тем, как забрать мопед — так проще при возврате\n"
    "🛂 Не оставляйте в залог оригинал паспорта — только копию или депозит, оригинал документа держат при себе"
)


def build_rental_post_caption(price_text: str) -> str:
    return (
        "🛵 Аренда мопеда/мотоцикла в Таиланде\n\n"
        f"Ориентир по цене: {price_text}\n\n"
        f"{RENTAL_SAFETY_NOTES}\n\n"
        "⚠️ Цены ориентировочные и зависят от локации, сезона и модели — уточняйте на месте перед арендой."
    )


REAL_ESTATE_NOTES = (
    "🏢 Иностранцы не могут напрямую владеть землёй в Таиланде, но могут владеть квартирой в кондоминиуме — "
    "в рамках квоты 49% иностранных владельцев на здание\n"
    "📜 Для дома/земли обычная схема — долгосрочная аренда (обычно до 30 лет, уточняйте условия продления в договоре)\n"
    "📋 Проверяйте тип документа на землю — Чанот (Nor Sor 4) даёт максимум прав, другие типы ограничены\n"
    "💰 При аренде жилья стандартный депозит — 1-2 месяца + аванс за месяц, всё фиксируйте в письменном договоре\n"
    "⚖️ Перед подписанием любых документов проверяйте их у лицензированного юриста, а квоту на владение "
    "конкретным кондо — у управляющей компании здания"
)


def build_realestate_post_caption(price_text: str) -> str:
    return (
        "🏠 Недвижимость в Таиланде: аренда и покупка\n\n"
        f"Ориентир по цене: {price_text}\n\n"
        f"{REAL_ESTATE_NOTES}\n\n"
        "⚠️ Это общие ориентиры, не юридическая консультация — законы и квоты меняются, "
        "перед сделкой уточняйте актуальные условия у юриста."
    )


tours_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=tour["title"], callback_data=tour_id)]
        for tour_id, tour in tours.items()
    ]
)

content_tours_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=tour["title"], callback_data=f"draft_{tour_id}")]
        for tour_id, tour in tours.items()
    ]
)

content_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📝 Пост для Instagram", callback_data="content_draft")],
        [InlineKeyboardButton(text="📤 Загрузить фото тура", callback_data="content_upload")],
        [InlineKeyboardButton(text="🗂 Загруженные фото", callback_data="content_gallery")],
    ]
)

upload_tours_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=tour["title"], callback_data=f"uploadphoto_{tour_id}")]
        for tour_id, tour in tours.items()
    ]
)

gallery_tours_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=tour["title"], callback_data=f"gallery_{tour_id}")]
        for tour_id, tour in tours.items()
    ]
)

draft_review_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Другой вариант", callback_data="draft_regen")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="draft_approve")],
    ]
)


STATUS_LABELS = {
    "new": "🆕 новая",
    "confirmed": "✅ подтверждена",
    "paid": "💰 оплачена",
    "cancelled": "❌ отменена",
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_status_menu(booking_id: int, status: str = "new") -> InlineKeyboardMarkup | None:
    if status in ("paid", "cancelled"):
        return None

    row = []
    if status == "new":
        row.append(InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"status_confirmed_{booking_id}"))
    row.append(InlineKeyboardButton(text="💰 Оплачена", callback_data=f"status_paid_{booking_id}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"status_cancelled_{booking_id}")],
        ]
    )


def generate_caption(tour: dict, variant: int) -> str:
    template = CONTENT_TEMPLATES[variant % len(CONTENT_TEMPLATES)]
    highlights = "\n".join(f"• {item}" for item in tour["highlights"])
    return template.format(
        title=tour["title"],
        description=tour["description"],
        price=get_display_price(tour),
        highlights=highlights,
    )


def fit_and_crop(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_ratio = image.width / image.height
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_height = image.height
        new_width = round(new_height * target_ratio)
    else:
        new_width = image.width
        new_height = round(new_width / target_ratio)
    left = (image.width - new_width) // 2
    top = (image.height - new_height) // 2
    cropped = image.crop((left, top, left + new_width, top + new_height))
    return cropped.resize((target_w, target_h), Image.LANCZOS)


def build_photo_album(tour: dict) -> list[InputMediaPhoto]:
    photos = [FSInputFile(IMAGES_DIR / name) for name in tour["photos"]]
    return [InputMediaPhoto(media=photo) for photo in photos]


FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONT_BOLD = FONT_DIR / "Arial Bold.ttf"
FONT_REGULAR = FONT_DIR / "Arial.ttf"

CARD_SIZE = PHOTO_FORMATS["square"]
CARD_ACCENT = (224, 144, 74)
CARD_ACCENT_TEXT = (30, 22, 14)
CARD_INK = (250, 250, 246)
CARD_MUTED = (222, 224, 216)

EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE00-\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    return EMOJI_PATTERN.sub("", text).strip()


def add_bottom_gradient(image: Image.Image, height_ratio: float = 0.55, max_alpha: int = 235) -> Image.Image:
    w, h = image.size
    gradient_h = round(h * height_ratio)
    gradient = Image.new("L", (1, gradient_h))
    for y in range(gradient_h):
        gradient.putpixel((0, y), int(max_alpha * (y / gradient_h) ** 1.6))
    alpha_mask = gradient.resize((w, gradient_h))
    overlay = Image.new("RGBA", (w, gradient_h), (10, 14, 12, 0))
    overlay.putalpha(alpha_mask)
    result = image.convert("RGBA")
    result.paste(overlay, (0, h - gradient_h), overlay)
    return result


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_content_card(tour: dict, out_path: Path) -> Path:
    w, h = CARD_SIZE
    with Image.open(IMAGES_DIR / tour["photos"][0]) as src:
        base = fit_and_crop(src.convert("RGB"), w, h)
    card = add_bottom_gradient(base)
    draw = ImageDraw.Draw(card)

    padding = 64
    title_font = ImageFont.truetype(str(FONT_BOLD), 66)
    highlight_font = ImageFont.truetype(str(FONT_REGULAR), 34)
    price_font = ImageFont.truetype(str(FONT_BOLD), 36)

    title = strip_emoji(tour["title"])
    title_lines = wrap_text(draw, title, title_font, w - padding * 2)
    highlight_text = f"• {tour['highlights'][0]}"
    highlight_lines = wrap_text(draw, highlight_text, highlight_font, w - padding * 2)[:2]

    price_text = get_display_price(tour).replace("₽", " руб.")
    badge_pad_x, badge_pad_y = 26, 16
    price_w = draw.textlength(price_text, font=price_font)
    badge_h = 36 + badge_pad_y * 2
    draw.rounded_rectangle(
        [padding, padding, padding + price_w + badge_pad_x * 2, padding + badge_h],
        radius=badge_h / 2,
        fill=CARD_ACCENT,
    )
    draw.text((padding + badge_pad_x, padding + badge_pad_y), price_text, font=price_font, fill=CARD_ACCENT_TEXT)

    title_line_height = 78
    highlight_line_height = 44
    block_gap = 18
    block_height = (
        title_line_height * len(title_lines) + block_gap + highlight_line_height * len(highlight_lines)
    )
    y = h - padding - block_height
    for line in title_lines:
        draw.text((padding, y), line, font=title_font, fill=CARD_INK)
        y += title_line_height

    y += block_gap
    for line in highlight_lines:
        draw.text((padding, y), line, font=highlight_font, fill=CARD_MUTED)
        y += highlight_line_height

    card.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


VISA_CARD_COLORS = {
    "thailand": ((94, 30, 41), (196, 84, 60)),
    "vietnam": ((110, 20, 28), (214, 60, 50)),
    "turkey": ((120, 18, 24), (224, 58, 48)),
}
VISA_CARD_FLAG_STRIPES = {
    "thailand": [(200, 30, 40), (255, 255, 255), (30, 40, 110), (255, 255, 255), (200, 30, 40)],
    "vietnam": [(218, 37, 28)],
    "turkey": [(227, 10, 23)],
}


def diagonal_gradient(size: tuple[int, int], color_top: tuple, color_bottom: tuple) -> Image.Image:
    w, h = size
    top = Image.new("RGB", (w, h), color_top)
    bottom = Image.new("RGB", (w, h), color_bottom)
    mask = Image.new("L", (w, h))
    mask.putdata([int(255 * ((x / w + y / h) / 2)) for y in range(h) for x in range(w)])
    return Image.composite(bottom, top, mask)


def draw_flag_chip(draw: ImageDraw.ImageDraw, xy: tuple, size: tuple, stripes: list):
    x, y = xy
    w, h = size
    stripe_h = h / len(stripes)
    for i, color in enumerate(stripes):
        draw.rectangle([x, y + i * stripe_h, x + w, y + (i + 1) * stripe_h], fill=color)
    draw.rectangle([x, y, x + w, y + h], outline=(255, 255, 255), width=2)


def build_visa_card(country_id: str, country_label: str, opt_label: str, highlight: str, out_path: Path) -> Path:
    w, h = CARD_SIZE
    top_c, bottom_c = VISA_CARD_COLORS[country_id]
    card = diagonal_gradient((w, h), top_c, bottom_c)
    draw = ImageDraw.Draw(card)

    padding = 64
    country_font = ImageFont.truetype(str(FONT_REGULAR), 40)
    title_font = ImageFont.truetype(str(FONT_BOLD), 72)
    highlight_font = ImageFont.truetype(str(FONT_BOLD), 38)
    label_font = ImageFont.truetype(str(FONT_REGULAR), 30)

    chip_size = (56, 40)
    draw_flag_chip(draw, (padding, padding), chip_size, VISA_CARD_FLAG_STRIPES[country_id])
    draw.text((padding + chip_size[0] + 20, padding), strip_emoji(country_label), font=country_font, fill=CARD_MUTED)

    title_lines = wrap_text(draw, strip_emoji(opt_label), title_font, w - padding * 2)
    title_line_height = 84
    y = (h - title_line_height * len(title_lines)) / 2 - 40
    for line in title_lines:
        draw.text((padding, y), line, font=title_font, fill=CARD_INK)
        y += title_line_height

    badge_pad_x, badge_pad_y = 28, 18
    highlight_w = draw.textlength(highlight, font=highlight_font)
    badge_h = 40 + badge_pad_y * 2
    badge_y = h - padding - badge_h
    draw.rounded_rectangle(
        [padding, badge_y, padding + highlight_w + badge_pad_x * 2, badge_y + badge_h],
        radius=badge_h / 2,
        fill=(255, 255, 255),
    )
    draw.text((padding + badge_pad_x, badge_y + badge_pad_y), highlight, font=highlight_font, fill=top_c)
    draw.text((padding, badge_y - 50), "Документы для визы", font=label_font, fill=CARD_MUTED)

    card.save(out_path, "JPEG", quality=92)
    return out_path


INFO_CARD_COLORS = ((28, 70, 74), (42, 140, 128))


def build_info_card(title: str, highlight: str, caption: str, out_path: Path) -> Path:
    w, h = CARD_SIZE
    top_c, bottom_c = INFO_CARD_COLORS
    card = diagonal_gradient((w, h), top_c, bottom_c)
    draw = ImageDraw.Draw(card)

    padding = 64
    title_font = ImageFont.truetype(str(FONT_BOLD), 72)
    highlight_font = ImageFont.truetype(str(FONT_BOLD), 38)
    label_font = ImageFont.truetype(str(FONT_REGULAR), 30)

    title_lines = wrap_text(draw, strip_emoji(title), title_font, w - padding * 2)
    title_line_height = 84
    y = (h - title_line_height * len(title_lines)) / 2 - 40
    for line in title_lines:
        draw.text((padding, y), line, font=title_font, fill=CARD_INK)
        y += title_line_height

    badge_pad_x, badge_pad_y = 28, 18
    highlight_w = draw.textlength(highlight, font=highlight_font)
    badge_h = 40 + badge_pad_y * 2
    badge_y = h - padding - badge_h
    draw.rounded_rectangle(
        [padding, badge_y, padding + highlight_w + badge_pad_x * 2, badge_y + badge_h],
        radius=badge_h / 2,
        fill=(255, 255, 255),
    )
    draw.text((padding + badge_pad_x, badge_y + badge_pad_y), highlight, font=highlight_font, fill=top_c)
    draw.text((padding, badge_y - 50), caption, font=label_font, fill=CARD_MUTED)

    card.save(out_path, "JPEG", quality=92)
    return out_path


@dp.message(CommandStart())
async def handle_start(message: Message):
    await message.answer("Привет! Я твой первый бот 🎉", reply_markup=home_keyboard)
    await message.answer("Выбери, что тебя интересует:", reply_markup=build_main_menu(message.from_user.id))


@dp.message(F.text == "/myid")
async def handle_myid(message: Message):
    await message.answer(f"Твой Telegram ID: {message.from_user.id}")


@dp.message(F.text == "🏠 Главная")
async def handle_home_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=build_main_menu(message.from_user.id))


@dp.callback_query(F.data == "menu_mybookings")
async def handle_my_bookings(callback: CallbackQuery):
    bookings = db.get_client_bookings(callback.from_user.id)
    if not bookings:
        await callback.message.answer("У вас пока нет броней.")
        await callback.answer()
        return

    lines = ["📅 Ваши брони:\n"]
    for b in bookings:
        lines.append(f"«{b['tour_title']}» — {STATUS_LABELS[b['status']]} ({b['created_at']})")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data == "menu_content")
async def handle_menu_content(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Что нужно?", reply_markup=content_menu)
    await callback.answer()


@dp.callback_query(F.data == "content_draft")
async def handle_content_draft(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Выбери тур, для которого нужен пост:", reply_markup=content_tours_menu)
    await callback.answer()


@dp.callback_query(F.data == "content_upload")
async def handle_content_upload(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Для какого тура фото?", reply_markup=upload_tours_menu)
    await callback.answer()


@dp.callback_query(F.data.startswith("uploadphoto_"))
async def handle_upload_photo_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    tour_id = callback.data.removeprefix("uploadphoto_")
    await state.update_data(upload_tour_id=tour_id)
    await state.set_state(AdminContentStates.waiting_content_photo)
    await callback.message.answer(f"Пришли фото для «{tours[tour_id]['title']}» — попадёт в галерею тура.")
    await callback.answer()


@dp.message(AdminContentStates.waiting_content_photo, F.photo)
async def handle_tour_photo_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    tour_id = data["upload_tour_id"]

    photo = message.photo[-1]
    tg_file = await bot.get_file(photo.file_id)
    filename = f"{tour_id}_upload_{photo.file_id}.jpg"
    await bot.download_file(tg_file.file_path, destination=IMAGES_DIR / filename)

    db.add_tour_photo(tour_id, filename)
    await state.clear()

    total = len(get_tour_photos(tour_id))
    await message.answer(f"Фото добавлено в галерею «{tours[tour_id]['title']}» ✅ (сейчас в галерее: {total})")


@dp.message(AdminContentStates.waiting_content_photo)
async def handle_tour_photo_upload_wrong_type(message: Message):
    await message.answer("Пришли именно фото (не файл и не текст).")


@dp.callback_query(F.data == "content_gallery")
async def handle_content_gallery(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Загруженные фото какого тура показать?", reply_markup=gallery_tours_menu)
    await callback.answer()


@dp.callback_query(F.data.startswith("gallery_"))
async def handle_gallery_show(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    tour_id = callback.data.removeprefix("gallery_")
    photos = db.list_tour_photos_with_ids(tour_id)
    if not photos:
        await callback.message.answer(
            f"У «{tours[tour_id]['title']}» пока нет загруженных фото — только встроенные."
        )
        await callback.answer()
        return
    await callback.message.answer(
        f"Загруженные фото «{tours[tour_id]['title']}» ({len(photos)} шт). Встроенные фото тура не показываются и не удаляются."
    )
    for photo_id, filename in photos:
        path = IMAGES_DIR / filename
        if not path.exists():
            db.delete_tour_photo(photo_id)
            continue
        delete_button = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delphoto_{photo_id}")]]
        )
        await callback.message.answer_photo(FSInputFile(path), reply_markup=delete_button)
    await callback.answer()


@dp.callback_query(F.data.startswith("delphoto_"))
async def handle_gallery_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    photo_id = int(callback.data.removeprefix("delphoto_"))
    filename = db.delete_tour_photo(photo_id)
    if filename is None:
        await callback.answer("Это фото уже удалено", show_alert=True)
        return
    (IMAGES_DIR / filename).unlink(missing_ok=True)
    await callback.message.edit_caption(caption="🗑 Фото удалено из галереи")
    await callback.answer("Удалено ✅")


@dp.callback_query(F.data == "menu_bookings")
async def handle_menu_bookings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await send_bookings_list(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "menu_notifications")
async def handle_menu_notifications(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await send_notifications(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "menu_calendar")
async def handle_menu_calendar(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await send_calendar(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "menu_wishes_stats")
async def handle_menu_wishes_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return

    counts = db.count_wishes()
    if not counts:
        await callback.message.answer("Пока нет данных по пожеланиям.")
        await callback.answer()
        return

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    lines = ["📊 Топ пожеланий клиентов:\n"]
    for tag_id, count in ranked:
        label = WISH_LABELS.get(tag_id, tag_id)
        lines.append(f"{count} × {label}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data == "menu_photo")
async def handle_menu_photo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Какой формат нужен?", reply_markup=photo_format_menu)
    await callback.answer()


@dp.callback_query(F.data.startswith("photofmt_"))
async def handle_photo_format(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    fmt = callback.data.removeprefix("photofmt_")
    await state.update_data(photo_format=fmt)
    await state.set_state(PhotoStates.waiting_photo)
    w, h = PHOTO_FORMATS[fmt]
    await callback.message.answer(f"Пришли фото — подготовлю под {w}×{h}.")
    await callback.answer()


@dp.message(PhotoStates.waiting_photo, F.photo)
async def handle_photo_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    fmt = data.get("photo_format", "square")
    target_w, target_h = PHOTO_FORMATS[fmt]

    photo = message.photo[-1]
    tg_file = await bot.get_file(photo.file_id)
    src_path = TMP_DIR / f"src_{photo.file_id}.jpg"
    out_path = TMP_DIR / f"out_{photo.file_id}.jpg"

    try:
        await bot.download_file(tg_file.file_path, destination=src_path)

        def _process_photo():
            with Image.open(src_path) as img:
                result = fit_and_crop(img.convert("RGB"), target_w, target_h)
                result.save(out_path, "JPEG", quality=92)

        await asyncio.to_thread(_process_photo)

        await message.answer_photo(
            FSInputFile(out_path),
            caption=f"Готово: {target_w}×{target_h}",
        )
    finally:
        src_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        await state.clear()


@dp.message(PhotoStates.waiting_photo)
async def handle_photo_upload_wrong_type(message: Message):
    await message.answer("Пришли именно фото (не файл и не текст).")


rental_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📤 Сделать пост", callback_data="rental_post")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="rental_edit")],
    ]
)


@dp.callback_query(F.data == "menu_rental")
async def handle_menu_rental(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    price_text = db.get_setting("rental_price_text")
    if not price_text:
        await state.set_state(AdminContentStates.waiting_rental_price)
        await callback.message.answer("Цена ещё не задана. Введи текущий ориентир (например: 150-300 THB/день):")
        await callback.answer()
        return
    await callback.message.answer(f"Текущая цена: {price_text}", reply_markup=rental_menu)
    await callback.answer()


@dp.callback_query(F.data == "rental_edit")
async def handle_rental_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminContentStates.waiting_rental_price)
    await callback.message.answer("Введи новый ориентир цены (например: 150-300 THB/день):")
    await callback.answer()


@dp.message(AdminContentStates.waiting_rental_price)
async def handle_rental_price_text(message: Message, state: FSMContext):
    db.set_setting("rental_price_text", message.text)
    await state.clear()
    await message.answer(f"Сохранено: {message.text} ✅", reply_markup=rental_menu)


@dp.callback_query(F.data == "rental_post")
async def handle_rental_post(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    price_text = db.get_setting("rental_price_text")
    if not price_text:
        await callback.message.answer("Цена ещё не задана — сначала задай её через «✏️ Изменить цену».")
        await callback.answer()
        return

    card_path = TMP_DIR / f"rental_{uuid.uuid4().hex}.jpg"
    try:
        await asyncio.to_thread(
            build_info_card, "🛵 Аренда мопеда/мотоцикла", price_text, "Ориентир по цене", card_path
        )
        await callback.message.answer_photo(
            FSInputFile(card_path), caption=build_rental_post_caption(price_text)
        )
    finally:
        card_path.unlink(missing_ok=True)
    await callback.answer()


realestate_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📤 Сделать пост", callback_data="realestate_post")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="realestate_edit")],
    ]
)


@dp.callback_query(F.data == "menu_realestate")
async def handle_menu_realestate(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    price_text = db.get_setting("realestate_price_text")
    if not price_text:
        await state.set_state(AdminContentStates.waiting_realestate_price)
        await callback.message.answer(
            "Цена ещё не задана. Введи текущий ориентир (например: аренда 15-40к THB/мес, кондо от 2.5 млн THB):"
        )
        await callback.answer()
        return
    await callback.message.answer(f"Текущая цена: {price_text}", reply_markup=realestate_menu)
    await callback.answer()


@dp.callback_query(F.data == "realestate_edit")
async def handle_realestate_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminContentStates.waiting_realestate_price)
    await callback.message.answer("Введи новый ориентир цены (например: аренда 15-40к THB/мес, кондо от 2.5 млн THB):")
    await callback.answer()


@dp.message(AdminContentStates.waiting_realestate_price)
async def handle_realestate_price_text(message: Message, state: FSMContext):
    db.set_setting("realestate_price_text", message.text)
    await state.clear()
    await message.answer(f"Сохранено: {message.text} ✅", reply_markup=realestate_menu)


@dp.callback_query(F.data == "realestate_post")
async def handle_realestate_post(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    price_text = db.get_setting("realestate_price_text")
    if not price_text:
        await callback.message.answer("Цена ещё не задана — сначала задай её через «✏️ Изменить цену».")
        await callback.answer()
        return

    card_path = TMP_DIR / f"realestate_{uuid.uuid4().hex}.jpg"
    try:
        await asyncio.to_thread(
            build_info_card, "🏠 Недвижимость в Таиланде", price_text, "Ориентир по цене", card_path
        )
        await callback.message.answer_photo(
            FSInputFile(card_path), caption=build_realestate_post_caption(price_text)
        )
    finally:
        card_path.unlink(missing_ok=True)
    await callback.answer()


currency_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли", callback_data="currency_set_RUB")],
        [InlineKeyboardButton(text="💵 Доллары", callback_data="currency_set_USD")],
        [InlineKeyboardButton(text="✏️ Изменить курс USD", callback_data="currency_edit_rate")],
    ]
)


@dp.callback_query(F.data == "menu_currency")
async def handle_menu_currency(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    currency = db.get_setting("currency", "RUB")
    rate = db.get_setting("usd_rate")
    currency_label = "доллары" if currency == "USD" else "рубли"
    rate_line = f"\nКурс: {rate} ₽ за $1" if rate else ""
    await callback.message.answer(f"Валюта показа цен: {currency_label}{rate_line}", reply_markup=currency_menu)
    await callback.answer()


@dp.callback_query(F.data.startswith("currency_set_"))
async def handle_currency_set(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    currency = callback.data.removeprefix("currency_set_")
    if currency == "USD" and not db.get_setting("usd_rate"):
        await state.set_state(AdminContentStates.waiting_usd_rate)
        await callback.message.answer("Сначала укажи курс: сколько рублей за 1 доллар (например 90):")
        await callback.answer()
        return
    db.set_setting("currency", currency)
    label = "доллары" if currency == "USD" else "рубли"
    await callback.message.answer(f"Валюта показа цен: {label} ✅")
    await callback.answer()


@dp.callback_query(F.data == "currency_edit_rate")
async def handle_currency_edit_rate(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminContentStates.waiting_usd_rate)
    await callback.message.answer("Введи курс: сколько рублей за 1 доллар (например 90):")
    await callback.answer()


@dp.message(AdminContentStates.waiting_usd_rate)
async def handle_usd_rate_text(message: Message, state: FSMContext):
    text = (message.text or "").strip().replace(",", ".")
    try:
        rate = float(text)
        if rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 90 или 90.5. Попробуй ещё раз.")
        return

    db.set_setting("usd_rate", str(rate))
    db.set_setting("currency", "USD")
    await state.clear()
    await message.answer(f"Курс сохранён: {rate} ₽ за $1. Валюта показа цен: доллары ✅")


@dp.callback_query(F.data == "tours")
async def handle_tours(callback: CallbackQuery):
    await callback.message.answer("Выбери тур:", reply_markup=tours_menu)
    await callback.answer()


@dp.callback_query(F.data.in_(tours.keys()))
async def handle_tour_details(callback: CallbackQuery):
    tour = tours[callback.data]
    booking_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Забронировать", callback_data=f"book_{callback.data}")]]
    )
    text = f"{tour['title']}\n\n{tour['description']}\n\nЦена: {get_display_price(tour)}"
    photo = FSInputFile(IMAGES_DIR / tour["photos"][0])
    await callback.message.answer_photo(photo, caption=text, reply_markup=booking_button)
    await callback.answer()


@dp.callback_query(F.data == "visa_docs")
async def handle_visa_docs(callback: CallbackQuery):
    options = [(country_id, info["label"]) for country_id, info in VISA_INFO.items()]
    await callback.message.answer(
        "Для какой страны нужны документы на визу?", reply_markup=build_choice_menu(options, "visacountry")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("visacountry_"))
async def handle_visa_country(callback: CallbackQuery):
    country = callback.data.removeprefix("visacountry_")
    info = VISA_INFO[country]
    options = [(opt_id, label) for opt_id, label, _, _ in info["options"]]
    await callback.message.answer(
        f"{info['label']}: выберите вариант въезда", reply_markup=build_choice_menu(options, f"visaopt_{country}")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("visaopt_"))
async def handle_visa_option(callback: CallbackQuery):
    _, country, opt_id = callback.data.split("_", 2)
    info = VISA_INFO[country]
    opt_label, highlight, text = next(
        (label, highlight, text) for oid, label, highlight, text in info["options"] if oid == opt_id
    )
    card_path = TMP_DIR / f"visa_{country}_{opt_id}_{uuid.uuid4().hex}.jpg"
    await asyncio.to_thread(build_visa_card, country, info["label"], opt_label, highlight, card_path)
    try:
        await callback.message.answer_photo(FSInputFile(card_path))
    finally:
        card_path.unlink(missing_ok=True)
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data.startswith("book_"))
async def handle_booking(callback: CallbackQuery, state: FSMContext):
    tour_id = callback.data.removeprefix("book_")
    await state.update_data(tour_id=tour_id)
    await state.set_state(BookingStates.waiting_date)
    today = datetime.now()
    await callback.message.answer(
        "На какую дату?",
        reply_markup=build_calendar_keyboard(today.year, today.month),
    )
    await callback.answer()


@dp.callback_query(F.data == "cal_ignore")
async def handle_cal_ignore(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("cal_nav_"))
async def handle_cal_nav(callback: CallbackQuery):
    _, _, year, month = callback.data.split("_")
    await callback.message.edit_reply_markup(
        reply_markup=build_calendar_keyboard(int(year), int(month))
    )
    await callback.answer()


@dp.callback_query(BookingStates.waiting_date, F.data.startswith("cal_day_"))
async def handle_cal_day(callback: CallbackQuery, state: FSMContext):
    year, month, day = callback.data.removeprefix("cal_day_").split("-")
    tour_date = f"{int(day):02d}.{int(month):02d}.{year}"
    await state.update_data(tour_date=tour_date)
    await state.set_state(BookingStates.waiting_people)
    await callback.message.edit_text(f"Дата: {tour_date} ✅")
    await callback.message.answer("Сколько человек?", reply_markup=build_people_menu())
    await callback.answer()


@dp.message(BookingStates.waiting_date)
async def handle_booking_date(message: Message, state: FSMContext):
    if parse_tour_date(message.text) == datetime.max:
        await message.answer(
            "Не получилось распознать дату. Введите в формате ДД.ММ или ДД.ММ.ГГГГ, "
            "либо выберите день в календаре выше."
        )
        return
    await state.update_data(tour_date=message.text)
    await state.set_state(BookingStates.waiting_people)
    await message.answer("Сколько человек?", reply_markup=build_people_menu())


@dp.callback_query(BookingStates.waiting_people, F.data.startswith("people_"))
async def handle_people_button(callback: CallbackQuery, state: FSMContext):
    count = callback.data.removeprefix("people_")
    await state.update_data(people_count=count)
    await state.update_data(wishes=[])
    await state.set_state(BookingStates.waiting_wishes)
    await callback.message.edit_text(f"Человек: {count} ✅")
    await callback.message.answer("Что для вас важно? Выбери один или несколько вариантов:", reply_markup=build_wishes_menu(set()))
    await callback.answer()


@dp.message(BookingStates.waiting_people)
async def handle_people_text(message: Message, state: FSMContext):
    await state.update_data(people_count=message.text.strip())
    await state.update_data(wishes=[])
    await state.set_state(BookingStates.waiting_wishes)
    await message.answer("Что для вас важно? Выбери один или несколько вариантов:", reply_markup=build_wishes_menu(set()))


@dp.callback_query(BookingStates.waiting_wishes, F.data.startswith("wish_toggle_"))
async def handle_wish_toggle(callback: CallbackQuery, state: FSMContext):
    tag_id = callback.data.removeprefix("wish_toggle_")
    data = await state.get_data()
    selected = set(data.get("wishes", []))
    if tag_id in selected:
        selected.discard(tag_id)
    else:
        selected.add(tag_id)
    await state.update_data(wishes=list(selected))
    await callback.message.edit_reply_markup(reply_markup=build_wishes_menu(selected))
    await callback.answer()


@dp.callback_query(BookingStates.waiting_wishes, F.data == "wish_custom")
async def handle_wish_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.waiting_custom_wish)
    await callback.message.answer("Напиши своё пожелание одним сообщением:")
    await callback.answer()


@dp.message(BookingStates.waiting_custom_wish)
async def handle_wish_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_wish=message.text)
    await state.set_state(BookingStates.waiting_wishes)
    data = await state.get_data()
    selected = set(data.get("wishes", []))
    await message.answer(f"Добавлено: «{message.text}» ✅\n\nЕщё что-то важно?", reply_markup=build_wishes_menu(selected))


@dp.message(BookingStates.waiting_wishes)
async def handle_wishes_text_hint(message: Message):
    await message.answer("Пожалуйста, выбери вариант, нажав на кнопку выше 👆")


@dp.callback_query(BookingStates.waiting_wishes, F.data == "wish_done")
async def handle_wishes_done(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.waiting_segment)
    await callback.message.answer("Вы турист или уже переехали жить в Таиланде?", reply_markup=build_choice_menu(SEGMENT_OPTIONS, "segment"))
    await callback.answer()


@dp.callback_query(BookingStates.waiting_segment, F.data.startswith("segment_"))
async def handle_segment(callback: CallbackQuery, state: FSMContext):
    segment = callback.data.removeprefix("segment_")
    await state.update_data(segment=segment)
    await state.set_state(BookingStates.waiting_source)
    await callback.message.edit_text(f"Вы: {SEGMENT_LABELS[segment]} ✅")
    await callback.message.answer("Как узнали о нас?", reply_markup=build_choice_menu(SOURCE_OPTIONS, "source"))
    await callback.answer()


@dp.message(BookingStates.waiting_segment)
async def handle_segment_text_hint(message: Message):
    await message.answer("Пожалуйста, выбери вариант, нажав на кнопку выше 👆")


@dp.callback_query(BookingStates.waiting_source, F.data.startswith("source_"))
async def handle_source(callback: CallbackQuery, state: FSMContext):
    source = callback.data.removeprefix("source_")
    await state.update_data(source=source)
    await state.set_state(BookingStates.waiting_contact)
    await callback.message.edit_text(f"Узнали через: {SOURCE_LABELS[source]} ✅")
    await callback.message.answer(
        "Оставь запасной контакт (телефон/WhatsApp) на случай, если связь в Telegram оборвётся:",
        reply_markup=contact_skip_menu,
    )
    await callback.answer()


@dp.message(BookingStates.waiting_source)
async def handle_source_text_hint(message: Message):
    await message.answer("Пожалуйста, выбери вариант, нажав на кнопку выше 👆")


@dp.callback_query(BookingStates.waiting_contact, F.data == "contact_skip")
async def handle_contact_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(alt_contact=None)
    await state.set_state(BookingStates.waiting_email)
    await callback.message.edit_text("Запасной контакт: пропущено")
    await callback.message.answer(
        "Укажи email — пришлём туда документы для визы и памятку по страховке после подтверждения брони:",
        reply_markup=email_skip_menu,
    )
    await callback.answer()


@dp.message(BookingStates.waiting_contact)
async def handle_contact_text(message: Message, state: FSMContext):
    await state.update_data(alt_contact=message.text)
    await state.set_state(BookingStates.waiting_email)
    await message.answer(
        "Укажи email — пришлём туда документы для визы и памятку по страховке после подтверждения брони:",
        reply_markup=email_skip_menu,
    )


@dp.callback_query(BookingStates.waiting_email, F.data == "email_skip")
async def handle_email_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(client_email=None)
    await state.set_state(BookingStates.waiting_comment)
    await callback.message.edit_text("Email: пропущено")
    await callback.message.answer("Что-то ещё хотите добавить? Если нет — просто отправьте \"+\".")
    await callback.answer()


@dp.message(BookingStates.waiting_email)
async def handle_email_text(message: Message, state: FSMContext):
    email = (message.text or "").strip()
    if "@" not in email:
        await message.answer("Похоже, это не email. Попробуй ещё раз или нажми «Пропустить» выше.")
        return
    await state.update_data(client_email=email)
    await state.set_state(BookingStates.waiting_comment)
    await message.answer("Что-то ещё хотите добавить? Если нет — просто отправьте \"+\".")


@dp.message(BookingStates.waiting_comment)
async def handle_booking_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    tour_id = data["tour_id"]
    tour_date = data.get("tour_date", "не указана")
    tour_title = tours[tour_id]["title"]
    comment = message.text if message.text and message.text != "+" else "без комментария"

    people_count = data.get("people_count")
    wish_ids = data.get("wishes", [])
    wish_labels = [WISH_LABELS[w] for w in wish_ids if w in WISH_LABELS]
    if data.get("custom_wish"):
        wish_labels.append(data["custom_wish"])
    wishes_text = ", ".join(wish_labels) if wish_labels else "не указаны"

    segment = data.get("segment")
    segment_label = SEGMENT_LABELS.get(segment, "не указано")
    source = data.get("source")
    source_label = SOURCE_LABELS.get(source, "не указано")
    alt_contact = data.get("alt_contact")
    client_email = data.get("client_email")

    await state.clear()

    await message.answer(f"Спасибо! Заявка на «{tour_title}» принята, менеджер скоро свяжется с вами 🙌")

    customer = message.from_user
    customer_name = f"@{customer.username}" if customer.username else customer.full_name
    booking_id = db.add_booking(
        customer.id, customer.username, tour_id, tour_title, tour_date, comment,
        people_count=people_count, wishes=",".join(wish_ids), segment=segment,
        source=source, alt_contact=alt_contact, custom_wish=data.get("custom_wish"),
        client_email=client_email,
    )

    try:
        booking_row = db.get_booking(booking_id)
        await asyncio.to_thread(
            sheets.append_booking,
            booking_row, wishes_text, segment_label, source_label, customer_name,
            STATUS_LABELS["new"],
        )
    except Exception:
        logger.exception("Не удалось добавить заявку #%s в Google Таблицу", booking_id)

    brief = (
        f"🔔 Новая заявка #{booking_id}\n\n"
        f"Тур: {tour_title}\n"
        f"Дата: {tour_date}\n"
        f"Человек: {people_count or 'не указано'}\n"
        f"Пожелания: {wishes_text}\n"
        f"Сегмент: {segment_label}\n"
        f"Откуда узнали: {source_label}\n"
        f"Запасной контакт: {alt_contact or 'не указан'}\n"
        f"Email: {client_email or 'не указан'}\n\n"
        f"Клиент: {customer_name}\nID клиента: {customer.id}\nКомментарий: {comment}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, brief, reply_markup=build_status_menu(booking_id))
        except Exception:
            logger.exception("Не удалось отправить заявку #%s админу %s", booking_id, admin_id)


@dp.callback_query(F.data.startswith("status_"))
async def handle_status_change(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, status, booking_id = callback.data.split("_")
    booking_id = int(booking_id)
    db.update_status(booking_id, status)
    booking = db.get_booking(booking_id)

    try:
        await asyncio.to_thread(sheets.update_status, booking_id, STATUS_LABELS[status])
    except Exception:
        logger.exception("Не удалось обновить статус заявки #%s в Google Таблице", booking_id)

    await callback.message.edit_text(
        f"{callback.message.text}\n\nСтатус: {STATUS_LABELS[status]}",
        reply_markup=build_status_menu(booking_id, status),
    )
    await callback.answer(f"Статус обновлён: {STATUS_LABELS[status]}")

    if status in ("confirmed", "paid") and booking:
        client_text = {
            "confirmed": f"Ваша заявка на «{booking['tour_title']}» подтверждена! ✅",
            "paid": f"Оплата за «{booking['tour_title']}» получена, до встречи на туре! 💰",
        }[status]

        pay_markup = None
        if status == "confirmed":
            try:
                amount = extract_amount(booking["tour_id"], booking.get("people_count"))
                payment_url = await asyncio.to_thread(
                    payments.create_payment_link,
                    booking_id, amount, f"Оплата тура «{booking['tour_title']}» (заявка #{booking_id})",
                )
                if payment_url:
                    pay_markup = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить онлайн", url=payment_url)]]
                    )
            except Exception:
                logger.exception("Не удалось создать ссылку на оплату для заявки #%s", booking_id)

            await callback.message.answer(BOOKING_CHECKLIST_FOR_ADMIN_TEXT)

            client_email = booking.get("client_email")
            if client_email:
                try:
                    await asyncio.to_thread(
                        mailer.send_email,
                        client_email,
                        f"Подтверждение брони «{booking['tour_title']}»",
                        build_confirmation_email_body(booking),
                    )
                except Exception:
                    logger.exception("Не удалось отправить письмо клиенту по заявке #%s", booking_id)
            else:
                await callback.message.answer("⚠️ Email клиента не указан — информационное письмо не отправлено.")

        await bot.send_message(booking["user_id"], client_text, reply_markup=pay_markup)


def extract_amount(tour_id: str, people_count) -> str:
    match = re.search(r"(\d+)", tours.get(tour_id, {}).get("price", ""))
    base = int(match.group(1)) if match else 0
    try:
        count = max(int(people_count), 1)
    except (TypeError, ValueError):
        count = 1
    return str(base * count)


def parse_tour_date(text: str) -> datetime:
    match = re.match(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?", (text or "").strip())
    if not match:
        return datetime.max
    day, month, year_str = match.groups()
    explicit_year = year_str is not None
    year = int(year_str) if explicit_year else datetime.now().year
    if year < 100:
        year += 2000
    try:
        result = datetime(year, int(month), int(day))
    except ValueError:
        return datetime.max

    if not explicit_year and result.date() < datetime.now().date():
        try:
            result = result.replace(year=year + 1)
        except ValueError:
            return datetime.max
    return result


def format_booking_wishes(b: dict) -> str:
    wish_ids = [w for w in (b.get("wishes") or "").split(",") if w]
    labels = [WISH_LABELS.get(w, w) for w in wish_ids]
    if b.get("custom_wish"):
        labels.append(b["custom_wish"])
    return ", ".join(labels) if labels else "не указаны"


async def send_calendar(target: Message):
    bookings = db.list_all_bookings()
    if not bookings:
        await target.answer("Броней пока нет.")
        return

    bookings.sort(key=lambda b: parse_tour_date(b["tour_date"]))
    lines = ["📅 Расписание броней:\n"]
    for b in bookings:
        date_label = b["tour_date"] or "дата не указана"
        lines.append(
            f"{date_label} — «{b['tour_title']}» — {STATUS_LABELS[b['status']]}\n"
            f"   клиент: {b['username'] or b['user_id']}\n"
            f"   пожелания: {format_booking_wishes(b)}"
        )
    await target.answer("\n\n".join(lines))


@dp.message(F.text == "/calendar")
async def handle_calendar(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(f"Команда только для админа. Твой ID: {message.from_user.id}")
        return
    await send_calendar(message)


async def send_bookings_list(target: Message):
    bookings = db.list_recent_bookings(limit=10)
    if not bookings:
        await target.answer("Заявок пока нет.")
        return

    lines = ["📋 Последние заявки:\n"]
    for b in bookings:
        lines.append(
            f"#{b['id']} — {b['tour_title']} — {STATUS_LABELS[b['status']]}\n"
            f"   клиент: {b['username'] or b['user_id']}, {b['created_at']}\n"
            f"   пожелания: {format_booking_wishes(b)}"
        )
    await target.answer("\n\n".join(lines))


async def send_notifications(target: Message):
    bookings = db.list_pending_bookings()
    if not bookings:
        await target.answer("Активных заявок нет.")
        return

    for b in bookings:
        text = (
            f"#{b['id']} — {b['tour_title']}\n"
            f"Дата: {b['tour_date'] or 'не указана'}\n"
            f"Статус: {STATUS_LABELS[b['status']]}\n"
            f"Клиент: {b['username'] or b['user_id']}\n"
            f"Пожелания: {format_booking_wishes(b)}"
        )
        await target.answer(text, reply_markup=build_status_menu(b["id"], b["status"]))


@dp.message(F.text == "/bookings")
async def handle_bookings_list(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(f"Команда только для админа. Твой ID: {message.from_user.id}")
        return
    await send_bookings_list(message)


@dp.message(F.text == "/content")
async def handle_content(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(f"Команда только для админа. Твой ID: {message.from_user.id}")
        return
    await message.answer("Что нужно?", reply_markup=content_menu)


@dp.callback_query(F.data.startswith("draft_") & ~F.data.in_({"draft_regen", "draft_approve"}))
async def handle_draft_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    tour_id = callback.data.removeprefix("draft_")
    await state.update_data(draft_tour_id=tour_id, draft_variant=0)
    tour = tours[tour_id]
    caption = generate_caption(tour, variant=0)
    card_path = TMP_DIR / f"card_{tour_id}_{uuid.uuid4().hex}.jpg"
    await asyncio.to_thread(build_content_card, tour, card_path)
    try:
        await callback.message.answer_photo(FSInputFile(card_path), caption=caption, reply_markup=draft_review_menu)
    finally:
        card_path.unlink(missing_ok=True)
    await callback.answer()


@dp.callback_query(F.data == "draft_regen")
async def handle_draft_regen(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    tour_id = data.get("draft_tour_id")
    if tour_id is None:
        await callback.answer("Черновик устарел, начните заново: /content", show_alert=True)
        return
    variant = data.get("draft_variant", 0) + 1
    await state.update_data(draft_variant=variant)
    tour = tours[tour_id]
    caption = generate_caption(tour, variant=variant)
    card_path = TMP_DIR / f"card_{tour_id}_{uuid.uuid4().hex}.jpg"
    await asyncio.to_thread(build_content_card, tour, card_path)
    try:
        await callback.message.answer_photo(FSInputFile(card_path), caption=caption, reply_markup=draft_review_menu)
    finally:
        card_path.unlink(missing_ok=True)
    await callback.answer()


@dp.callback_query(F.data == "draft_approve")
async def handle_draft_approve(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.update_data(draft_tour_id=None, draft_variant=None)
    await callback.message.answer("Готово ✅ Копируй текст выше и публикуй в Instagram.")
    await callback.answer()


@dp.callback_query(F.data == "contacts")
async def handle_contacts(callback: CallbackQuery):
    await callback.message.answer("Наши контакты: @example_manager")
    await callback.answer()


@dp.message()
async def handle_echo(message: Message):
    await message.answer(f"Ты написал: {message.text}")


async def setup_commands():
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать"),
            BotCommand(command="myid", description="Узнать свой Telegram ID"),
        ],
        scope=BotCommandScopeDefault(),
    )
    for admin_id in ADMIN_IDS:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Начать"),
                BotCommand(command="myid", description="Узнать свой Telegram ID"),
                BotCommand(command="content", description="Создать пост для Instagram"),
                BotCommand(command="bookings", description="Список заявок"),
                BotCommand(command="calendar", description="Расписание броней"),
            ],
            scope=BotCommandScopeChat(chat_id=admin_id),
        )


REMINDER_CHECK_INTERVAL = 6 * 3600  # проверка каждые 6 часов


async def send_reminders_once():
    today = datetime.now().date()
    for b in db.list_all_bookings():
        if b["status"] not in ("confirmed", "paid"):
            continue
        tour_date = parse_tour_date(b["tour_date"])
        if tour_date == datetime.max:
            continue
        days_left = (tour_date.date() - today).days

        if days_left == 3 and not b["reminder_3d_sent"]:
            which, text = "3d", f"Напоминание: через 3 дня у вас «{b['tour_title']}» ({b['tour_date']}) 🌊"
        elif days_left == 1 and not b["reminder_1d_sent"]:
            which, text = "1d", f"Напоминание: завтра у вас «{b['tour_title']}» ({b['tour_date']}) 🌊"
        else:
            continue

        try:
            await bot.send_message(b["user_id"], text)
        except Exception:
            logger.exception("Не удалось отправить напоминание по брони #%s", b["id"])
        db.mark_reminder_sent(b["id"], which)


async def reminder_loop():
    while True:
        await send_reminders_once()
        await asyncio.sleep(REMINDER_CHECK_INTERVAL)


async def main():
    db.init_db()
    await setup_commands()
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
