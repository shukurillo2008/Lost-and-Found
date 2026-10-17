"""Seed the Campus Lost & Found database with realistic demo data.

Idempotent: every row is inserted via get_or_create on a natural key and all
random selections are driven by ``random.seed(42)``, so re-running produces
the exact same data and never duplicates anything.

Creates: 3 buildings, 20 areas, 9 categories, 12 colours, 4 office staff
accounts, 30 Telegram users, 40 lost reports, 30 found reports, 25 stored
items (18 linked to found reports, 7 desk walk-ins) with dates spread over
the last two months.
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from reports.models import FoundReport, LostReport
from storage.models import StoredItem

random.seed(42)

BUILDINGS = {
    "Main Building": [
        "Canteen", "Lobby", "2nd Floor Corridor", "Lecture Hall 1",
        "Room 104", "North Elevator", "Bus stop",
    ],
    "Library": [
        "1st Floor Atrium", "2nd Floor Study Hall", "3rd Floor Reading Room",
        "Basement Stacks", "Locker Area", "Computer Lab",
    ],
    "Sport Complex": [
        "Gym Lobby", "Swimming Pool Entrance", "Basketball Court",
        "Fitness Hall", "Track Stand", "Vending Machine Corridor",
        "Squash Court Area",
    ],
}

CATEGORIES = [
    ("documents", "📄", 180),
    ("keys", "🔑", 45),
    ("electronics", "💻", 90),
    ("clothing", "👕", 30),
    ("bags", "🎒", 60),
    ("bottles & containers", "🧴", 30),
    ("books & stationery", "📚", 90),
    ("jewellery & accessories", "💍", 60),
    ("other", "📦", 30),
]

COLORS = [
    "black", "white", "grey", "red", "blue", "green",
    "yellow", "orange", "pink", "purple", "brown", "silver",
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

TITLES = {
    "documents": ["Student ID card", "International passport", "Bus pass", "Course certificate", "Insurance card"],
    "keys": ["Dorm key ring", "Backpack keychain", "Car keys", "Office key with lanyard"],
    "electronics": ["Wireless earbuds", "Charging cable", "Laptop charger", "USB flash drive", "Smartwatch"],
    "clothing": ["Black scarf", "Sports cap", "Winter gloves", "Earphone case", "Warm jacket"],
    "bags": ["Leather backpack", "Shopping bag", "Shoulder bag", "Transparent pencil holder"],
    "bottles & containers": ["Steel water bottle", "Lunch container", "Coffee thermos", "Glass water jar"],
    "books & stationery": ["Statistics notebook", "Data structures textbook", "Math pen case", "Art folder"],
    "jewellery & accessories": ["Silver chain bracelet", "Gold ring", "Reading glasses", "Analog wristwatch", "Hair clip"],
    "other": ["Compact umbrella", "Chess board", "Bicycle helmet", "Yoga mat"],
}

BRANDS = ["Xiaomi", "Samsung", "Apple", "Casio", "Adidas", "Nike", "Anker", "Zara", "Lotus", "Fujifilm", "Candy", "Mint"]

MARKS = [
    "engraved initials", "black-and-white sticker", "cracked corner",
    "red tassel", "worn leather strap", "team logo print", "no visible marks",
]

SCENES = [
    "Slipped out while I was running to the bus.",
    "Left it on the desk after the lecture.",
    "Probably dropped it in the corridor.",
    "Forgot it on the bench outside.",
    "Misplaced it somewhere between the two floors.",
    "It disappeared from the locker.",
    "Last seen in this area, found nothing on my way back.",
    "Left it next to the vending machines.",
]

LOST_STATUS_PLAN = ["open"] * 24 + ["matched"] * 7 + ["returned"] * 4 + ["expired"] * 4 + ["cancelled"] * 1
FOUND_STATUS_PLAN = ["open"] * 21 + ["registered"] * 6 + ["returned"] * 2 + ["cancelled"] * 1
ITEM_STATUS_PLAN = ["in_storage"] * 20 + ["returned"] * 2 + ["disposed"] * 2 + ["transferred"] * 1


def description_for(title, color_name, scene):
    return f"{title}. Looked {color_name} in colour. {scene}"


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

        self.stdout.write(self.style.SUCCESS(
            "seed_demo finished. Created in this run: lost=%d found=%d items=%d. Totals:"
            " locations=%d categories=%d colors=%d staff=%d users=%d lost=%d found=%d stored=%d"
            % (
                lost_created, found_created, items_created,
                Location.objects.count(), Category.objects.count(), Color.objects.count(),
                User.objects.count(), TelegramUser.objects.count(),
                LostReport.objects.count(), FoundReport.objects.count(),
                StoredItem.objects.count(),
            )
        ))

    def _seed_locations(self):
        created = 0
        for building, areas in BUILDINGS.items():
            for area in areas:
                _, was_created = Location.objects.get_or_create(building=building, area=area)
                created += was_created
        return created

    def _seed_categories(self):
        created = 0
        for name, emoji, retention in CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                name=name, defaults={"emoji": emoji, "retention_days": retention}
            )
            created += was_created
        return created

    def _seed_colors(self):
        created = 0
        for name in COLORS:
            _, was_created = Color.objects.get_or_create(name=name)
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
            title = random.choice(TITLES[category.name])
            color = random.choice(colors)
            scene = random.choice(SCENES)
            brand = random.choice(BRANDS)
            mark = random.choice(MARKS)
            status = LOST_STATUS_PLAN[number % len(LOST_STATUS_PLAN)]
            location = None if number % 5 == 0 else random.choice(locations)
            date_lost = pick_unique_date(
                today, 59, lambda d,rid=reporter.id,t=title: (rid, t, d), used_keys
            )
            _, was_created = LostReport.objects.get_or_create(
                reporter=reporter, category=category, title=title, date_lost=date_lost,
                defaults={
                    "description": description_for(title, color.name, scene),
                    "color": color,
                    "brand_marks": brand_marks_for(brand, mark),
                    "location": location,
                    "status": status,
                },
            )
            created += was_created
        return created

    def _seed_found_reports(self, today, users, categories, colors, locations):
        created = 0
        used_keys = set()
        for number in range(30):
            category = categories[number % len(categories)]
            reporter = random.choice(users)
            title = random.choice(TITLES[category.name])
            color = random.choice(colors)
            scene = random.choice(SCENES)
            brand = random.choice(BRANDS)
            mark = random.choice(MARKS)
            status = FOUND_STATUS_PLAN[number % len(FOUND_STATUS_PLAN)]
            location = random.choice(locations)
            custody = "handed_to_office" if number % 3 != 2 else "kept_by_finder"
            finder_contact_allowed = number % 4 == 0
            date_found = pick_unique_date(
                today, 59, lambda d,rid=reporter.id,t=title: (rid, t, d), used_keys
            )
            _, was_created = FoundReport.objects.get_or_create(
                reporter=reporter, category=category, title=title, date_found=date_found,
                defaults={
                    "description": description_for(title, color.name, scene),
                    "color": color,
                    "location": location,
                    "photo_file_id": "",
                    "custody": custody,
                    "finder_contact_allowed": finder_contact_allowed,
                    "status": status,
                },
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
            title = all_titles[number % len(all_titles)]
            category = categories[number % len(categories)]
            status = ITEM_STATUS_PLAN[number % len(ITEM_STATUS_PLAN)]
            found_report = linked_found_reports[number] if number < 18 else None
            item, was_created = StoredItem.objects.get_or_create(
                title=title, shelf_code=shelf_code,
                defaults={
                    "found_report": found_report,
                    "category": category,
                    "description": description_for(
                        title, random.choice(colors).name, random.choice(SCENES)
                    ),
                    "color": random.choice(colors),
                    "received_by": User.objects.get(username=STAFF_ACCOUNTS[number % 4][0]),
                    "status": status,
                },
            )
            created += was_created
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
