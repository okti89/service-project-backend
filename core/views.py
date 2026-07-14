from django.db.models import Q, Value
from django.db.models.functions import Replace
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsGlobalSearchManager
from customers.models import Customer
from products.models import Product
from services.models import Service
from technicians.models import Technician
from accounts.models import AccountDeletionRequest


class GlobalSearchView(APIView):
    permission_classes = [IsGlobalSearchManager]

    def get(self, request):
        query = request.query_params.get("q", "").strip()

        if len(query) < 2:
            return Response({
                "customers": [],
                "services": [],
                "technicians": [],
                "products": [],
                "total": 0
            })

        clean_query = (
            query.replace(" ", "")
            .replace("-", "")
            .replace(".", "")
            .replace("(", "")
            .replace(")", "")
        )

        # ---------------- CUSTOMERS ----------------
        customers = (
            Customer.objects.annotate(
                clean_phone=Replace("phone_number", Value(" "), Value(""))
            )
            .filter(
                Q(full_name__icontains=query)
                | Q(clean_phone__icontains=clean_query)
                | Q(email__icontains=query)
            )
            .only("id", "full_name", "phone_number", "email")
            .distinct()[:10]
        )

        customer_data = [
            {
                "id": str(c.id),
                "title": c.full_name,
                "subtitle": c.phone_number or c.email or "-",
                "type": "customer",
            }
            for c in customers
        ]

        # ---------------- SERVICES ----------------
        services = (
            Service.objects.annotate(
                clean_cust_phone=Replace("customer__phone_number", Value(" "), Value("")),
                clean_receipt=Replace("receipt_number", Value(" "), Value("")),
            )
            .filter(
                Q(receipt_number__icontains=query)
                | Q(clean_receipt__icontains=clean_query)
                | Q(customer__full_name__icontains=query)
                | Q(customer_full_name__icontains=query)
                | Q(clean_cust_phone__icontains=clean_query)
                | Q(device_type__name__icontains=query)
                | Q(device_brand__name__icontains=query)
                | Q(device_model__name__icontains=query)
                | Q(fault_description__icontains=query)
            )
            .select_related("customer", "device_type")
            .only(
                "id",
                "receipt_number",
                "customer__full_name",
                "customer_full_name",
                "device_type__name",
            )
            .distinct()[:10]
        )

        service_data = [
            {
                "id": str(s.id),
                "title": f"#{s.receipt_number} - {s.customer.full_name if s.customer else s.customer_full_name}",
                "subtitle": s.device_type.name if s.device_type else "Servis Kaydi",
                "type": "service",
            }
            for s in services
        ]

        # ---------------- TECHNICIANS ----------------
        technicians = (
            Technician.objects.annotate(
                clean_phone=Replace("user__phone_number", Value(" "), Value(""))
            )
            .filter(
                Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(user__email__icontains=query)
                | Q(clean_phone__icontains=clean_query)
            )
            .select_related("user")
            .only("id", "user__first_name", "user__last_name", "user__email")
            .distinct()[:10]
        )

        technician_data = [
            {
                "id": str(t.id),
                "title": f"{t.user.first_name} {t.user.last_name}".strip() or t.user.email,
                "subtitle": "Teknisyen",
                "type": "technician",
            }
            for t in technicians
        ]

        # ---------------- PRODUCTS ----------------
        products = (
            Product.objects.annotate(
                clean_code=Replace("code", Value(" "), Value(""))
            )
            .filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(clean_code__icontains=clean_query)
                | Q(description__icontains=query)
            )
            .only("id", "name", "code", "price")
            .distinct()[:10]
        )

        product_data = [
            {
                "id": str(p.id),
                "title": p.name,
                "subtitle": f"Kod: {p.code} - {p.price} TL",
                "type": "product",
            }
            for p in products
        ]

        total = (
            len(customer_data)
            + len(service_data)
            + len(technician_data)
            + len(product_data)
        )

        return Response({
            "customers": customer_data,
            "services": service_data,
            "technicians": technician_data,
            "products": product_data,
            "total": total,
        })

def privacy_policy(request):
    html = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Servis Asistanı Gizlilik Politikası</title>
<style>body{margin:0;background:#f8fafc;color:#172033;font:16px/1.65 Arial,sans-serif}.page{max-width:780px;margin:40px auto;padding:36px;background:#fff;border-radius:18px;box-shadow:0 8px 30px rgba(15,23,42,.08)}h1{font-size:28px}h2{font-size:20px;margin-top:30px}p,li{color:#475569}small{color:#64748b}@media(max-width:640px){.page{margin:0;border-radius:0;padding:24px}}</style></head>
<body><main class="page"><h1>Gizlilik Politikası</h1><small>Son güncelleme: 13 Temmuz 2026</small>
<p>Servis Asistanı, işletmelerin servis, müşteri ve saha operasyonlarını yönetmesi için sunulan kurumsal bir uygulamadır.</p>
<h2>Toplanan veriler</h2><p>Hesap bilgileri (ad, e-posta, telefon), müşteri ve servis kayıtları, adres bilgileri, servis fotoğrafları, imza, tahsilat kayıtları, cihaz ve bildirim kimlikleri ile aktif vardiyada teknisyen konumu işlenebilir.</p>
<h2>İşleme amaçları</h2><p>Veriler; kullanıcı hesabını yönetmek, servis iş emirlerini yürütmek, müşteriyle iletişimi sağlamak, servis belgelerini oluşturmak, aktif saha görevlerini takip etmek ve bildirim göndermek için kullanılır. Veriler reklam amacıyla satılmaz veya izleme amacıyla kullanılmaz.</p>
<h2>Konum verisi</h2><p>Arka plan konumu yalnızca teknisyen aktif vardiya takibini başlattığında ve açık rıza ile işletilir. Konum, görev yönetimi ve yetkili yöneticilerin canlı takip ekranı için sunucuya aktarılır. Kullanıcı, cihaz ayarlarından konum iznini her zaman kapatabilir.</p>
<h2>Hizmet sağlayıcılar ve güvenlik</h2><p>Bildirim, harita ve altyapı hizmetleri için Expo, Firebase ve Google Maps gibi hizmet sağlayıcılar kullanılabilir. Veri aktarımı üretim ortamında HTTPS üzerinden yapılır.</p>
<h2>Saklama ve silme</h2><p>Kullanıcı hesabı, uygulama içindeki Profil &gt; Hesabımı Sil adımından silinebilir. Uygulamaya erişemiyorsanız <a href="/delete-account/">hesap silme talep formunu</a> kullanabilirsiniz. Hesap silindiğinde kullanıcıya bağlı oturum, cihaz, konum ve profil verileri kaldırılır. Yasal veya muhasebesel saklama yükümlülüğü bulunan kurumsal servis kayıtları, kullanıcı kimliğiyle bağlantısı kaldırılarak saklanabilir.</p>
<h2>İletişim</h2><p>Gizlilik talepleriniz için uygulamadaki Ayarlar &gt; E-posta ile Geri Bildirim alanından destek ekibiyle iletişime geçebilirsiniz.</p></main></body></html>"""
    return HttpResponse(html, content_type="text/html; charset=utf-8")

def account_deletion(request):
    submitted = False
    error = ""

    if request.method == "POST":
        email = str(request.POST.get("email", "")).strip().lower()
        note = str(request.POST.get("note", "")).strip()
        try:
            validate_email(email)
        except ValidationError:
            error = "Lütfen geçerli bir e-posta adresi girin."
        else:
            existing_request = AccountDeletionRequest.objects.filter(
                email__iexact=email,
                status=AccountDeletionRequest.STATUS_PENDING,
            ).first()
            if existing_request:
                if note and not existing_request.note:
                    existing_request.note = note
                    existing_request.save(update_fields=["note"])
            else:
                AccountDeletionRequest.objects.create(email=email, note=note)
            submitted = True

    return render(
        request,
        "core/account_deletion.html",
        {"submitted": submitted, "error": error},
    )