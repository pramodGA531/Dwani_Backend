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

# Production Email Settings (Real SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False          # Never set both TLS and SSL to True
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
EMAIL_TIMEOUT = 10             # Don't hang forever on SMTP errors
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='dwani.gradarena@gmail.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL   # Used by Django error emails

FRONTEND_URL = config('FRONTEND_URL', default='https://dwani.gradarena.in')

