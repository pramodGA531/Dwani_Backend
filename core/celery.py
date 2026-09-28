import os
from celery import Celery

# Auto-select settings based on PRODUCTION env var (same logic as manage.py)
default_settings = (
    'core.settings.production'
    if os.environ.get('PRODUCTION') == '1'
    else 'core.settings.development'
)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)

app = Celery('core')

# Load celery config from Django settings using CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()
