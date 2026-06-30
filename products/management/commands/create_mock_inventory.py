import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from accounts.models import User
from products.models import Product, ProductCategory, StockMovement
from tenants.models import Tenant


PRODUCT_NAMES = [
    "Mikro Fiber Temizlik Bezi", "Klima Gazı R410A 1kg", "Beyaz Isı Yalıtım Bandı",
    "Hijyen Eldiven 100'lü Mavi", "Elektrik Bandı Siyah 18mm", "Termometre Lazerli -50~600°C",
    "Multimetre Dijital Otomatik", "Lehim Makinesi 60W Ayarlı", "Havya Ucu Seti 10'lu",
    "Vida Seti Karma 600 Parça", "Matkap Ucu Seti HSS 13'lü", "Sıkma Pense 9\" Profesyonel",
    "Yan Keski 7\" İzole", "Kombi Anahtar Seti 12'li", "Sifon Tamir Takımı Universal",
    "Termostatik Vana DN15", "Radyatör Hava Purjörü 1/2\"", "Tesisat Kelepçesi 3/4\" 10'lu",
    "Esnek Bağlantı 1/2\" 30cm", "Basınç Düşürücü 1/2\" Ayarlı", "Filtre Kartuşu 10\" 5 Mikron",
    "Pompa Contası 2\" Silikon", "Motor Yağı 5W-30 4L Tam Sentetik", "Fren Balata Ön Set",
    "Polen Filtresi Standart", "Yağ Filtresi Spin-On", "Hava Filtresi Panel Tip",
    "Akü 60Ah Tam Bakımsız", "Silecek Süpürgesi 24\" + 18\" Set", "Lamba H4 60/55W Halojen",
    "LED Far H7 6000K Beyaz", "Kablo Bağı 4.8x300mm 100'lü", "Spiral Kablo Kanalı 25mm 2m",
    "Anahtar Priz Çerçeve Beyaz", "Priz Kapağı Çocuk Korumalı", "Kablo Kesici 0.5-6mm²",
    "Sıcak Silikon Tabancası 60W", "Yapıştırıcı Epoksi 25ml", "Bant Çift Taraflı 19mm 5m",
    "Köpük Temizleyici 750ml", "Cam Temizleyici Sprey 500ml", "Pas Sökücü Sprey 400ml",
    "WD-40 Yağlayıcı 300ml", "Kontakt Sprey 200ml", "Toz Maskesi FFP2 10'lu",
    "Koruyucu Gözlük Şeffaf", "İş Eldiveni Latex Pudrasız 100'lü", "Emniyet Kemeri (Araç Tipi)",
    "Seyyar Lamba LED 30W", "Projektör LED 50W IP65", "Pil AA Alkalin 4'lü",
    "Pil 9V Alkalin Tekli", "Şarj Cihazı USB-C 25W", "Powerbank 10000mAh",
    "Klavye USB Mekanik Türkçe", "Mouse Optik USB Sessiz", "HDMI Kablo 1.5m 4K",
    "Ethernet Kablo CAT6 5m", "USB-A 3.0 Uzatma 1.5m", "Kulaklık Bluetooth TWS",
    "Termos 1L Paslanmaz Çelik", "Masa Lambası LED Ayarlı", "Masaüstü Fan USB 15cm",
    "El Feneri LED 1000 Lümen", "Şerit Metre 5m", "Su Terazisi 60cm",
    "Maket Bıçağı 18mm Yedekli", "Hassas Terazi 5kg 1g", "Lokma Anahtar Seti 1/2\" 24'lü",
    "Allen Anahtar Seti 9'lu Uzun", "Tornavida Seti 12'li Profesyonel", "Cırcır Kolu 1/2\" 72 Diş",
]

CATEGORY_NAMES = [
    "Temizlik Malzemeleri", "Soğutma & HVAC", "Elektrik & Aydınlatma",
    "Hırdavat & El Aletleri", "Tesisat & Su Tesisatı", "Filtre & Conta",
    "Otomotiv Yedek Parça", "Kablo & Bağlantı", "Aşındırıcı & Yapıştırıcı",
    "Bakım Spreyleri", "İş Güvenliği", "Sarj & Pil",
]


class Command(BaseCommand):
    help = "Tum tenantlar icin Faker ile mock kategori, urun ve stok hareketi olusturur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--categories",
            type=int,
            default=10,
            help="Her tenant icin olusturulacak kategori sayisi (varsayilan: 10).",
        )
        parser.add_argument(
            "--products",
            type=int,
            default=40,
            help="Her tenant icin olusturulacak urun sayisi (varsayilan: 40).",
        )
        parser.add_argument(
            "--movements",
            type=int,
            default=60,
            help="Her tenant icin olusturulacak stok hareketi sayisi (varsayilan: 60).",
        )
        parser.add_argument(
            "--tenant-id",
            type=str,
            default=None,
            help="Sadece belirli bir tenant icin calistir.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Tekrarlanabilir uretim icin seed degeri.",
        )
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Mevcut urun/kategori/hareketleri once sil.",
        )

    def handle(self, *args, **options):
        n_categories = options["categories"]
        n_products = options["products"]
        n_movements = options["movements"]
        tenant_id = options["tenant_id"]
        seed = options["seed"]
        wipe = options["wipe"]

        if n_categories < 0 or n_products < 0 or n_movements < 0:
            self.stderr.write(self.style.ERROR("Sayilar negatif olamaz."))
            return

        faker = Faker("tr_TR")
        if seed is not None:
            Faker.seed(seed)
            random.seed(seed)

        tenants_qs = Tenant.objects.all().order_by("name")
        if tenant_id:
            tenants_qs = tenants_qs.filter(id=tenant_id)

        if not tenants_qs.exists():
            self.stderr.write(self.style.ERROR("Hic tenant bulunamadi."))
            return

        total = {"categories": 0, "products": 0, "movements": 0}
        for tenant in tenants_qs:
            if wipe:
                deleted_movements, _ = StockMovement.objects.filter(tenant=tenant).delete()
                deleted_products, _ = Product.objects.filter(tenant=tenant).delete()
                deleted_categories, _ = ProductCategory.objects.filter(tenant=tenant).delete()
                self.stdout.write(self.style.WARNING(
                    f"{tenant.name} ({tenant.id}): temizlendi - "
                    f"{deleted_categories} kategori, {deleted_products} urun, {deleted_movements} hareket"
                ))

            counts = self._create_for_tenant(faker, tenant, n_categories, n_products, n_movements)
            for key, val in counts.items():
                total[key] += val
            self.stdout.write(self.style.SUCCESS(
                f"{tenant.name} ({tenant.id}): {counts['categories']} kategori, "
                f"{counts['products']} urun, {counts['movements']} stok hareketi olusturuldu"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Islem tamam. Toplam: {total['categories']} kategori, "
            f"{total['products']} urun, {total['movements']} stok hareketi"
        ))

    def _create_for_tenant(self, faker, tenant, n_categories, n_products, n_movements):
        counts = {"categories": 0, "products": 0, "movements": 0}

        with transaction.atomic():
            categories = self._create_categories(faker, tenant, n_categories)
            counts["categories"] = len(categories)

            if not categories:
                self.stdout.write(self.style.WARNING(
                    f"{tenant.name}: kategori olusturulamadi, urun/hareket atlandi."
                ))
                return counts

            technicians = list(
                User.objects.filter(tenant=tenant, user_type="technician", is_active=True)
            )
            if not technicians:
                self.stdout.write(self.style.WARNING(
                    f"{tenant.name}: aktif teknisyen yok, hareketler rastgele User atayacak."
                ))

            products = self._create_products(faker, tenant, categories, n_products)
            counts["products"] = len(products)

            if not products:
                return counts

            counts["movements"] = self._create_movements(
                faker, tenant, products, technicians, n_movements
            )

        return counts

    def _create_categories(self, faker, tenant, target):
        existing = set(
            ProductCategory.objects.filter(tenant=tenant)
            .values_list("name", flat=True)
        )
        chosen = [c for c in CATEGORY_NAMES if c not in existing]
        random.shuffle(chosen)
        to_create = chosen[:target]
        if len(to_create) < target:
            extra = target - len(to_create)
            for i in range(extra):
                candidate = f"{faker.word().capitalize()} {faker.word().capitalize()}"
                counter = 1
                base = candidate
                while candidate in existing or candidate in to_create:
                    candidate = f"{base} {counter}"
                    counter += 1
                to_create.append(candidate)

        created = []
        for name in to_create:
            created.append(ProductCategory.objects.create(tenant=tenant, name=name))
        return created

    def _create_products(self, faker, tenant, categories, target):
        existing_codes = set(
            Product.objects.filter(tenant=tenant)
            .exclude(code="")
            .values_list("code", flat=True)
        )
        used_names = set(
            Product.objects.filter(tenant=tenant)
            .values_list("name", flat=True)
        )

        created = []
        pool = list(PRODUCT_NAMES)
        random.shuffle(pool)

        attempts = 0
        max_attempts = target * 3
        for _ in range(target):
            if attempts >= max_attempts:
                break
            attempts += 1

            if pool:
                base_name = pool.pop()
            else:
                base_name = f"{faker.word().capitalize()} {faker.word().capitalize()} {random.randint(1, 999)}"

            if base_name in used_names:
                if not pool:
                    break
                continue
            used_names.add(base_name)

            category = random.choice(categories)
            price = round(random.uniform(15, 3500), 2)
            stock_quantity = random.randint(0, 200)
            description = faker.sentence(nb_words=8)

            code = f"200{random.randint(1000000000, 9999999999)}"
            while code in existing_codes:
                code = f"200{random.randint(1000000000, 9999999999)}"
            existing_codes.add(code)

            try:
                product = Product.objects.create(
                    tenant=tenant,
                    category=category,
                    name=base_name,
                    code=code,
                    description=description,
                    price=price,
                    stock_quantity=stock_quantity,
                    is_active=random.random() > 0.05,
                )
                created.append(product)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Urun olusturulamadi ({base_name}): {exc}"
                ))

        return created

    def _create_movements(self, faker, tenant, products, technicians, target):
        weights = [
            ("in", 30),
            ("out", 45),
            ("adjustment", 10),
            ("return", 15),
        ]
        types, w = zip(*weights)

        if not technicians:
            fallback = User.objects.filter(tenant=tenant).first()
            if not fallback:
                return 0
            technicians = [fallback]

        created_count = 0
        now = timezone.now()
        for _ in range(target):
            product = random.choice(products)
            technician = random.choice(technicians)
            mtype = random.choices(types, weights=w, k=1)[0]
            if mtype == "adjustment":
                qty = random.randint(1, 15)
            elif mtype == "out":
                qty = random.randint(1, min(20, max(1, product.stock_quantity)))
            else:
                qty = random.randint(1, 30)

            days_ago = random.randint(0, 60)
            minutes_ago = random.randint(0, 24 * 60)
            ts = now - timedelta(days=days_ago, minutes=minutes_ago)

            description_templates = {
                "in": [
                    "Tedarikci teslimati kabul edildi.",
                    "Depo yenileme siparisi geldi.",
                    "Aylik stok takviyesi yapildi.",
                ],
                "out": [
                    "Servis icin cikis yapildi.",
                    "Teknisyen sahaya urun verdi.",
                    "Musteriye yedek parca olarak cikti.",
                ],
                "adjustment": [
                    "Sayim farki duzeltildi.",
                    "Hasarli urun kaybi düsüldü.",
                    "Stok tutarsizligi giderildi.",
                ],
                "return": [
                    "Musteri iade etti.",
                    "Kullanilmayan malzeme depoya alindi.",
                    "Servisten iade gelen parca.",
                ],
            }
            description = random.choice(description_templates[mtype])

            try:
                movement = StockMovement(
                    tenant=tenant,
                    technician=technician,
                    product=product,
                    movement_type=mtype,
                    quantity=qty,
                    description=description,
                )
                movement.save()
                StockMovement.objects.filter(pk=movement.pk).update(created_at=ts)
                created_count += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"Stok hareketi olusturulamadi: {exc}"
                ))
        return created_count
