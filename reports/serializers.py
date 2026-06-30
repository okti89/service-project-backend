from rest_framework import serializers

class GeneralPerformanceSerializer(serializers.Serializer):
    gross_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    total_reversal = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    collected_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    outstanding_receivables = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    total_overdue_receivables = serializers.IntegerField(required=False)
    net_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_expenses = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_profit = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_services = serializers.IntegerField()
    total_customers = serializers.IntegerField()
    total_technicians = serializers.IntegerField()
    total_completed_services = serializers.IntegerField()
    total_pending_services = serializers.IntegerField()
    total_cancelled_services = serializers.IntegerField()
    total_completed_services_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    total_pending_services_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    total_cancelled_services_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    
class TechnicianPerformanceSerializer(serializers.Serializer):
    technician_id = serializers.UUIDField(allow_null=True)
    technician_name = serializers.CharField(max_length=200)
    completed_services_count = serializers.IntegerField()
    total_revenue_generated = serializers.DecimalField(max_digits=15, decimal_places=2)
