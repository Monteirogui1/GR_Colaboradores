from django.core.mail import send_mail

def enviar_email_estoque_minimo(variacao):
    produto = variacao.produto
    assunto = f"[ALERTA] Estoque mínimo - {produto.nome} ({variacao.tamanho})"
    mensagem = (
        f"O produto '{produto.nome}' (Tamanho: {variacao.tamanho}) atingiu o estoque mínimo!\n\n"
        f"Quantidade atual: {variacao.quantidade}\n"
        f"Estoque mínimo: {variacao.estoque_minimo}\n"
        "Favor providenciar a reposição."
    )
    destinatario = ["suporte@frilog.com.br"]
    send_mail(
        assunto,
        mensagem,
        None,  # from_email (usa DEFAULT_FROM_EMAIL)
        destinatario,
        fail_silently=False,
    )
