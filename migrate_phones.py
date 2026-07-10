import os
import django
import sys

# Setup django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from customers.models import Customer
from services.models import Service

def normalize_to_tr_format(phone):
    if not phone:
        return None
    digits = ''.join(ch for ch in str(phone) if ch.isdigit())
    if not digits:
        return None
        
    if digits.startswith('90') and len(digits) > 10:
        digits = digits[2:]
    elif digits.startswith('090') and len(digits) > 11:
        digits = digits[3:]
        
    if not digits.startswith('0') and len(digits) == 10:
        digits = '0' + digits
    return digits

def run():
    print("Starting phone number migration...")
    
    # 1. Migrate Customer phone numbers
    customers = Customer.objects.all()
    updated_customers = 0
    for customer in customers:
        if customer.phone_number:
            normalized = normalize_to_tr_format(customer.phone_number)
            if normalized and customer.phone_number != normalized:
                print(f"Customer: {customer.full_name} | {customer.phone_number} -> {normalized}")
                customer.phone_number = normalized
                customer.save(update_fields=['phone_number'])
                updated_customers += 1
                
    # 2. Migrate Service customer_phone numbers
    services = Service.objects.all()
    updated_services = 0
    for service in services:
        if service.customer_phone:
            normalized = normalize_to_tr_format(service.customer_phone)
            if normalized and service.customer_phone != normalized:
                print(f"Service ID: {service.id} | {service.customer_phone} -> {normalized}")
                service.customer_phone = normalized
                service.save(update_fields=['customer_phone'])
                updated_services += 1
                
    print(f"Completed! Updated {updated_customers} customers and {updated_services} services.")

if __name__ == "__main__":
    run()
