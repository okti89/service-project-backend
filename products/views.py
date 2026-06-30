from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import ProductCategory, Product, StockMovement
from .serializers import ProductCategorySerializer, ProductSerializer, StockMovementSerializer
from .permissions import IsInventoryManager


def product_request_data(request):
    data = request.data.copy()
    if request.FILES:
        for key, file_obj in request.FILES.items():
            data[key] = file_obj
    return data

class ProductCategoryListCreateView(APIView):
    permission_classes = [IsInventoryManager]

    def get(self, request):
        qs = ProductCategory.objects.filter(tenant=request.user.tenant)
        return Response(ProductCategorySerializer(qs, many=True).data)

    def post(self, request):
        serializer = ProductCategorySerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(tenant=request.user.tenant)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProductCategoryDetailView(APIView):
    permission_classes = [IsInventoryManager]

    def get_object(self, pk):
        return get_object_or_404(ProductCategory, pk=pk, tenant=self.request.user.tenant)

    def get(self, request, pk):
        return Response(ProductCategorySerializer(self.get_object(pk)).data)

    def patch(self, request, pk):
        obj = self.get_object(pk)
        serializer = ProductCategorySerializer(obj, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save(tenant=request.user.tenant)
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response({"detail": "Silindi"})

class ProductListCreateView(APIView):
    permission_classes = [IsInventoryManager]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        qs = Product.objects.filter(tenant=request.user.tenant).select_related('category')
        return Response(ProductSerializer(qs, many=True).data)

    def post(self, request):
        data = product_request_data(request)
        serializer = ProductSerializer(data=data, context={"request": request})

        if serializer.is_valid():
            serializer.save(tenant=request.user.tenant)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProductDetailView(APIView):
    permission_classes = [IsInventoryManager]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_object(self, pk):
        return get_object_or_404(Product, pk=pk, tenant=self.request.user.tenant)

    def get(self, request, pk):
        obj = self.get_object(pk)
        serializer = ProductSerializer(obj, context={"request": request})
        return Response(serializer.data)

    def patch(self, request, pk):
        obj = self.get_object(pk)
        data = product_request_data(request)
        serializer = ProductSerializer(obj, data=data, partial=True, context={"request": request})

        if serializer.is_valid():
            serializer.save(tenant=request.user.tenant)
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response({"detail": "Silindi"})

class StockMovementListCreateView(APIView):
    permission_classes = [IsInventoryManager]

    def get(self, request):
        qs = StockMovement.objects.filter(tenant=request.user.tenant).select_related('product', 'technician')

        if request.query_params.get('product'):
            qs = qs.filter(product_id=request.query_params["product"])

        if request.query_params.get('technician'):
            qs = qs.filter(technician_id=request.query_params["technician"])

        return Response(StockMovementSerializer(qs, many=True).data)

    def post(self, request):
        serializer = StockMovementSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            serializer.save(tenant=request.user.tenant)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StockMovementDetailView(APIView):
    permission_classes = [IsInventoryManager]

    def get_object(self, pk):
        return get_object_or_404(StockMovement, pk=pk, tenant=self.request.user.tenant)

    def get(self, request, pk):
        return Response(StockMovementSerializer(self.get_object(pk)).data)

    def delete(self, request, pk):
        # SADECE SİL — stok logic model/signal tarafında
        self.get_object(pk).delete()
        return Response({"detail": "Silindi"}, status=status.HTTP_200_OK)
