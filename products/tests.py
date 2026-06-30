from io import BytesIO
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User
from products.models import Product, ProductCategory, StockMovement
from products.permissions import IsInventoryManager
from products.serializers import StockMovementSerializer
from tenants.models import Tenant


def make_test_image(name="test.png"):
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    MEDIA_ROOT=tempfile.gettempdir(),
)
class ProductBehaviorTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
        self.other_tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")

        self.user = User.objects.create_user(
            email="user@example.com",
            password="test123",
            tenant=self.tenant,
            user_type="technician",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="test123",
            tenant=self.other_tenant,
            user_type="technician",
        )

        self.category = ProductCategory.objects.create(
            tenant=self.tenant,
            name="Category A",
        )
        self.product = Product.objects.create(
            tenant=self.tenant,
            category=self.category,
            name="Product A",
            stock_quantity=10,
            price="100.00",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_stock_movement_delete_restores_product_stock_and_status(self):
        movement = StockMovement.objects.create(
            tenant=self.tenant,
            technician=self.user,
            product=self.product,
            movement_type="out",
            quantity=3,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 7)
        self.assertEqual(self.product.status, "in_stock")

        movement.delete()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.status, "in_stock")

    def test_product_save_does_not_reprocess_image_when_image_is_unchanged(self):
        image = make_test_image()

        with patch("products.models.process_image", side_effect=lambda file_obj: file_obj) as mock_process:
            product = Product.objects.create(
                tenant=self.tenant,
                category=self.category,
                name="Image Product",
                stock_quantity=2,
                image=image,
            )
            self.assertEqual(mock_process.call_count, 1)

        with patch("products.models.process_image", side_effect=lambda file_obj: file_obj) as mock_process:
            product.name = "Renamed Product"
            product.save()
            self.assertEqual(mock_process.call_count, 0)

    def test_stock_movement_serializer_rejects_cross_tenant_technician(self):
        request = self.factory.post("/api/products/stock-movements/")
        request.user = self.user

        serializer = StockMovementSerializer(
            data={
                "product_id": str(self.product.id),
                "technician": self.other_user.id,
                "movement_type": "out",
                "quantity": 1,
            },
            context={"request": request},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("technician", serializer.errors)

    def test_inventory_permission_only_requires_authentication(self):
        permission = IsInventoryManager()

        anonymous_request = self.factory.get("/api/products/products/")
        anonymous_request.user = None
        self.assertFalse(permission.has_permission(anonymous_request, None))

        authenticated_request = self.factory.get("/api/products/products/")
        authenticated_request.user = self.user
        self.assertTrue(permission.has_permission(authenticated_request, None))

    def test_product_create_accepts_multipart_image_upload(self):
        response = self.client.post(
            "/api/products/products/",
            {
                "category_id": str(self.category.id),
                "name": "Uploaded Product",
                "price": "125.50",
                "stock_quantity": "4",
                "is_active": "true",
                "image": make_test_image("create.png"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(name="Uploaded Product")
        self.assertTrue(product.image)

    def test_product_update_accepts_multipart_image_upload(self):
        response = self.client.patch(
            f"/api/products/products/{self.product.id}/",
            {
                "name": "Product With Image",
                "image": make_test_image("update.png"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Product With Image")
        self.assertTrue(self.product.image)
