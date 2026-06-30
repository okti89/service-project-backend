from PIL import Image
from io import BytesIO
import os
from django.core.files import File
from datetime import datetime

def process_product_image(image_field, max_size=(1200, 1200), quality=85):
    """Görüntüyü işleyip WebP formatına dönüştüren yardımcı fonksiyon"""
    if not image_field:
        return None
        
    img = Image.open(image_field)
    
    # RGBA görüntüleri RGB'ye dönüştür
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, 'white')
        background.paste(img, mask=img.split()[-1])
        img = background

    # Görüntüyü yeniden boyutlandır (sadece daha büyükse)
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    # WebP olarak kaydet
    buffer = BytesIO()
    img.save(buffer, format='WebP', quality=quality, method=6, lossless=False)
    buffer.seek(0)
                
    # Yeni dosya adı oluştur
    name = os.path.splitext(image_field.name)[0]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    new_name = f"{name}_{timestamp}.webp"                
    # İşlenmiş dosyayı görüntü alanına geri ata
    return File(buffer, name=new_name)


def process_image(image_field, max_size=(1200, 1200), quality=85):
    return process_product_image(
        image_field=image_field,
        max_size=max_size,
        quality=quality,
    )

