"""Seed the Campus Lost & Found database with realistic demo data.

Idempotent: every row is inserted via get_or_create on a natural key and all
random selections are driven by ``random.seed(42)`` at the start of every
run, so re-running (even in one process) produces the exact same data and
never duplicates anything.

Creates: 3 buildings, 20 areas, 9 categories, 12 colours, 4 office staff
accounts, 30 Telegram users, 40 lost reports, 30 found reports, 25 stored
items (18 linked to found reports, 7 desk walk-ins) with dates spread over
the last two months.

It also creates the **handover history** the demo video needs: six shelf
items are matched to a fresh lost report, confirmed, handed over with a
confidential act and flipped to ``returned`` — each with a consistent
``MatchSuggestion``, ``Handover``, ``ItemStatusLog`` and report status.
Any returned item left over from an older seed is repaired the same way.
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from catalog import translation
from matching.engine import score_breakdown, score_from_breakdown
from matching.models import Handover, MatchSuggestion
from reports.models import FoundReport, LostReport
from storage.models import ItemStatusLog, StoredItem

BUILDINGS = {
    "Asosiy bino": ("Главный корпус", "Main Building", [
        ("Oshxona", "Столовая", "Canteen"),
        ("Foye", "Фойе", "Lobby"),
        ("2-qavat koridori", "Коридор 2-го этажа", "2nd Floor Corridor"),
        ("1-sonli auditoriya", "Аудитория №1", "Lecture Hall 1"),
        ("104-xona", "Кабинет 104", "Room 104"),
        ("Shimoliy lift", "Северный лифт", "North Elevator"),
        ("Avtobus bekat", "Автобусная остановка", "Bus stop"),
    ]),
    "Kutubxona": ("Библиотека", "Library", [
        ("1-qavat atriumi", "Атриум 1-го этажа", "1st Floor Atrium"),
        ("2-qavat o‘quv zali", "Учебный зал 2-го этажа", "2nd Floor Study Hall"),
        ("3-qavat o‘qish zali", "Читальный зал 3-го этажа", "3rd Floor Reading Room"),
        ("Quyi qavat kitob ombori", "Книжное хранилище (подвал)", "Basement Stacks"),
        ("Shkafchalar zonasi", "Зона шкафчиков", "Locker Area"),
        ("Kompyuter sinfxonasi", "Компьютерный класс", "Computer Lab"),
    ]),
    "Sport majmuasi": ("Спортивный комплекс", "Sport Complex", [
        ("Sport zali foyesi", "Фойе спортзала", "Gym Lobby"),
        ("Basseyn kirish qismi", "Вход в бассейн", "Swimming Pool Entrance"),
        ("Basketbol maydonchasi", "Баскетбольная площадка", "Basketball Court"),
        ("Fitnes zali", "Фитнес-зал", "Fitness Hall"),
        ("Yugurish yo‘lkasi tribunasi", "Трибуна беговой дорожки", "Track Stand"),
        ("Avtomatlar koridori", "Коридор с автоматами", "Vending Machine Corridor"),
        ("Skvosh maydonchasi", "Сквош-корты", "Squash Court Area"),
    ]),
}

CATEGORIES = [
    ("Hujjatlar", "Документы", "Documents", "📄", 180),
    ("Kalitlar", "Ключи", "Keys", "🔑", 45),
    ("Elektronika", "Электроника", "Electronics", "💻", 90),
    ("Kiyimlar", "Одежда", "Clothing", "👕", 30),
    ("Sumkalar", "Сумки", "Bags", "🎒", 60),
    ("Butilka va idishlar", "Бутылки и контейнеры", "Bottles & containers", "🧴", 30),
    ("Kitob va kantselyariya", "Книги и канцелярия", "Books & stationery", "📚", 90),
    ("Taqinchoqlar va aksessuarlar", "Украшения и аксессуары", "Jewellery & accessories", "💍", 60),
    ("Boshqalar", "Прочее", "Other", "📦", 30),
]

COLORS = [
    ("Qora", "Чёрный", "Black"),
    ("Oq", "Белый", "White"),
    ("Kulrang", "Серый", "Grey"),
    ("Qizil", "Красный", "Red"),
    ("Ko‘k", "Синий", "Blue"),
    ("Yashil", "Зелёный", "Green"),
    ("Sariq", "Жёлтый", "Yellow"),
    ("To‘q sariq", "Оранжевый", "Orange"),
    ("Pushti", "Розовый", "Pink"),
    ("Binafsha", "Фиолетовый", "Purple"),
    ("Jigarrang", "Коричневый", "Brown"),
    ("Kumushrang", "Серебристый", "Silver"),
]

FULL_NAMES = [
    "Aziz Rahmonov", "Malika Yusupova", "Timur Nazarov", "Sardor Umarov",
    "Zilola Ergasheva", "Dilshod Karimov", "Gulnora Ismailova", "Jasur Toxirov",
    "Nodira Aliyeva", "Farrux Bekmurodov", "Sevara Qodirova", "Eldor Abduvaliyev",
    "Munisa Xolmatova", "Islom Yunusov", "Kamola Rasulova", "Otabek Yusupov",
    "Rayhona Tursunova", "Damir Sokolov", "Anisa Alimova", "Sarvar Iskandarov",
    "Madina Nazarova", "Nodir Xamidov", "Zulfiya Aminova", "Khumoyun Alimov",
    "Nilufar Saidova", "Ulugbek Astanov", "Laziza Hamroyeva", "Rustam Ergashev",
    "Shahzoda Murodova", "Xurshid Rasulov",
]

STAFF_ACCOUNTS = [
    ("office.aziza", "Aziza Karimova"),
    ("office.jasur", "Jasur Xakimov"),
    ("office.nilufar", "Nilufar Toshqulova"),
    ("office.bekzod", "Bekzod Rashidov"),
]

# Item titles in all three interface languages: (uz, ru, en). Uzbek is the
# canonical/primary language — the stored `title` column gets the Uzbek text
# and the `title_uz/_ru/_en` streams are filled explicitly by the seeder.
TITLES = {
    "Hujjatlar": [
        ("Talaba guvohnomasi", "Студенческий билет", "Student ID card"),
        ("Xorijiy pasport", "Загранпаспорт", "International passport"),
        ("Avtobus kartasi", "Транспортная карта", "Bus pass"),
        ("Kurs sertifikati", "Сертификат курса", "Course certificate"),
        ("Sug‘urta kartasi", "Страховая карта", "Insurance card"),
    ],
    "Kalitlar": [
        ("Yotoqxona kalitlari", "Ключи от общежития", "Dorm key ring"),
        ("Ryukzak kalitchasi", "Брелок для рюкзака", "Backpack keychain"),
        ("Mashina kalitlari", "Ключи от машины", "Car keys"),
        ("Ofis kaliti", "Офисный ключ", "Office key with lanyard"),
    ],
    "Elektronika": [
        ("Simsiz quloqchin", "Беспроводные наушники", "Wireless earbuds"),
        ("Quvvatlash kabeli", "Кабель для зарядки", "Charging cable"),
        ("Noutbuk quvvatlagichi", "Зарядное устройство для ноутбука", "Laptop charger"),
        ("USB flesh xotira", "USB-флешка", "USB flash drive"),
        ("Aqlli soat", "Умные часы", "Smartwatch"),
    ],
    "Kiyimlar": [
        ("Qora ro‘mol", "Чёрный платок", "Black scarf"),
        ("Sport kepka", "Спортивная кепка", "Sports cap"),
        ("Qishki qo‘lqop", "Зимние перчатки", "Winter gloves"),
        ("Quloqchin qutisi", "Футляр для наушников", "Earphone case"),
        ("Issiq kurtka", "Тёплая куртка", "Warm jacket"),
    ],
    "Sumkalar": [
        ("Charm ryukzak", "Кожаный рюкзак", "Leather backpack"),
        ("Xarid paketi", "Пакет для покупок", "Shopping bag"),
        ("Yelka sumkasi", "Сумка на плечо", "Shoulder bag"),
        ("Shaffof qalamdon", "Прозрачный пенал", "Transparent pencil holder"),
    ],
    "Butilka va idishlar": [
        ("Po‘lat suv idishi", "Стальная бутылка для воды", "Steel water bottle"),
        ("Ovqat idishi", "Контейнер для еды", "Lunch container"),
        ("Kofe termosi", "Термос для кофе", "Coffee thermos"),
        ("Shisha suv bankasi", "Стеклянная банка для воды", "Glass water jar"),
    ],
    "Kitob va kantselyariya": [
        ("Statistika daftari", "Тетрадь по статистике", "Statistics notebook"),
        ("Ma’lumotlar tuzilmasi darsligi", "Учебник по структурам данных", "Data structures textbook"),
        ("Matematika qalamdoni", "Пенал для математики", "Math pen case"),
        ("Rasm papkasi", "Папка для рисования", "Art folder"),
    ],
    "Taqinchoqlar va aksessuarlar": [
        ("Kumush bilaguzuk", "Серебряный браслет", "Silver chain bracelet"),
        ("Oltin uzuk", "Золотое кольцо", "Gold ring"),
        ("Ko‘rish ko‘zoynagi", "Очки для чтения", "Reading glasses"),
        ("Qo‘l soati", "Наручные часы", "Analog wristwatch"),
        ("Soch qisqichi", "Заколка для волос", "Hair clip"),
    ],
    "Boshqalar": [
        ("Yig‘ma soyabon", "Складной зонт", "Compact umbrella"),
        ("Shaxmat taxtasi", "Шахматная доска", "Chess board"),
        ("Velosiped dubulg‘asi", "Велошлем", "Bicycle helmet"),
        ("Yoga gilami", "Коврик для йоги", "Yoga mat"),
    ],
}

# Uzbek title -> full trilingual triple (used to rebuild related records).
TITLE_BY_UZ = {
    title_uz: (title_uz, title_ru, title_en)
    for titles in TITLES.values()
    for title_uz, title_ru, title_en in titles
}

BRANDS = ["Xiaomi", "Samsung", "Apple", "Casio", "Adidas", "Nike", "Anker", "Zara", "Lotus", "Fujifilm", "Candy", "Mint"]

# `brand_marks` is a single free-text column (no translation streams), so it is
# written in the primary language.
MARKS = [
    "o‘yilgan bosh harflar", "qora-oq stiker", "singan burchak",
    "qizil popuk", "eskirgan charm tasma", "jamoa logotipi", "ko‘rinadigan belgisi yo‘q",
]

# Report descriptions are built per language: (uz, ru, en).
SCENES_LOST = [
    ("Avtobusga yugurib ketayotganda tushib qolgan.",
     "Выпал, когда я бежал(а) на автобус.",
     "Slipped out while I was running to the bus."),
    ("Ma’ruzadan keyin stol ustida qolib ketgan.",
     "Оставил(а) на столе после лекции.",
     "Left it on the desk after the lecture."),
    ("Koridorda tushirib qo‘ygan bo‘lishim mumkin.",
     "Скорее всего, выронил(а) в коридоре.",
     "Probably dropped it in the corridor."),
    ("Tashqaridagi skameykada unutib qoldirganman.",
     "Забыл(а) на скамейке на улице.",
     "Forgot it on the bench outside."),
    ("Ikki qavat orasida qayerdadir qoldirib ketganman.",
     "Оставил(а) где-то между двумя этажами.",
     "Misplaced it somewhere between the two floors."),
    ("Shkafdan yo‘qolib qolgan.",
     "Пропал из шкафчика.",
     "It disappeared from the locker."),
    ("Oxirgi marta shu joyda ko‘rganman, qaytishda topa olmadim.",
     "В последний раз видел(а) здесь, на обратном пути не нашёл(ла).",
     "Last seen in this area, found nothing on my way back."),
    ("Avtomatlar yonida qoldirib ketganman.",
     "Оставил(а) рядом с автоматами.",
     "Left it next to the vending machines."),
]

SCENES_FOUND = [
    ("Topib oldim va ofisga topshirdim.",
     "Нашёл(ла) и сдал(а) в офис.",
     "I found it and handed it in at the office."),
    ("Skameykada yotgan edi.",
     "Лежал на скамейке.",
     "It was lying on the bench."),
    ("Darsdan keyin stol ustida qolib ketgan.",
     "Остался на столе после занятия.",
     "It was left on the desk after the class."),
    ("Koridorda ko‘rib qoldim.",
     "Заметил(а) в коридоре.",
     "I spotted it in the corridor."),
    ("Avtomatlar yonida turgan edi.",
     "Стоял рядом с автоматами.",
     "It was next to the vending machines."),
    ("Zinapoyada topdim.",
     "Нашёл(ла) на лестнице.",
     "I found it on the stairs."),
]

LOST_STATUS_PLAN = ["open"] * 24 + ["matched"] * 7 + ["returned"] * 4 + ["expired"] * 4 + ["cancelled"] * 1
FOUND_STATUS_PLAN = ["open"] * 21 + ["registered"] * 6 + ["returned"] * 2 + ["cancelled"] * 1
ITEM_STATUS_PLAN = ["in_storage"] * 20 + ["returned"] * 2 + ["disposed"] * 2 + ["transferred"] * 1

# Handover history: fixed shelf codes keep the demo deterministic, while the
# "repair" pass picks up any returned item created by an older seed run.
HANDOVER_SHELF_CODES = ("A1-01", "A1-02", "A1-03", "A1-04", "A1-05", "A1-06")
HANDOVER_DAYS_AGO = (21, 18, 15, 12, 9, 6)
HANDOVER_NOTES = (
    "Talaba guvohnomasi ofisda tekshirildi.",
    "Egasi buyumni oldindan ta’riflab berdi.",
    "Qaytarish tasdiqlangan moslikdan keyin rasmiylashtirildi.",
    "Qabul qiluvchi qog‘oz dalolatnomani imzoladi.",
)


def aware(day, hour, minute=0):
    """Aware datetime in the project timezone (Asia/Tashkent)."""
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))



def description_variants(title, color, scene):
    """Build the report description in all three languages.

    ``title`` and ``scene`` are ``(uz, ru, en)`` triples; the colour names come
    from the reference table's own translation columns. Uzbek is canonical.
    """
    title_uz, title_ru, title_en = title
    scene_uz, scene_ru, scene_en = scene
    return {
        "uz": f"{title_uz}. Rangi — {color.name_uz.lower()}. {scene_uz}",
        "ru": f"{title_ru}. Цвет — {(color.name_ru or color.name_uz).lower()}. {scene_ru}",
        "en": f"{title_en}. Colour — {(color.name_en or color.name_uz).lower()}. {scene_en}",
    }


def title_streams(title):
    """``(uz, ru, en)`` triple -> ``title_uz/_ru/_en`` keyword dict."""
    title_uz, title_ru, title_en = title
    return {"title_uz": title_uz, "title_ru": title_ru, "title_en": title_en}


def description_streams(descriptions):
    """Language dict -> ``description_uz/_ru/_en`` keyword dict."""
    return {
        "description_uz": descriptions["uz"],
        "description_ru": descriptions["ru"],
        "description_en": descriptions["en"],
    }


def brand_marks_for(brand, mark):
    return f"{brand}; {mark}"


def pick_unique_date(today, span_days, key, used_keys):
    """Deterministically pick an unused date within the last span_days days."""
    for _ in range(200):
        dt = today - timedelta(days=random.randint(0, span_days))
        candidate = key(dt)
        if candidate not in used_keys:
            used_keys.add(candidate)
            return dt
    dt = today - timedelta(days=random.randint(0, span_days))
    while key(dt) in used_keys:
        dt -= timedelta(days=1)
    used_keys.add(key(dt))
    return dt


class Command(BaseCommand):
    help = "Seed all reference data, users, reports and stored items (idempotent)."

    def handle(self, *args, **options):
        random.seed(42)   # deterministic on every invocation, not just import
        today = timezone.localdate()

        self.stdout.write("Seeding reference data ...", ending=" ")
        self._seed_locations()
        self._seed_categories()
        self._seed_colors()
        self.stdout.write(self.style.SUCCESS("ok"))

        self.stdout.write("Seeding office staff ...", ending=" ")
        self._seed_staff()
        self.stdout.write(self.style.SUCCESS("ok"))


        self.stdout.write("Seeding Telegram users ...", ending=" ")
        users = self._seed_users()
        self.stdout.write(self.style.SUCCESS("ok"))

        categories = list(Category.objects.all().order_by("id"))
        colors = list(Color.objects.all().order_by("id"))
        locations = list(Location.objects.all().order_by("id"))

        with translation.disabled():
            self.stdout.write("Seeding lost reports ...", ending=" ")
            lost_created = self._seed_lost_reports(today, users, categories, colors, locations)
            self.stdout.write(self.style.SUCCESS("ok"))

            self.stdout.write("Seeding found reports ...", ending=" ")
            found_created = self._seed_found_reports(today, users, categories, colors, locations)
            self.stdout.write(self.style.SUCCESS("ok"))

            found_reports = list(FoundReport.objects.all().order_by("id"))

            self.stdout.write("Seeding stored items ...", ending=" ")
            items_created = self._seed_stored_items(found_reports, categories, colors)
            self.stdout.write(self.style.SUCCESS("ok"))

            self.stdout.write("Seeding handover history ...", ending=" ")
            acts_created = self._seed_handover_history(today, users, locations)
            self.stdout.write(self.style.SUCCESS("ok"))

            self.stdout.write("Seeding status history ...", ending=" ")
            logs_created = self._seed_status_history(today)
            self.stdout.write(self.style.SUCCESS("ok"))

        self.stdout.write(self.style.SUCCESS(
            "seed_demo finished. Created in this run: lost=%d found=%d items=%d"
            " acts=%d logs=%d. Totals:"
            " locations=%d categories=%d colors=%d staff=%d users=%d lost=%d found=%d"
            " stored=%d handovers=%d suggestions=%d"
            % (
                lost_created, found_created, items_created, acts_created, logs_created,
                Location.objects.count(), Category.objects.count(), Color.objects.count(),
                User.objects.count(), TelegramUser.objects.count(),
                LostReport.objects.count(), FoundReport.objects.count(),
                StoredItem.objects.count(), Handover.objects.count(),
                MatchSuggestion.objects.count(),
            )
        ))

    def _seed_locations(self):
        created = 0
        for building_uz, (building_ru, building_en, areas) in BUILDINGS.items():
            for area_uz, area_ru, area_en in areas:
                location, was_created = Location.objects.get_or_create(
                    building_uz=building_uz, area_uz=area_uz,
                    defaults={
                        "building_en": building_en, "building_ru": building_ru,
                        "area_en": area_en, "area_ru": area_ru,
                    },
                )
                if not was_created:
                    Location.objects.filter(pk=location.pk).update(
                        building_en=building_en, building_ru=building_ru,
                        area_en=area_en, area_ru=area_ru,
                    )
                created += was_created
        return created

    def _seed_categories(self):
        created = 0
        for name_uz, name_ru, name_en, emoji, retention in CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                name_uz=name_uz,
                defaults={"name_ru": name_ru, "name_en": name_en,
                          "emoji": emoji, "retention_days": retention},
            )
            Category.objects.filter(name_uz=name_uz).update(
                name_ru=name_ru, name_en=name_en, emoji=emoji, retention_days=retention,
            )
            created += was_created
        return created

    def _seed_colors(self):
        created = 0
        for name_uz, name_ru, name_en in COLORS:
            _, was_created = Color.objects.get_or_create(
                name_uz=name_uz,
                defaults={"name_ru": name_ru, "name_en": name_en},
            )
            Color.objects.filter(name_uz=name_uz).update(name_ru=name_ru, name_en=name_en)
            created += was_created
        return created

    def _seed_staff(self):
        created = 0
        for username, name in STAFF_ACCOUNTS:
            _, was_created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": name.split()[0], "last_name": name.split()[1], "is_staff": True},
            )
            created += was_created

        # Office superuser for /admin (credentials come from the environment,
        # never from this repo). Existing password is left untouched.
        import os

        username = os.environ.get("SEED_ADMIN_USERNAME", "").strip()
        password = os.environ.get("SEED_ADMIN_PASSWORD", "")
        if username and password:
            user, was_created = User.objects.get_or_create(
                username=username,
                defaults={"is_staff": True, "is_superuser": True},
            )
            if was_created:
                user.set_password(password)
                user.save()
            created += was_created
        return created

    def _seed_users(self):
        users = []
        for index, name in enumerate(FULL_NAMES):
            user, _ = TelegramUser.objects.get_or_create(
                telegram_id=700000000 + 37 * (index + 1),
                defaults={
                    "username": name.lower().replace(" ", "_")[:32],
                    "display_name": name,
                    "language": ("uz", "ru", "en")[index % 3],
                    "student_staff_id": f"SF{index:05d}" if index % 2 == 0 else None,
                    "is_blocked": index in (7, 19),
                },
            )
            users.append(user)
        return users

    def _seed_lost_reports(self, today, users, categories, colors, locations):
        created = 0
        used_keys = set()
        for number in range(40):
            category = categories[number % len(categories)]
            reporter = random.choice(users)
            title = random.choice(TITLES[category.name_uz])
            color = random.choice(colors)
            scene = random.choice(SCENES_LOST)
            brand = random.choice(BRANDS)
            mark = random.choice(MARKS)
            status = LOST_STATUS_PLAN[number % len(LOST_STATUS_PLAN)]
            location = None if number % 5 == 0 else random.choice(locations)
            descriptions = description_variants(title, color, scene)
            title_uz, title_ru, title_en = title
            date_lost = pick_unique_date(
                today, 59, lambda d,rid=reporter.id,t=title_uz: (rid, t, d), used_keys
            )
            report, was_created = LostReport.objects.get_or_create(
                reporter=reporter, category=category, title=title_uz,
                defaults={
                    "description": descriptions["uz"],
                    "color": color,
                    "brand_marks": brand_marks_for(brand, mark),
                    "location": location,
                    "date_lost": date_lost,
                    "status": status,
                },
            )
            # Streams are written with queryset.update() so the model's
            # reporter-language sync cannot overwrite them.
            LostReport.objects.filter(pk=report.pk).update(
                **title_streams(title), **description_streams(descriptions)
            )
            created += was_created
        return created

    def _seed_found_reports(self, today, users, categories, colors, locations):
        created = 0
        used_keys = set()
        for number in range(30):
            category = categories[number % len(categories)]
            reporter = random.choice(users)
            title = random.choice(TITLES[category.name_uz])
            color = random.choice(colors)
            scene = random.choice(SCENES_FOUND)
            brand = random.choice(BRANDS)
            mark = random.choice(MARKS)
            status = FOUND_STATUS_PLAN[number % len(FOUND_STATUS_PLAN)]
            location = random.choice(locations)
            custody = "handed_to_office" if number % 3 != 2 else "kept_by_finder"
            finder_contact_allowed = number % 4 == 0
            descriptions = description_variants(title, color, scene)
            title_uz, title_ru, title_en = title
            date_found = pick_unique_date(
                today, 59, lambda d,rid=reporter.id,t=title_uz: (rid, t, d), used_keys
            )
            report, was_created = FoundReport.objects.get_or_create(
                reporter=reporter, category=category, title=title_uz,
                defaults={
                    "description": descriptions["uz"],
                    "color": color,
                    "location": location,
                    "date_found": date_found,
                    "photo_file_id": "",
                    "custody": custody,
                    "finder_contact_allowed": finder_contact_allowed,
                    "status": status,
                },
            )
            FoundReport.objects.filter(pk=report.pk).update(
                **title_streams(title), **description_streams(descriptions)
            )
            created += was_created
        return created

    def _seed_stored_items(self, found_reports, categories, colors):
        created = 0
        block_letters = ["A", "B", "C"]
        linked_found_reports = found_reports[:18]
        today = timezone.localdate()
        all_titles = [t for titles in TITLES.values() for t in titles]
        for number in range(25):
            letter = block_letters[(number // 9) % 3]
            block_number = (number // 9) + 1
            compartment = (number % 9) + 1
            shelf_code = f"{letter}{block_number}-{compartment:02d}"
            title_uz, title_ru, title_en = all_titles[number % len(all_titles)]
            category = categories[number % len(categories)]
            status = ITEM_STATUS_PLAN[number % len(ITEM_STATUS_PLAN)]
            found_report = linked_found_reports[number] if number < 18 else None
            item_color = random.choice(colors)
            # StoredItem has a single title/description column, so the office
            # shelf records use the primary language (Uzbek).
            item, was_created = StoredItem.objects.get_or_create(
                title=title_uz, shelf_code=shelf_code,
                defaults={
                    "found_report": found_report,
                    "category": category,
                    "description": description_variants(
                        (title_uz, title_ru, title_en), item_color, random.choice(SCENES_FOUND)
                    )["uz"],
                    "color": item_color,
                    "received_by": User.objects.get(username=STAFF_ACCOUNTS[number % 4][0]),
                    "status": status,
                },
            )
            created += was_created
            # A handover item owns its historical received date and its found
            # report is already ``returned``; re-seeding must not rewrite them.
            if Handover.objects.filter(stored_item_id=item.pk).exists():
                continue
            received_days_back = random.randint(0, 55)
            received_at = timezone.now() - timedelta(days=received_days_back,
                                                     hours=number, minutes=(number * 7) % 60)
            stored_day = timezone.localdate(received_at)
            StoredItem.objects.filter(pk=item.pk).update(
                received_at=received_at,
                retention_until=stored_day + timedelta(days=category.retention_days),
            )
            if found_report is not None:
                found_status = "returned" if status == "returned" else "registered"
                FoundReport.objects.filter(pk=found_report.pk).exclude(
                    status=found_status
                ).update(status=found_status)
        return created

    def _seed_handover_history(self, today, users, locations):
        """Create confirmed matches + handover acts with a coherent timeline.

        Each act is atomic: the lost report, confirmed suggestion, handover,
        status log and the returned flips on the item/found/lost reports all
        land together or not at all. Re-running skips items that already have
        a handover, so the command stays idempotent.
        """
        created = 0
        staff_accounts = list(
            User.objects.filter(username__in=[username for username, _ in STAFF_ACCOUNTS])
            .order_by("username")
        )
        select_related = ("found_report", "found_report__reporter", "category", "color")
        targets = list(
            StoredItem.objects.select_related(*select_related)
            .filter(shelf_code__in=HANDOVER_SHELF_CODES)
            .order_by("shelf_code")
        )
        # Repair a returned item created by an older seed (no act yet).
        targets += list(
            StoredItem.objects.select_related(*select_related)
            .filter(status="returned", handover__isnull=True)
            .exclude(shelf_code__in=HANDOVER_SHELF_CODES)
            .order_by("shelf_code")
        )

        for index, item in enumerate(targets):
            if item.status not in ("in_storage", "returned"):
                continue
            if Handover.objects.filter(stored_item_id=item.pk).exists():
                continue

            days_ago = (
                HANDOVER_DAYS_AGO[index]
                if index < len(HANDOVER_DAYS_AGO)
                else 4 + (index - len(HANDOVER_DAYS_AGO))
            )
            handover_day = today - timedelta(days=days_ago)
            received_day = handover_day - timedelta(days=2)
            found_day = received_day - timedelta(days=1)
            lost_day = found_day - timedelta(days=2)
            handover_at = aware(handover_day, 14, 30)
            location = locations[(index * 3) % len(locations)]
            reporter = users[(index * 5 + 2) % len(users)]
            if item.found_report_id and reporter.pk == item.found_report.reporter_id:
                reporter = users[(index * 5 + 3) % len(users)]
            staff = staff_accounts[index % len(staff_accounts)]
            note = HANDOVER_NOTES[index % len(HANDOVER_NOTES)]

            with transaction.atomic():
                if item.found_report_id:
                    FoundReport.objects.filter(pk=item.found_report_id).update(
                        date_found=found_day,
                        location=location,
                        created_at=aware(found_day, 9),
                    )
                StoredItem.objects.filter(pk=item.pk).update(
                    received_at=aware(received_day, 10),
                    retention_until=received_day + timedelta(days=item.category.retention_days),
                )
                item = StoredItem.objects.select_related(*select_related).get(pk=item.pk)

                title = TITLE_BY_UZ.get(item.title, (item.title, item.title, item.title))
                descriptions = description_variants(
                    title, item.color, SCENES_LOST[index % len(SCENES_LOST)]
                )
                lost, _ = LostReport.objects.get_or_create(
                    reporter=reporter,
                    category=item.category,
                    title=item.title,
                    date_lost=lost_day,
                    defaults={
                        "description": descriptions["uz"],
                        "color": item.color,
                        "location": location,
                        "status": "open",
                    },
                )
                lost.description = descriptions["uz"]
                lost.color = item.color
                lost.location = location
                lost.status = "open"
                lost.save()
                LostReport.objects.filter(pk=lost.pk).update(
                    created_at=aware(lost_day, 18),
                    **title_streams(title), **description_streams(descriptions),
                )

                breakdown = score_breakdown(lost, item)
                score = score_from_breakdown(breakdown)
                reviewed_at = aware(handover_day, 11)
                suggestion, _ = MatchSuggestion.objects.get_or_create(
                    lost_report=lost,
                    stored_item=item,
                    defaults={
                        "found_report": item.found_report,
                        "score": score,
                        "score_breakdown": breakdown,
                        "created_by": "system",
                        "status": "confirmed",
                        "reviewed_by": staff,
                        "reviewed_at": reviewed_at,
                    },
                )
                suggestion.found_report = item.found_report
                suggestion.score = score
                suggestion.score_breakdown = breakdown
                suggestion.created_by = "system"
                suggestion.status = "confirmed"
                suggestion.reviewed_by = staff
                suggestion.reviewed_at = reviewed_at
                suggestion.save()
                MatchSuggestion.objects.filter(pk=suggestion.pk).update(
                    created_at=aware(received_day, 15)
                )

                handover, _ = Handover.objects.get_or_create(
                    stored_item=item,
                    defaults={
                        "lost_report": lost,
                        "receiver_name": lost.reporter.display_name,
                        "receiver_id_last4": str((1000 + index * 137) % 10000).zfill(4),
                        "staff": staff,
                        "note": note,
                    },
                )
                Handover.objects.filter(pk=handover.pk).update(handed_at=handover_at)

                item.status = "returned"
                item.save(update_fields=["status"])
                log, _ = ItemStatusLog.objects.get_or_create(
                    item=item,
                    old_status="in_storage",
                    new_status="returned",
                    staff=staff,
                    note=note,
                    defaults={},
                )
                ItemStatusLog.objects.filter(pk=log.pk).update(created_at=handover_at)

                if item.found_report_id:
                    FoundReport.objects.filter(pk=item.found_report_id).update(
                        status="returned"
                    )
                LostReport.objects.filter(pk=lost.pk).update(status="returned")
            created += 1
        return created

    def _seed_status_history(self, today):
        """Give disposed/transferred items the audit rows the UI expects."""
        created = 0
        staff = User.objects.get(username=STAFF_ACCOUNTS[0][0])
        items = (
            StoredItem.objects.filter(status__in=("disposed", "transferred"))
            .filter(status_logs__isnull=True)
            .select_related("category")
            .order_by("shelf_code")
        )
        for index, item in enumerate(items):
            if item.status == "disposed":
                note = "Saqlash muddati tugadi — buyum ofis xodimlari tomonidan utilizatsiya qilindi."
            else:
                note = "Buyum boshqa kampus ofisiga o‘tkazildi."
            log = ItemStatusLog.objects.create(
                item=item,
                old_status="in_storage",
                new_status=item.status,
                staff=staff,
                note=note,
            )
            when = aware(today - timedelta(days=4 + index), 16)
            ItemStatusLog.objects.filter(pk=log.pk).update(created_at=when)
            created += 1
        return created
