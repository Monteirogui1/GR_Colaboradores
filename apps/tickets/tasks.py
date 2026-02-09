from django.core.management import call_command
# from celery import shared_task

# @shared_task
def process_ticket_emails():
    call_command('process_ticket_emails', '--mark-read')