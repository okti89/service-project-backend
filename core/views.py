from django.db.models import Q, Value
from django.db.models.functions import Replace
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsGlobalSearchManager
from customers.models import Customer
from products.models import Product
from services.models import Service
from technicians.models import Technician


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