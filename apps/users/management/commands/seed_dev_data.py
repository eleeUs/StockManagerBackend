"""
Management command: seed_dev_data

Creates a consistent, realistic development dataset idempotently.
Running this command multiple times is safe — it uses get_or_create
throughout so no duplicate records are created.

Usage:
    python manage.py seed_dev_data
    python manage.py seed_dev_data --flush   # clears all data first (dev only)
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.branches.models import Branch
from apps.products.models import Category, Product
from apps.suppliers.models import Supplier
from apps.stock.models import Stock
from apps.users.models import User


BRANCHES = [
    {"name": "Downtown",  "address": "123 Main St"},
    {"name": "Northside", "address": "456 North Ave"},
    {"name": "Westgate",  "address": "789 West Blvd"},
]

CATEGORIES = ["Electronics", "Stationery", "Cleaning Supplies"]

SUPPLIERS = [
    {"name": "TechSource Wholesale", "contact_email": "orders@techsource.dev"},
    {"name": "OfficePlus Distribution", "contact_email": "sales@officeplus.dev"},
]

PRODUCTS = [
    {"sku": "ELEC-001", "name": "Wireless Mouse",     "category": "Electronics",       "unit_type": "unit",   "cost_price": "8.50",  "sale_price": "14.99"},
    {"sku": "ELEC-002", "name": "USB Hub 4-Port",     "category": "Electronics",       "unit_type": "unit",   "cost_price": "6.00",  "sale_price": "11.50"},
    {"sku": "ELEC-003", "name": "HDMI Cable 2m",      "category": "Electronics",       "unit_type": "unit",   "cost_price": "3.20",  "sale_price": "7.99"},
    {"sku": "STAT-001", "name": "A4 Paper Ream",      "category": "Stationery",        "unit_type": "unit",   "cost_price": "2.10",  "sale_price": "4.50"},
    {"sku": "STAT-002", "name": "Ballpoint Pens Box", "category": "Stationery",        "unit_type": "unit",   "cost_price": "1.80",  "sale_price": "3.99"},
    {"sku": "STAT-003", "name": "Sticky Notes Pack",  "category": "Stationery",        "unit_type": "unit",   "cost_price": "1.20",  "sale_price": "2.99"},
    {"sku": "CLEA-001", "name": "Floor Cleaner",      "category": "Cleaning Supplies", "unit_type": "weight", "cost_price": "4.00",  "sale_price": "8.50"},
    {"sku": "CLEA-002", "name": "Disinfectant Spray", "category": "Cleaning Supplies", "unit_type": "unit",   "cost_price": "2.75",  "sale_price": "6.25"},
]

# Initial stock quantities per branch (product_sku → quantity)
INITIAL_STOCK = {
    "Downtown":  {"ELEC-001": 50, "ELEC-002": 30, "ELEC-003": 40, "STAT-001": 100, "STAT-002": 80,  "STAT-003": 60,  "CLEA-001": 25,  "CLEA-002": 35},
    "Northside": {"ELEC-001": 20, "ELEC-002": 15, "ELEC-003": 20, "STAT-001": 50,  "STAT-002": 40,  "STAT-003": 30,  "CLEA-001": 10,  "CLEA-002": 20},
    "Westgate":  {"ELEC-001": 35, "ELEC-002": 25, "ELEC-003": 30, "STAT-001": 75,  "STAT-002": 60,  "STAT-003": 45,  "CLEA-001": 15,  "CLEA-002": 25},
}

USERS = [
    {
        "email":     "admin@stockapp.dev",
        "full_name": "System Admin",
        "role":      "admin",
        "branch":    None,
        "password":  "admin1234!",
    },
    {
        "email":     "downtown.seller@stockapp.dev",
        "full_name": "Downtown Seller",
        "role":      "seller",
        "branch":    "Downtown",
        "password":  "seller1234!",
    },
    {
        "email":     "northside.seller@stockapp.dev",
        "full_name": "Northside Seller",
        "role":      "seller",
        "branch":    "Northside",
        "password":  "seller1234!",
    },
    {
        "email":     "westgate.seller@stockapp.dev",
        "full_name": "Westgate Seller",
        "role":      "seller",
        "branch":    "Westgate",
        "password":  "seller1234!",
    },
]


class Command(BaseCommand):
    help = "Seed the development database with initial data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing data before seeding. USE IN DEVELOPMENT ONLY.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._confirm_flush()
            self._flush()

        with transaction.atomic():
            branches   = self._seed_branches()
            categories = self._seed_categories()
            suppliers  = self._seed_suppliers()
            products   = self._seed_products(categories)
            self._seed_stock(products, branches)
            self._seed_users(branches)

        self.stdout.write(self.style.SUCCESS(
            "\n✓ Development seed complete.\n"
            f"  Branches:   {len(branches)}\n"
            f"  Categories: {len(categories)}\n"
            f"  Suppliers:  {len(suppliers)}\n"
            f"  Products:   {len(products)}\n"
            f"  Users:      {len(USERS)}\n\n"
            "Admin credentials:\n"
            f"  Email:    admin@stockapp.dev\n"
            f"  Password: admin1234!\n"
        ))

    # ------------------------------------------------------------------
    # Seed helpers
    # ------------------------------------------------------------------

    def _seed_branches(self):
        branches = {}
        for data in BRANCHES:
            branch, created = Branch.objects.get_or_create(
                name=data["name"],
                defaults={"address": data["address"]},
            )
            branches[branch.name] = branch
            self._log_created("Branch", branch.name, created)
        return branches

    def _seed_categories(self):
        categories = {}
        for name in CATEGORIES:
            category, created = Category.objects.get_or_create(name=name)
            categories[name] = category
            self._log_created("Category", name, created)
        return categories

    def _seed_suppliers(self):
        suppliers = {}
        for data in SUPPLIERS:
            supplier, created = Supplier.objects.get_or_create(
                name=data["name"],
                defaults={"contact_email": data["contact_email"]},
            )
            suppliers[supplier.name] = supplier
            self._log_created("Supplier", supplier.name, created)
        return suppliers

    def _seed_products(self, categories):
        products = {}
        for data in PRODUCTS:
            product, created = Product.objects.get_or_create(
                sku=data["sku"],
                defaults={
                    "name":       data["name"],
                    "category":   categories[data["category"]],
                    "unit_type":  data["unit_type"],
                    "cost_price": Decimal(data["cost_price"]),
                    "sale_price": Decimal(data["sale_price"]),
                },
            )
            products[product.sku] = product
            self._log_created("Product", f"{product.sku} — {product.name}", created)
        return products

    def _seed_stock(self, products, branches):
        for branch_name, stock_map in INITIAL_STOCK.items():
            branch = branches[branch_name]
            for sku, qty in stock_map.items():
                product = products[sku]
                stock, created = Stock.objects.get_or_create(
                    product=product,
                    branch=branch,
                    defaults={"quantity": Decimal(str(qty))},
                )
                if created:
                    self.stdout.write(
                        f"  [+] Stock  {branch_name:12} | {sku:10} | qty={qty}"
                    )

    def _seed_users(self, branches):
        for data in USERS:
            branch = branches.get(data["branch"]) if data["branch"] else None
            user, created = User.objects.get_or_create(
                email=data["email"],
                defaults={
                    "full_name": data["full_name"],
                    "role":      data["role"],
                    "branch":    branch,
                },
            )
            if created:
                user.set_password(data["password"])
                user.save(update_fields=["password"])
            self._log_created("User", f"{data['full_name']} ({data['role']})", created)

    def _log_created(self, model_name, identifier, created):
        prefix = "[+]" if created else "[ ]"
        action = "created" if created else "already exists"
        self.stdout.write(f"  {prefix} {model_name:12} {identifier} — {action}")

    def _confirm_flush(self):
        self.stdout.write(self.style.WARNING(
            "\n⚠  --flush will DELETE all data. This cannot be undone.\n"
            "   Type 'yes' to continue, anything else to abort: "
        ), ending="")
        if input().strip().lower() != "yes":
            raise CommandError("Flush aborted.")

    def _flush(self):
        self.stdout.write(self.style.WARNING("  Flushing all data..."))
        from apps.movements.models import StockMovement
        StockMovement.objects.all().delete()
        Stock.objects.all().delete()
        User.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        Branch.objects.all().delete()
        self.stdout.write(self.style.WARNING("  Done.\n"))
