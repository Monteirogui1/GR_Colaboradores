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

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'inventory_db'),
        'USER': os.getenv('DB_USER', 'inventory_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 0,  # conexões persistentes — melhora performance
         # Timeout de conexão (segundos) — evita travamento se postgres cair
         'OPTIONS': {
            'connect_timeout': 10,
        },
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

# Limite de upload — agents chegam a ~150 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 300 * 1024 * 1024   # 300 MB (multipart fields em memória)
FILE_UPLOAD_MAX_MEMORY_SIZE = 300 * 1024 * 1024   # 300 MB (antes de escrever em disco)




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
RDP_SESSION_TOKEN_TTL     = 120    # segundos de TTL para token efêmero do navegador
RDP_DEFAULT_CONNECTION_MODE = "auto"  # auto|p2p_only|relay_only
RDP_DEFAULT_QUALITY         = "auto"  # auto|high|medium|low
RDP_REQUIRE_JUSTIFICATION   = True
RDP_SILENT_ACCESS_ONLY      = True
RDP_ENABLE_REVERSE_SIGNAL   = True
RDP_SIGNAL_WAIT_TIMEOUT     = 12
AGENT_IPC_PORT            = 7070   # porta IPC do agente
AGENT_WEBRTC_PORT         = 7071
RDP_TURN_CONFIG = {
    'host':        os.environ.get('TURN_HOST',        '192.168.100.247'),
    'port':        int(os.environ.get('TURN_PORT',        '3478')),
    'port_tls':    int(os.environ.get('TURN_PORT_TLS',    '5349')),
    'port_tcp443': int(os.environ.get('TURN_PORT_TCP443', '443')),
    'username':    os.environ.get('TURN_USER',        'rdp'),
    'credential':  os.environ.get('TURN_CREDENTIAL',  'rdp123'),
}

RDP_ALLOWED_ORIGINS = [
    'http://192.168.100.247:5002',
    'http://192.168.100.247',
]

# ==================== CELERY ====================
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'America/Sao_Paulo'

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Gatilhos por tempo — a cada 5 minutos
    'tickets-gatilhos-tempo': {
        'task': 'tickets.avaliar_gatilhos_tempo',
        'schedule': 300.0,  # 5 min
    },
    # Alertas de SLA — a cada 15 minutos
    'tickets-verificar-sla': {
        'task': 'tickets.verificar_sla',
        'schedule': 900.0,  # 15 min
    },
    # Processar e-mails — a cada 5 minutos
    'tickets-processar-emails': {
        'task': 'tickets.processar_emails',
        'schedule': 300.0,
    },
    # Fechar tickets resolvidos — todo dia às 02:00
    'tickets-fechar-resolvidos': {
        'task': 'tickets.fechar_tickets_resolvidos',
        'schedule': crontab(hour=2, minute=0),
        'kwargs': {'dias': 7},
    },
    # Pesquisa de satisfação — a cada hora
    'tickets-pesquisa-satisfacao': {
        'task': 'tickets.enviar_pesquisa_satisfacao',
        'schedule': crontab(minute=0),  # início de cada hora
        'kwargs': {'horas_apos_fechamento': 24},
    },
    # Limpar notificações antigas — domingo às 03:00
    'tickets-limpar-notificacoes': {
        'task': 'tickets.limpar_notificacoes',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),
        'kwargs': {'dias': 30},
    },
    # Machines status (já existia)
    'check-machines-status': {
        'task': 'apps.inventory.tasks.check_machines_status',
        'schedule': 300.0,
    },
}

CRON_ALTERNATIVA = """
# crontab -e
# Avaliar gatilhos e SLA a cada 5 min:
*/5 * * * * cd /path/to/project && python manage.py avaliar_gatilhos_tempo >> logs/gatilhos.log 2>&1
*/15 * * * * cd /path/to/project && python manage.py verificar_sla >> logs/sla.log 2>&1
*/5 * * * * cd /path/to/project && python manage.py process_ticket_emails --mark-read >> logs/emails.log 2>&1
0 2 * * * cd /path/to/project && python manage.py fechar_tickets_resolvidos >> logs/fechamento.log 2>&1
"""
