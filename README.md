# GR-Colaboradores

Sistema web de Gestao de TI desenvolvido em Django para operacao multi-cliente. O projeto centraliza inventario de maquinas Windows, atendimento de tickets com SLA, gestao de ativos fisicos, catalogo de produtos, movimentacao de estoque, auditoria patrimonial, notificacoes e acesso remoto via WebRTC/RDP.

## Sumario

- [Visao Geral](#visao-geral)
- [Principais Recursos](#principais-recursos)
- [Tecnologias](#tecnologias)
- [Arquitetura](#arquitetura)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Pre-requisitos](#pre-requisitos)
- [Configuracao Local](#configuracao-local)
- [Variaveis de Ambiente](#variaveis-de-ambiente)
- [Banco de Dados](#banco-de-dados)
- [Comandos Uteis](#comandos-uteis)
- [APIs e Rotas](#apis-e-rotas)
- [Sistema de Inventario e Agente Windows](#sistema-de-inventario-e-agente-windows)
- [Sistema de Tickets e SLA](#sistema-de-tickets-e-sla)
- [Acesso Remoto RDP/WebRTC](#acesso-remoto-rdpwebrtc)
- [Tarefas em Segundo Plano](#tarefas-em-segundo-plano)
- [Testes](#testes)
- [Deploy](#deploy)
- [Seguranca](#seguranca)
- [Troubleshooting](#troubleshooting)

## Visao Geral

O GR-Colaboradores e uma aplicacao Django monolitica, organizada por apps de dominio dentro de `apps/`, com configuracao principal em `core/settings.py`.

O sistema usa portugues do Brasil como idioma padrao (`pt-br`) e timezone `America/Sao_Paulo`.

## Principais Recursos

- Autenticacao com modelo customizado de usuario.
- Gestao multi-cliente com isolamento por `Cliente` nos apps corporativos.
- Dashboard operacional.
- Inventario de maquinas Windows com agente, check-in, status online/offline, grupos, sites bloqueados e logs de atividade.
- Distribuicao e atualizacao de versoes do agente Windows.
- Execucao remota de comandos em maquinas inventariadas.
- Sistema de tickets com categorias, urgencias, status, anexos, acoes, macros, equipes e relatorios.
- SLA com regras por contrato, horarios de atendimento e feriados.
- Automacoes de tickets por gatilhos configuraveis em JSON.
- Criacao de tickets por e-mail via IMAP.
- Gestao de ativos fisicos, localizacao, status, historico e anexos.
- Catalogo de produtos, variacoes, campos dinamicos, unidades e parametros de estoque.
- Movimentacao de estoque, lotes, ajustes, historico e importacao de NFe.
- Auditoria de ativos com execucao, historico e relatorio.
- Notificacoes in-app.
- Acesso remoto via WebRTC/RDP com sinalizacao via API.
- API documentada com drf-spectacular em Swagger e Redoc.

## Tecnologias

- Python
- Django 5.2
- Django REST Framework
- drf-spectacular
- PostgreSQL
- WhiteNoise
- django-import-export
- django-cryptography
- python-dotenv
- Celery e Redis para rotinas agendadas, quando habilitados no ambiente
- Bibliotecas Windows para agente, automacao e empacotamento: `pywin32`, `WMI`, `psutil`, `pyinstaller`, `pystray`, `pyautogui`, entre outras

## Arquitetura

### Configuracao Principal

- `core/settings.py`: configuracoes Django, banco, DRF, e-mail, Celery Beat, RDP/TURN, logs e arquivos estaticos.
- `core/urls.py`: rotas raiz da aplicacao.
- `core/wsgi.py` e `core/asgi.py`: entrypoints para deploy.
- `manage.py`: comandos administrativos do Django.

### Multi-Tenancy

A base multi-cliente fica em `apps/shared/models.py`:

```python
class ClienteBaseModel(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)

    class Meta:
        abstract = True
```

Apps que usam esse padrao devem filtrar dados por `cliente` em views, queries, relatorios e APIs:

- `ativos`
- `produtos`
- `movimentacao`
- `notificacao`
- `fornecedor`
- `categorias`
- `marcas`
- `auditoria`

Observacoes:

- `authentication.User` possui FK para `Cliente`.
- Usuarios `is_staff=True` representam agentes/tecnicos.
- Usuarios sem staff representam clientes finais.
- `inventory` nao e tenant-scoped atualmente; maquinas sao globais.
- `tickets` possui modelos proprios de categoria e urgencia, separados de `apps.categorias`.

## Estrutura do Projeto

```text
GR-Colaboradores/
├── apps/
│   ├── authentication/   # Login, logout e usuarios
│   ├── home/             # Dashboard
│   ├── inventory/        # Inventario, agentes Windows, tokens e APIs
│   ├── tickets/          # Tickets, SLA, automacoes, e-mail e relatorios
│   ├── ativos/           # Ativos fisicos
│   ├── produtos/         # Catalogo de produtos
│   ├── movimentacao/     # Estoque, lotes e movimentacoes
│   ├── auditoria/        # Auditoria patrimonial
│   ├── rdp/              # Sinalizacao WebRTC/RDP
│   ├── shared/           # Cliente e base multi-tenant
│   ├── categorias/       # Categorias tenant-scoped
│   ├── marcas/           # Marcas tenant-scoped
│   ├── fornecedor/       # Fornecedores tenant-scoped
│   ├── notificacao/      # Notificacoes tenant-scoped
│   ├── templates/        # Templates HTML
│   └── static/           # CSS, JS e assets
├── core/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── logs/
├── media/
├── manage.py
├── requirements.txt
└── README.md
```

## Pre-requisitos

- Python compativel com Django 5.2.
- PostgreSQL em execucao.
- Git.
- Redis, caso use Celery/rotinas agendadas.
- Windows, caso compile ou execute o agente localmente.

## Configuracao Local

1. Clone o repositorio e entre na pasta:

```bash
git clone <url-do-repositorio>
cd GR-Colaboradores
```

2. Crie e ative um ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

No Git Bash para Windows:

```bash
source .venv/Scripts/activate
```

3. Instale as dependencias:

```bash
pip install -r requirements.txt
```

4. Configure o arquivo `.env` na raiz do projeto:

```env
DB_NAME=inventory_db
DB_USER=inventory_user
DB_PASSWORD=sua_senha
DB_HOST=localhost
DB_PORT=5432

TURN_HOST=192.168.100.247
TURN_PORT=3478
TURN_PORT_TLS=5349
TURN_PORT_TCP443=443
TURN_USER=rdp
TURN_CREDENTIAL=rdp123

AGENT_BOOTSTRAP_NSSM_URL=
AGENT_BOOTSTRAP_NSSM_SHA256=
AGENT_BOOTSTRAP_RUNTIME_LEGACY_URL=
AGENT_BOOTSTRAP_RUNTIME_LEGACY_SHA256=
AGENT_BOOTSTRAP_RUNTIME_BALANCED_URL=
AGENT_BOOTSTRAP_RUNTIME_BALANCED_SHA256=
AGENT_BOOTSTRAP_RUNTIME_PERFORMANCE_URL=
AGENT_BOOTSTRAP_RUNTIME_PERFORMANCE_SHA256=
```

5. Aplique as migracoes:

```bash
python manage.py migrate
```

6. Crie um superusuario:

```bash
python manage.py createsuperuser
```

7. Execute o servidor de desenvolvimento:

```bash
python manage.py runserver
```

8. Acesse:

```text
http://127.0.0.1:8000/
```

## Variaveis de Ambiente

O projeto carrega `.env` pela raiz usando `python-dotenv`.

### Banco de Dados

| Variavel | Padrao | Descricao |
|---|---:|---|
| `DB_NAME` | `inventory_db` | Nome do banco PostgreSQL |
| `DB_USER` | `inventory_user` | Usuario do PostgreSQL |
| `DB_PASSWORD` | vazio | Senha do PostgreSQL |
| `DB_HOST` | `localhost` | Host do PostgreSQL |
| `DB_PORT` | `5432` | Porta do PostgreSQL |

### RDP/TURN

| Variavel | Padrao | Descricao |
|---|---:|---|
| `TURN_HOST` | `192.168.100.247` | Host do servidor TURN |
| `TURN_PORT` | `3478` | Porta UDP/TCP padrao |
| `TURN_PORT_TLS` | `5349` | Porta TLS |
| `TURN_PORT_TCP443` | `443` | Porta TCP alternativa |
| `TURN_USER` | `rdp` | Usuario TURN |
| `TURN_CREDENTIAL` | `rdp123` | Credencial TURN |

### Bootstrap do Agente

| Variavel | Descricao |
|---|---|
| `AGENT_BOOTSTRAP_NSSM_URL` | URL do binario NSSM para instalacao do servico |
| `AGENT_BOOTSTRAP_NSSM_SHA256` | SHA-256 esperado do NSSM |
| `AGENT_BOOTSTRAP_RUNTIME_LEGACY_URL` | Runtime legado do agente |
| `AGENT_BOOTSTRAP_RUNTIME_LEGACY_SHA256` | SHA-256 do runtime legado |
| `AGENT_BOOTSTRAP_RUNTIME_BALANCED_URL` | Runtime balanceado do agente |
| `AGENT_BOOTSTRAP_RUNTIME_BALANCED_SHA256` | SHA-256 do runtime balanceado |
| `AGENT_BOOTSTRAP_RUNTIME_PERFORMANCE_URL` | Runtime de performance do agente |
| `AGENT_BOOTSTRAP_RUNTIME_PERFORMANCE_SHA256` | SHA-256 do runtime de performance |

## Banco de Dados

A configuracao ativa usa PostgreSQL:

```python
ENGINE = django.db.backends.postgresql
```

Exemplo de criacao manual do banco:

```sql
CREATE DATABASE inventory_db;
CREATE USER inventory_user WITH PASSWORD 'sua_senha';
GRANT ALL PRIVILEGES ON DATABASE inventory_db TO inventory_user;
```

Depois execute:

```bash
python manage.py migrate
```

## Comandos Uteis

### Django

```bash
python manage.py runserver
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic
python manage.py test
```

### Testes por App

```bash
python manage.py test apps.tickets
python manage.py test apps.inventory -v 2
python manage.py test apps.ativos
```

### Rotinas de Tickets

```bash
python manage.py verificar_sla
python manage.py process_ticket_emails --limit 50 --mark-read
python manage.py fechar_tickets --dias 7
```

## APIs e Rotas

### Rotas Principais

| Caminho | Modulo | Descricao |
|---|---|---|
| `/` | `authentication` | Login e rotas de autenticacao |
| `/admin/` | Django Admin | Administracao |
| `/dashboard/` | `home` | Dashboard principal |
| `/usuarios/` | `authentication` | Gestao de usuarios |
| `/tickets/` | `tickets` | Lista e operacao de tickets |
| `/dash/` | `tickets` | Dashboard de tickets |
| `/config/...` | `tickets` | Configuracoes de tickets, SLA, campos, gatilhos e equipes |
| `/api/` | `inventory` | APIs e telas do inventario |
| `/rdp/` | `rdp` | Tela de acesso remoto |
| `/api/rdp/` | `rdp` | API de sinalizacao RDP/WebRTC |

### Documentacao da API

```text
/api/schema/
/api/schema/swagger-ui/
/api/schema/redoc/
```

### Autenticacao da API

O DRF usa `SessionAuthentication` e exige usuario autenticado por padrao.

Limites configurados:

- Anonimos: `30/minute`
- Autenticados: `120/minute`

Endpoints de agente em `inventory` possuem regras proprias e alguns sao intencionalmente sem autenticacao de sessao, pois usam token do agente.

## Sistema de Inventario e Agente Windows

O app `apps.inventory` gerencia maquinas, grupos, sites bloqueados, notificacoes, tokens de agente, versoes de agente, downloads, updates e logs de atividade.

### Modelos Principais

- `MachineGroup`
- `Machine`
- `BlockedSite`
- `Notification`
- `AgentToken`
- `AgentTokenUsage`
- `AgentVersion`
- `AgentDownloadLog`
- `AgentUpdateReport`
- `LogAtividade`

### Endpoints do Inventario

| Caminho | Descricao |
|---|---|
| `/api/machines/` | Lista de maquinas |
| `/api/machines/<id>/` | Detalhe de maquina |
| `/api/groups/` | Grupos de maquinas |
| `/api/blocked-sites/` | Sites bloqueados |
| `/api/run/<machine_id>/` | Execucao de comando em uma maquina |
| `/api/run/bulk/` | Execucao de comando em lote |
| `/api/inventario/checkin/` | Check-in do agente |
| `/api/inventario/health/` | Health check do agente |
| `/api/inventario/agent/validate/` | Validacao de token do agente |
| `/api/inventario/agent/update/` | Consulta de atualizacao |
| `/api/inventario/agent/download/<id>/` | Download de versao do agente |
| `/api/inventario/agent/update-report/` | Relatorio de atualizacao |
| `/api/inventario/agent/activity/` | Envio de atividade do agente |
| `/api/inventario/agent/bootstrap-manifest/` | Manifesto de bootstrap |

### Agente Windows

Arquivos relacionados ao agente ficam em `apps/inventory/agents/`.

Componentes relevantes:

- `agent_service.py`: servico principal do agente.
- `agent_tray.py`: interface de bandeja.
- `install_agent_bootstrap.py`: instalacao/bootstrap.
- `install_agent_silent.py`: instalacao silenciosa.
- `encoder_runtime.py`: runtime auxiliar.
- `notification.py`: notificacoes no Windows.
- `chamados.py`: integracao de chamados no agente.

O agente usa tokens `AgentToken` de 8 caracteres, armazenados como hash SHA-256. O status online/offline da maquina e calculado a partir de `last_seen`.

## Sistema de Tickets e SLA

O app `apps.tickets` implementa atendimento, SLA, automacoes, e-mails e relatorios.

### Modelos Principais

- `Ticket`
- `AcaoTicket`
- `AnexoTicket`
- `HistoricoTicket`
- `Categoria`
- `Urgencia`
- `Status`
- `Justificativa`
- `Servico`
- `ContratoSLA`
- `RegraSLA`
- `CampoAdicional`
- `RegraExibicaoCampo`
- `Gatilho`
- `Macro`
- `PesquisaSatisfacao`
- `ConfiguracaoEmail`
- `HorarioAtendimento`
- `Feriado`
- `TemplateResposta`
- `Equipe`
- `NotificacaoTicket`

### SLA

O SLA suporta dois modos de calculo:

- `corridas`: prazo simples a partir de `criado_em + prazo_horas`.
- `uteis`: considera janelas de atendimento e feriados.

As regras de SLA sao vinculadas a contratos e podem variar por categoria, urgencia, servico e cliente.

### Gatilhos

Os gatilhos sao avaliados em salvamentos de tickets, novas acoes e tarefas de tempo.

Condicoes usam JSON com estruturas como:

```json
{
  "todas": [
    {"campo": "ticket.status", "operador": "igual", "valor": "Novo"}
  ]
}
```

Acoes suportadas incluem:

- Alterar status.
- Alterar responsavel.
- Alterar urgencia.
- Alterar categoria.
- Adicionar nota.
- Adicionar tag.
- Enviar e-mail.

### Tickets por E-mail

O comando `process_ticket_emails` processa mensagens via IMAP e cria tickets automaticamente.

As configuracoes podem vir de:

- Registros ativos em `ConfiguracaoEmail`.
- Fallback `TICKET_EMAIL_CONFIG` em `core/settings.py`.

## Acesso Remoto RDP/WebRTC

O app `apps.rdp` oferece sinalizacao para sessoes remotas.

Rotas principais:

| Caminho | Descricao |
|---|---|
| `/rdp/` | Tela protegida de acesso remoto |
| `/api/rdp/offer/` | Criacao/oferta de sessao |
| `/api/rdp/close/` | Encerramento de sessao |
| `/api/rdp/info/` | Informacoes da sessao |
| `/api/rdp/sessions/` | Listagem de sessoes |
| `/api/rdp/policy/` | Politicas de acesso |
| `/api/rdp/config/` | Configuracoes de conexao |
| `/api/rdp/session-token/` | Token efemero de sessao |
| `/api/rdp/signal/pull/` | Pull de sinal pelo agente |
| `/api/rdp/signal/answer/` | Resposta de sinal pelo agente |

Configuracoes relevantes em `core/settings.py`:

- `RDP_SESSION_TIMEOUT`
- `RDP_MAX_SESSIONS_PER_USER`
- `RDP_SESSION_TOKEN_TTL`
- `RDP_DEFAULT_CONNECTION_MODE`
- `RDP_DEFAULT_QUALITY`
- `RDP_REQUIRE_JUSTIFICATION`
- `RDP_SILENT_ACCESS_ONLY`
- `RDP_ENABLE_REVERSE_SIGNAL`
- `RDP_TURN_CONFIG`

## Tarefas em Segundo Plano

As tarefas de tickets ficam em `apps/tickets/tasks.py`:

| Tarefa | Descricao | Agenda configurada |
|---|---|---|
| `tickets.avaliar_gatilhos_tempo` | Avalia gatilhos por tempo | A cada 5 minutos |
| `tickets.verificar_sla` | Cria alertas de SLA | A cada 15 minutos |
| `tickets.processar_emails` | Processa tickets por e-mail | A cada 5 minutos |
| `tickets.fechar_tickets_resolvidos` | Fecha resolvidos antigos | Diario as 02:00 |
| `tickets.enviar_pesquisa_satisfacao` | Envia pesquisa de satisfacao | A cada hora |
| `tickets.limpar_notificacoes` | Remove notificacoes antigas | Domingo as 03:00 |
| `apps.inventory.tasks.check_machines_status` | Verifica status de maquinas | A cada 5 minutos |

O agendamento esta definido em `CELERY_BEAT_SCHEDULE` dentro de `core/settings.py`.

Para usar Celery, garanta que `celery` e o cliente Redis estejam instalados no ambiente e que o app Celery do projeto esteja configurado. Exemplo de execucao quando o app estiver disponivel:

```bash
celery -A core worker -l info
celery -A core beat -l info
```

Como alternativa sem Celery, algumas rotinas possuem comandos Django:

```bash
python manage.py verificar_sla
python manage.py process_ticket_emails --mark-read
python manage.py fechar_tickets --dias 7
```

## Testes

Execute todos os testes:

```bash
python manage.py test
```

Execute testes especificos:

```bash
python manage.py test apps.tickets
python manage.py test apps.inventory -v 2
```

## Deploy

Checklist recomendado para producao:

1. Definir variaveis reais no `.env` ou no ambiente do servidor.
2. Usar PostgreSQL gerenciado ou instancia dedicada.
3. Definir `DEBUG=False`.
4. Configurar `ALLOWED_HOSTS` com os dominios reais.
5. Externalizar `SECRET_KEY` para variavel de ambiente antes de publicar.
6. Configurar SMTP/IMAP reais para notificacoes e criacao de tickets por e-mail.
7. Configurar servidor TURN para RDP/WebRTC.
8. Executar `python manage.py collectstatic`.
9. Servir a aplicacao via WSGI/ASGI com proxy reverso.
10. Garantir permissao de escrita para `logs/` e `media/`.
11. Configurar backup do banco e dos anexos em `media/`.
12. Subir Redis/Celery se usar rotinas agendadas.

## Seguranca

- Nao versionar `.env`, bancos locais, logs, binarios gerados ou arquivos de agentes sensiveis.
- O `.gitignore` ja ignora `.env`, `.venv`, logs, executaveis, zips, `__pycache__`, agentes e migracoes.
- Revise `SECRET_KEY`, `ALLOWED_HOSTS`, credenciais de e-mail e credenciais TURN antes de producao.
- Endpoints de agente que nao usam sessao devem validar token corretamente.
- Toda query em apps tenant-scoped deve filtrar por `cliente`.
- O projeto possui configuracoes de Django Axes em `settings.py`, mas confirme se o app e middleware estao instalados antes de depender do bloqueio de brute force.

## Troubleshooting

### Erro de conexao com PostgreSQL

Verifique se o servico esta ativo e se `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` e `DB_PORT` estao corretos.

### Arquivos estaticos nao carregam em producao

Execute:

```bash
python manage.py collectstatic
```

Confirme `STATIC_ROOT`, WhiteNoise e a configuracao do servidor web.

### Uploads ou anexos nao aparecem

Confirme `MEDIA_ROOT`, `MEDIA_URL` e as permissoes da pasta `media/`. Em desenvolvimento, arquivos de media so sao servidos automaticamente quando `DEBUG=True`.

### Tickets por e-mail nao sao criados

Verifique configuracoes ativas em `ConfiguracaoEmail` ou o fallback `TICKET_EMAIL_CONFIG`. Confirme IMAP, usuario, senha/app password, caixa `INBOX` e permissao do provedor.

### Agente nao registra check-in

Verifique conectividade com `/api/inventario/health/`, validade do `AgentToken`, relogio da maquina, URL do servidor e logs do agente.

### Atualizacao do agente falha

Confirme se existe `AgentVersion` ativo para o tipo correto, se o arquivo esta acessivel e se hashes/manifestos de bootstrap estao consistentes.

### Celery nao inicia

Confirme instalacao de `celery` e cliente Redis, Redis em `localhost:6379`, configuracao do app Celery e importacao das tasks.

## Licenca

Licenca nao informada neste repositorio.
