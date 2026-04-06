import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.inclusion_tag('tickets/partials/campo_adicional.html', takes_context=True)
def render_campo_adicional(context, campo, regra, valores_existentes=None):
    """Renderiza um campo adicional com seu tipo e regra de exibição."""
    opcoes = []
    if campo.opcoes:
        try:
            opcoes = json.loads(campo.opcoes) if isinstance(campo.opcoes, str) else campo.opcoes
        except (json.JSONDecodeError, TypeError):
            opcoes = []

    valor_atual = ''
    if valores_existentes:
        raw = valores_existentes.get(str(campo.pk), '')
        if isinstance(raw, list):
            valor_atual = raw
        else:
            valor_atual = str(raw)

    obrigatorio = False
    if regra:
        obrigatorio = regra.obrigatoriedade == 'sempre'

    return {
        'campo':        campo,
        'regra':        regra,
        'tipo':         campo.tipo,
        'nome_campo':   f"campo_adicional_{campo.pk}",
        'valor_atual':  valor_atual,
        'opcoes':       opcoes,
        'obrigatorio':  obrigatorio,
        'colunas':      regra.colunas if regra else 12,
        'request':      context.get('request'),
    }


@register.simple_tag(takes_context=True)
def campos_adicionais_json(context):
    """Serializa as regras de campos para uso no JavaScript de exibição condicional."""
    regras = context.get('regras_campos', [])
    dados = []
    for regra in regras:
        dados.append({
            'id':          regra.pk,
            'campo_id':    regra.campo_id,
            'campo_nome':  f"campo_adicional_{regra.campo_id}",
            'condicoes':   regra.condicoes or {},
            'obrigatorio': regra.obrigatoriedade,
            'cond_obrig':  regra.condicoes_obrigatoriedade or {},
            'colunas':     regra.colunas,
            'exibir_para': regra.exibir_para,
        })
    return mark_safe(json.dumps(dados, ensure_ascii=False))