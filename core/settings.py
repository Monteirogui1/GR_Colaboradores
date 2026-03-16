import os
from pathlib import Path

from django.urls import reverse_lazy
import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Carrega o .env da raiz do projeto
load_dotenv(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-rg(j=r4br+!f!43dn2s(w_(np700%1nx#pw(aq+(^7t@@sj&#9'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = ['*']

LOGIN_URL = reverse_lazy('authentication:login')  # Página de login
LOGIN_REDIRECT_URL = reverse_lazy('home:dashboard')       # Redireciona para a homepage após login
LOGOUT_REDIRECT_URL = reverse_lazy('authentication:login')  # Redireciona para login após logout

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_cryptography',
    'rest_framework',
    'drf_spectacular',
    'import_export',
    'apps',
    'apps.authentication',
    'apps.home',
    'apps.inventory',
    'apps.shared',
    'apps.categorias',
    'apps.marcas',
    'apps.fornecedor',
    'apps.ativos',
    'apps.auditoria',
    'apps.tickets',
    'apps.produtos',
    'apps.movimentacao',
    'apps.notificacao',
    'apps.rdp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

# Assets Management
ASSETS_ROOT = os.getenv('ASSETS_ROOT', '/static/assets')

TEMPLATE_DIR = os.path.join(APPS_DIR, "apps/templates")  # ROOT dir for templates
STATIC_DIR = os.path.join(APPS_DIR, "apps/static")  # ROOT dir for Static


TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATE_DIR, STATIC_DIR],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

AUTH_USER_MODEL = 'authentication.User'

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),  # Opcional: diretório para arquivos estáticos do projeto
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema'
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Gestão de TI',
    'DESCRIPTION': 'Sem Descrição',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}


MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = 'media/'




# Configuração para recebimento de tickets por e-mail
TICKET_EMAIL_CONFIG = {
    # Servidor IMAP
    'IMAP_SERVER': 'imap.gmail.com',  # Gmail
    # 'IMAP_SERVER': 'outlook.office365.com',  # Outlook
    # 'IMAP_SERVER': 'imap.mail.yahoo.com',  # Yahoo
    'IMAP_PORT': 993,

    # Credenciais
    'EMAIL_USER': 'suporte@suaempresa.com',
    'EMAIL_PASSWORD': 'sua_senha_ou_app_password',

    # Configurações de processamento
    'AUTO_CREATE_USERS': True,  # Criar usuários automaticamente
    'PROCESS_ATTACHMENTS': True,  # Processar anexos
    'DEFAULT_CLIENTE_ID': 1,  # ID do cliente padrão (opcional)

    # NOTIFICAÇÕES
    'SEND_CONFIRMATION': True,  # Enviar confirmação ao criar ticket
    'NOTIFY_AGENT_ON_REPLY': True,  # Notificar técnico quando cliente responde
    'NOTIFY_CLIENT_ON_REPLY': True,  # Notificar cliente quando técnico responde

    # URL DO SISTEMA
    'SITE_URL': 'https://suporte.empresa.com',  # URL base para links
}

# E-mail de saída (para enviar notificações)
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'suporte@empresa.com'
EMAIL_HOST_PASSWORD = 'senha_ou_app_password'
DEFAULT_FROM_EMAIL = 'Suporte <suporte@empresa.com>'



# CELERY_BEAT_SCHEDULE = {
#     'check-machines-status': {
#         'task': 'apps.inventory.tasks.check_machines_status',
#         'schedule': 300.0,  # A cada 5 minutos
#     },
# }



LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'errors_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'errors.log',
            'maxBytes': 10 * 1024 * 1024,   # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'security.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['errors_file'],
            'level': 'ERROR',
            'propagate': True,
        },
        'django.security': {
            'handlers': ['security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}


SPECTACULAR_SETTINGS['SERVE_INCLUDE_SCHEMA'] = False

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '120/minute',
    },
}

AXES_FAILURE_LIMIT = 5        # bloqueia após 5 tentativas erradas
AXES_COOLOFF_TIME  = 1        # 1 hora de bloqueio
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_RESET_ON_SUCCESS = True

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

RDP_SESSION_TIMEOUT       = 3600   # segundos de TTL da sessão
RDP_MAX_SESSIONS_PER_USER = 3      # máximo de sessões simultâneas
RDP_ALLOWED_ORIGINS       = ['https://seudominio.com']  # lista branca de origens
AGENT_IPC_PORT            = 7070   # porta IPC do agente
AGENT_WEBRTC_PORT         = 7071
RDP_TURN_CONFIG = {
    'host':       os.environ.get('TURN_HOST',       '192.168.100.247'),
    'port':       int(os.environ.get('TURN_PORT',   '3478')),
    'username':   os.environ.get('TURN_USER',       'rdp'),
    'credential': os.environ.get('TURN_CREDENTIAL', 'rdp123'),
}