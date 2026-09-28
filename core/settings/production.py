from .base import *

DEBUG = False

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='dwani.gradarena.in,localhost,127.0.0.1').split(',')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='dwani_db'),
        'USER': config('DB_USER', default='dwani_user'),
        'PASSWORD': config('DB_PASSWORD', default='your_strong_password'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default=5432, cast=int),
    }
}

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='https://dwani.gradarena.in').split(',')
# Add this line at the very bottom
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='https://dwani.gradarena.in,https://dwanibackend.gradarena.in').split(',')
