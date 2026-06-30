import os
from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image
from django.core.files import File
import hashlib

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from config.models import CompanyConfig

def process_image(image_field, max_size=(1200, 1200), quality=92):
    if not image_field:
        return None

    img = Image.open(image_field)

    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.split()[-1])
        img = background

    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    buffer = BytesIO()

    img.save(
        buffer,
        format="WEBP",
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




def _resolve_panel_url(tenant=None):
    if tenant:
        config = CompanyConfig.objects.filter(tenant=tenant).only("panel_url").first()
        panel_url = (getattr(config, "panel_url", None) or "").strip() if config else ""
        if panel_url:
            return panel_url
    return getattr(settings, "FRONTEND_URL",)

def send_password_reset_email(email, code, full_name):
    """
    Sends a password reset email to the user with the provided code.
    """
    subject = 'Parola Sıfırlama İsteği'
    context = {
        'code': code,
        'full_name': full_name
    }
    html_content = render_to_string('password_reset_email.html', context)
    text_content = strip_tags(html_content)
    email_from = f"Servis Takip Sistemi <{settings.EMAIL_HOST_USER}>"
    recipient_list = [email]
    
    msg = EmailMultiAlternatives(subject, text_content, email_from, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_approval_email(email, full_name):
    """
    Kullanıcıya hesabının onaylandığına dair e-posta gönderir.
    """
    subject = 'Hesabınız Onaylandı'
    context = {
        'full_name': full_name,
    }
    html_content = render_to_string('user_approved_email.html', context)
    text_content = strip_tags(html_content)
    email_from = f"Servis Takip Sistemi <{settings.EMAIL_HOST_USER}>"
    recipient_list = [email]
    
    msg = EmailMultiAlternatives(subject, text_content, email_from, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_rejected_email(email, full_name):
    """
    Kullanıcıya hesabının onaylanmadığına dair e-posta gönderir.
    """
    subject = 'Hesabınız Onaylanmadı'
    context = {
        'full_name': full_name,
    }
    html_content = render_to_string('user_rejected_email.html', context)
    text_content = strip_tags(html_content)
    email_from = f"Servis Takip Sistemi <{settings.EMAIL_HOST_USER}>"
    recipient_list = [email]
    
    msg = EmailMultiAlternatives(subject, text_content, email_from, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    
def send_admin_registration_email(admin_user, user_full_name, user_email):
    """
    Adminlere yeni bir kullanıcının kayıt olduğuna dair e-posta gönderir.
    """
    subject = 'Yeni Kullanıcı Kaydı Bildirimi'
    from django.utils import timezone
    context = {
        'user_full_name': user_full_name,
        'user_email': user_email,
        'date_joined': timezone.now().strftime("%d.%m.%Y %H:%M"),
        'admin_url': _resolve_panel_url(getattr(admin_user, "tenant", None)),
    }
    html_content = render_to_string('new_user_admin_email.html', context)
    text_content = strip_tags(html_content)
    email_from = f"Servis Takip Sistemi <{settings.EMAIL_HOST_USER}>"
    recipient_list = [admin_user.email]
    
    msg = EmailMultiAlternatives(subject, text_content, email_from, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_admin_pending_approval_reminder_email(admin_user, user_full_name, user_email, waiting_label):
    """
    Adminlere kullanici onay bekleme hatirlatmasi e-postasi gonderir.
    """
    subject = 'Onay Bekleyen Kullanici Hatirlatmasi'
    from django.utils import timezone
    context = {
        'user_full_name': user_full_name,
        'user_email': user_email,
        'waiting_label': waiting_label,
        'date_now': timezone.now().strftime("%d.%m.%Y %H:%M"),
        'admin_url': _resolve_panel_url(getattr(admin_user, "tenant", None)),
    }
    html_content = render_to_string('pending_user_admin_reminder_email.html', context)
    text_content = strip_tags(html_content)
    email_from = f"Servis Takip Sistemi <{settings.EMAIL_HOST_USER}>"
    recipient_list = [admin_user.email]

    msg = EmailMultiAlternatives(subject, text_content, email_from, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    msg.send()

