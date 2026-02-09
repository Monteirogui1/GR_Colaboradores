import imaplib
import email
from email.header import decode_header
from datetime import datetime
import re

from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tickets.models import Ticket, Status, StatusBase

User = get_user_model()


class Command(BaseCommand):
    help = 'Processa e-mails recebidos e cria tickets automaticamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Número máximo de e-mails para processar por execução'
        )
        parser.add_argument(
            '--mark-read',
            action='store_true',
            help='Marcar e-mails como lidos após processar'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        mark_read = options['mark_read']

        self.stdout.write('Iniciando processamento de e-mails...')

        # Configurações de e-mail
        email_config = getattr(settings, 'TICKET_EMAIL_CONFIG', {})

        if not email_config:
            self.stdout.write(self.style.ERROR(
                'Configuração TICKET_EMAIL_CONFIG não encontrada em settings.py'
            ))
            return

        try:
            # Conectar ao servidor IMAP
            mail = imaplib.IMAP4_SSL(
                email_config.get('IMAP_SERVER'),
                email_config.get('IMAP_PORT', 993)
            )

            mail.login(
                email_config.get('EMAIL_USER'),
                email_config.get('EMAIL_PASSWORD')
            )

            self.stdout.write(self.style.SUCCESS('Conectado ao servidor de e-mail'))

            # Selecionar caixa de entrada
            mail.select('INBOX')

            # Buscar e-mails não lidos
            status, messages = mail.search(None, 'UNSEEN')

            if status != 'OK':
                self.stdout.write(self.style.ERROR('Erro ao buscar e-mails'))
                return

            email_ids = messages[0].split()
            total_emails = len(email_ids)

            if total_emails == 0:
                self.stdout.write('Nenhum e-mail novo encontrado')
                mail.logout()
                return

            self.stdout.write(f'Encontrados {total_emails} e-mails novos')

            # Processar e-mails (limitado)
            processed = 0
            created = 0
            errors = 0

            for email_id in email_ids[:limit]:
                try:
                    ticket = self.process_email(mail, email_id, email_config)
                    if ticket:
                        created += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'✓ Ticket #{ticket.numero} criado: {ticket.assunto}'
                        ))

                    # Marcar como lido se configurado
                    if mark_read:
                        mail.store(email_id, '+FLAGS', '\\Seen')

                    processed += 1

                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(
                        f'✗ Erro ao processar e-mail {email_id}: {str(e)}'
                    ))

            # Resumo
            self.stdout.write('\n' + '=' * 50)
            self.stdout.write(f'E-mails processados: {processed}')
            self.stdout.write(self.style.SUCCESS(f'Tickets criados: {created}'))
            if errors > 0:
                self.stdout.write(self.style.ERROR(f'Erros: {errors}'))
            self.stdout.write('=' * 50)

            mail.logout()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erro na conexão: {str(e)}'))

    def process_email(self, mail, email_id, config):
        """Processa um e-mail e cria um ticket ou adiciona ação a ticket existente"""

        # Buscar e-mail
        status, msg_data = mail.fetch(email_id, '(RFC822)')

        if status != 'OK':
            return None

        # Parse do e-mail
        email_body = msg_data[0][1]
        email_message = email.message_from_bytes(email_body)

        # Extrair informações
        subject = self.decode_header_value(email_message['Subject'])
        from_email = email.utils.parseaddr(email_message['From'])[1]
        date = email.utils.parsedate_to_datetime(email_message['Date'])
        message_id = email_message.get('Message-ID', '')
        in_reply_to = email_message.get('In-Reply-To', '')
        references = email_message.get('References', '')

        # Extrair corpo do e-mail
        body = self.get_email_body(email_message)

        # Buscar ou criar usuário
        usuario = self.get_or_create_user(from_email, config)

        if not usuario:
            self.stdout.write(self.style.ERROR(
                f'Não foi possível criar usuário para: {from_email}'
            ))
            return None

        # VERIFICAR SE É RESPOSTA A UM TICKET EXISTENTE
        ticket_existente = self.find_existing_ticket(
            subject,
            in_reply_to,
            references,
            from_email
        )

        if ticket_existente:
            # É uma resposta - adicionar como AÇÃO no ticket existente
            return self.add_action_to_ticket(
                ticket_existente,
                usuario,
                body,
                email_message,
                config
            )

        # NÃO É RESPOSTA - Criar novo ticket

        # Verificar duplicatas (apenas para novos tickets)
        if self.is_duplicate(subject, from_email, date):
            self.stdout.write(self.style.WARNING(
                f'E-mail duplicado ignorado: {subject}'
            ))
            return None

        # Buscar cliente
        cliente = self.get_cliente(config)

        # Buscar status padrão "Novo"
        status_novo = Status.objects.filter(
            cliente=cliente,
            status_base=StatusBase.NOVO
        ).first()

        if not status_novo:
            self.stdout.write(self.style.ERROR('Status "Novo" não encontrado'))
            return None

        # Criar ticket
        ticket = Ticket.objects.create(
            cliente=cliente,
            solicitante=usuario,
            status=status_novo,
            assunto=self.clean_subject(subject)[:200],
            descricao=body,
            tipo_ticket='email',
            canal_abertura='email',
            criado_em=timezone.now()
        )

        # Salvar Message-ID para threading futuro
        if message_id:
            ticket.tags = ticket.tags or {}
            ticket.tags['email_message_id'] = message_id
            ticket.save()

        # Processar anexos
        if config.get('PROCESS_ATTACHMENTS', True):
            self.process_attachments(email_message, ticket)

        # Enviar e-mail de confirmação com número do ticket
        if config.get('SEND_CONFIRMATION', True):
            self.send_ticket_confirmation(ticket, usuario)

        return ticket

    def find_existing_ticket(self, subject, in_reply_to, references, from_email):
        """
        Encontra ticket existente baseado em:
        1. Número do ticket no assunto (#2024-000123)
        2. Message-ID nas tags do ticket
        3. Assunto similar recente
        """
        from apps.tickets.models import Ticket

        # Método 1: Buscar número do ticket no assunto
        # Ex: "Re: [Ticket #2024-000123] Sistema travando"
        import re

        # Padrão: #YYYY-NNNNNN ou Ticket #YYYY-NNNNNN
        match = re.search(r'#(\d{4}-\d{6})', subject)
        if match:
            numero = match.group(1)
            try:
                ticket = Ticket.objects.get(numero=numero)
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Resposta identificada para ticket #{ticket.numero}'
                ))
                return ticket
            except Ticket.DoesNotExist:
                pass

        # Método 2: Buscar por Message-ID nos headers de resposta
        if in_reply_to:
            ticket = Ticket.objects.filter(
                tags__email_message_id=in_reply_to
            ).first()
            if ticket:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Resposta identificada via In-Reply-To para ticket #{ticket.numero}'
                ))
                return ticket

        # Método 3: Buscar nas referências (thread completo)
        if references:
            # References pode ter múltiplos Message-IDs
            ref_ids = references.split()
            for ref_id in ref_ids:
                ticket = Ticket.objects.filter(
                    tags__email_message_id=ref_id
                ).first()
                if ticket:
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Resposta identificada via References para ticket #{ticket.numero}'
                    ))
                    return ticket

        # Método 4: Buscar por assunto similar nos últimos 7 dias
        # Remove "Re:", "Fwd:", etc do assunto
        clean_subject = self.clean_subject(subject)

        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=7)

        # Buscar ticket com assunto similar do mesmo solicitante
        ticket = Ticket.objects.filter(
            assunto__icontains=clean_subject[:100],
            solicitante__email=from_email,
            criado_em__gte=cutoff
        ).exclude(
            status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
        ).order_by('-criado_em').first()

        if ticket:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Resposta identificada via assunto similar para ticket #{ticket.numero}'
            ))
            return ticket

        return None

    def clean_subject(self, subject):
        """Remove Re:, Fwd:, etc do assunto"""
        import re

        # Remover prefixos comuns
        cleaned = re.sub(r'^(Re:|RE:|Fwd:|FW:|RES:|ENC:)\s*', '', subject, flags=re.IGNORECASE)

        # Remover [Ticket #XXXX] se existir
        cleaned = re.sub(r'\[Ticket #\d{4}-\d{6}\]\s*', '', cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def add_action_to_ticket(self, ticket, usuario, body, email_message, config):
        """Adiciona uma ação (resposta) a um ticket existente"""
        from apps.tickets.models import AcaoTicket, AnexoTicket

        # Determinar tipo de ação
        # Se o usuário é o solicitante = resposta pública
        # Se é outro usuário (técnico) = resposta pública ou interna
        if usuario == ticket.solicitante:
            tipo_acao = 'publica'
        else:
            # Técnico respondendo
            tipo_acao = 'publica'  # Pode ser configurável

        # Criar ação
        acao = AcaoTicket.objects.create(
            ticket=ticket,
            tipo=tipo_acao,
            autor=usuario,
            conteudo=body,
            criado_em=timezone.now()
        )

        self.stdout.write(self.style.SUCCESS(
            f'✓ Ação adicionada ao ticket #{ticket.numero} por {usuario.email}'
        ))

        # Processar anexos da resposta
        if config.get('PROCESS_ATTACHMENTS', True):
            for part in email_message.walk():
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" in content_disposition:
                    filename = part.get_filename()

                    if filename:
                        filename = self.decode_header_value(filename)
                        file_data = part.get_payload(decode=True)

                        # Limitar tamanho (25MB)
                        if len(file_data) > 25 * 1024 * 1024:
                            continue

                        from django.core.files.base import ContentFile

                        # Criar anexo
                        anexo = AnexoTicket.objects.create(
                            ticket=ticket,
                            autor=usuario,
                            nome_original=filename,
                            tamanho=len(file_data),
                            tipo_mime=part.get_content_type()
                        )

                        anexo.arquivo.save(
                            filename,
                            ContentFile(file_data),
                            save=True
                        )

        # Atualizar status do ticket se necessário
        # Se estava Aguardando Cliente e o cliente respondeu, pode voltar para Em Atendimento
        if ticket.status.status_base == StatusBase.PARADO and usuario == ticket.solicitante:
            status_atendimento = Status.objects.filter(
                cliente=ticket.cliente,
                status_base=StatusBase.EM_ATENDIMENTO
            ).first()

            if status_atendimento:
                ticket.status = status_atendimento
                ticket.save()

                self.stdout.write(self.style.SUCCESS(
                    f'✓ Status do ticket #{ticket.numero} alterado para Em Atendimento'
                ))

        # Notificar responsável se cliente respondeu
        if usuario == ticket.solicitante and ticket.responsavel:
            if config.get('NOTIFY_AGENT_ON_REPLY', True):
                self.notify_agent(ticket, acao)

        # Notificar solicitante se técnico respondeu
        elif usuario != ticket.solicitante:
            if config.get('NOTIFY_CLIENT_ON_REPLY', True):
                self.notify_client(ticket, acao)

        return ticket

    def send_ticket_confirmation(self, ticket, usuario):
        """Envia e-mail de confirmação quando ticket é criado"""
        from django.core.mail import send_mail
        from django.template.loader import render_to_string

        try:
            subject = f'[Ticket #{ticket.numero}] {ticket.assunto}'

            message = f"""
Olá {usuario.get_full_name() or usuario.username},

Seu ticket foi criado com sucesso!

Número do Ticket: #{ticket.numero}
Assunto: {ticket.assunto}
Status: {ticket.status.nome}

Para responder a este ticket, basta responder este e-mail mantendo o número do ticket no assunto.

Você pode acompanhar seu ticket em: {self.get_ticket_url(ticket)}

Atenciosamente,
Equipe de Suporte
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [usuario.email],
                fail_silently=True
            )

            self.stdout.write(self.style.SUCCESS(
                f'✓ E-mail de confirmação enviado para {usuario.email}'
            ))

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f'Não foi possível enviar e-mail de confirmação: {str(e)}'
            ))

    def notify_agent(self, ticket, acao):
        """Notifica agente quando cliente responde"""
        from django.core.mail import send_mail

        if not ticket.responsavel or not ticket.responsavel.email:
            return

        try:
            subject = f'[Ticket #{ticket.numero}] Nova resposta do cliente'

            message = f"""
Olá {ticket.responsavel.get_full_name() or ticket.responsavel.username},

O cliente respondeu ao ticket #{ticket.numero}.

Solicitante: {ticket.solicitante.get_full_name() or ticket.solicitante.email}
Assunto: {ticket.assunto}

Resposta:
{acao.conteudo[:500]}

Acesse: {self.get_ticket_url(ticket)}

Atenciosamente,
Sistema de Tickets
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [ticket.responsavel.email],
                fail_silently=True
            )

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f'Não foi possível notificar agente: {str(e)}'
            ))

    def notify_client(self, ticket, acao):
        """Notifica cliente quando técnico responde"""
        from django.core.mail import send_mail

        if not ticket.solicitante or not ticket.solicitante.email:
            return

        try:
            subject = f'[Ticket #{ticket.numero}] {ticket.assunto}'

            message = f"""
Olá {ticket.solicitante.get_full_name() or ticket.solicitante.username},

Há uma nova resposta no seu ticket #{ticket.numero}.

{acao.conteudo}

Para responder, basta responder este e-mail.

Acesse: {self.get_ticket_url(ticket)}

Atenciosamente,
Equipe de Suporte
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [ticket.solicitante.email],
                fail_silently=True
            )

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f'Não foi possível notificar cliente: {str(e)}'
            ))

    def get_ticket_url(self, ticket):
        """Retorna URL completa do ticket"""
        from django.conf import settings

        base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        return f"{base_url}/tickets/{ticket.pk}/"

    def decode_header_value(self, value):
        """Decodifica header do e-mail"""
        if not value:
            return ''

        decoded = decode_header(value)
        header_parts = []

        for part, encoding in decoded:
            if isinstance(part, bytes):
                try:
                    header_parts.append(part.decode(encoding or 'utf-8'))
                except:
                    header_parts.append(part.decode('utf-8', errors='ignore'))
            else:
                header_parts.append(str(part))

        return ' '.join(header_parts)

    def get_email_body(self, email_message):
        """Extrai o corpo do e-mail (texto ou HTML)"""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Ignorar anexos
                if "attachment" in content_disposition:
                    continue

                # Pegar texto
                if content_type == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except:
                        pass

                # Se não tiver texto, pegar HTML
                elif content_type == "text/html" and not body:
                    try:
                        html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        # Remover tags HTML básicas
                        body = re.sub('<[^<]+?>', '', html_body)
                    except:
                        pass
        else:
            # E-mail não é multipart
            try:
                body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                body = str(email_message.get_payload())

        # Limpar assinaturas automáticas comuns
        body = self.clean_email_body(body)

        return body.strip()

    def clean_email_body(self, body):
        """Remove assinaturas e texto padrão de e-mails"""
        # Remover "-- " e tudo depois (assinatura padrão)
        if '\n-- \n' in body:
            body = body.split('\n-- \n')[0]

        # Remover linhas de resposta/encaminhamento
        lines = body.split('\n')
        cleaned_lines = []

        for line in lines:
            # Ignorar linhas de citação (começam com >)
            if line.strip().startswith('>'):
                continue
            # Ignorar cabeçalhos de resposta
            if re.match(r'^(On|Em) .* wrote:', line):
                break
            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines).strip()

    def get_or_create_user(self, email_address, config):
        """Busca ou cria usuário baseado no e-mail"""
        try:
            user = User.objects.get(email=email_address)
            return user
        except User.DoesNotExist:
            # Criar novo usuário se configurado
            if config.get('AUTO_CREATE_USERS', True):
                # Extrair nome do e-mail
                username = email_address.split('@')[0]
                name = username.replace('.', ' ').title()

                # Garantir username único
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User.objects.create_user(
                    username=username,
                    email=email_address,
                    first_name=name,
                    password=User.objects.make_random_password()
                )
                return user
            return None

    def get_cliente(self, config):
        """Retorna o cliente padrão para tickets por e-mail"""
        cliente_id = config.get('DEFAULT_CLIENTE_ID')

        if cliente_id:
            try:
                return User.objects.get(id=cliente_id)
            except User.DoesNotExist:
                pass

        # Retornar primeiro superuser
        return User.objects.filter(is_superuser=True).first()

    def is_duplicate(self, subject, from_email, date):
        """Verifica se já existe ticket similar (evitar duplicatas)"""
        # Buscar tickets criados nas últimas 24h com mesmo assunto
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=24)

        return Ticket.objects.filter(
            assunto__icontains=subject[:100],
            solicitante__email=from_email,
            criado_em__gte=cutoff
        ).exists()

    def process_attachments(self, email_message, ticket):
        """Processa anexos do e-mail e adiciona ao ticket"""
        from apps.tickets.models import AnexoTicket
        from django.core.files.base import ContentFile

        for part in email_message.walk():
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                filename = part.get_filename()

                if filename:
                    filename = self.decode_header_value(filename)
                    file_data = part.get_payload(decode=True)

                    # Limitar tamanho (25MB)
                    if len(file_data) > 25 * 1024 * 1024:
                        continue

                    # Criar anexo
                    anexo = AnexoTicket.objects.create(
                        ticket=ticket,
                        autor=ticket.solicitante,
                        nome_original=filename,
                        tamanho=len(file_data),
                        tipo_mime=part.get_content_type()
                    )

                    anexo.arquivo.save(
                        filename,
                        ContentFile(file_data),
                        save=True
                    )