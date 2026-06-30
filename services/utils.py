from PIL import Image
from io import BytesIO
import os
from django.core.files import File
from datetime import datetime
import hashlib

def process_service_image(image_field, image_name=None, max_size=(1200, 1200), quality=92):
    """Görüntüyü işleyip WebP formatına dönüştürür"""
    if not image_field:
        return None

    img = Image.open(image_field)

    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, 'white')
        background.paste(img, mask=img.split()[-1])
        img = background
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    buffer = BytesIO()

    img.save(
        buffer,
        format='WEBP',
        quality=quality,
        method=6,
        lossless=False
    )

    buffer.seek(0)

    name = os.path.splitext(image_field.name)[0]
    hash_name = hashlib.md5(name.encode()).hexdigest()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    new_name = f"{hash_name}_{timestamp}.webp"

    return File(buffer, name=new_name)
