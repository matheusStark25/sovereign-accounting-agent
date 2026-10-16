"""Formatação em português (BRL) dos resultados do motor, para chat, PDF e relatórios."""

from __future__ import annotations

from typing import Any, Dict, List


def brl(valor: Any) -> str:
    """12345.6 -> 'R$ 12.345,60'."""
    if valor is None:
        return "—"
    texto = f"{float(valor):,.2f}"
    inteiro, _, dec = texto.partition(".")
    return "R$ " + inteiro.replace(",", ".") + "," + dec


def _linhas_rescisao(r: Dict[str, Any]) -> List[str]:
    nomes = {
        "sem_justa_causa": "dispensa sem justa causa",
        "justa_causa": "dispensa por justa causa",
        "pedido_demissao": "pedido de demissão",
        "acordo": "acordo (art. 484-A da CLT)",
    }
    linhas = [f"Rescisão — {nomes.get(r['tipo'], r['tipo'])}", ""]
    d = r["datas"]
    linhas.append(
        f"Admissão {d['admissao'][8:10]}/{d['admissao'][5:7]}/{d['admissao'][:4]} · "
        f"Demissão {d['demissao'][8:10]}/{d['demissao'][5:7]}/{d['demissao'][:4]} · "
        f"{d['anos_completos']} ano(s) completo(s)"
    )
    linhas.append("")
    linhas.append("Verbas:")
    for v in r["verbas"]:
        linhas.append(f"• {v['descricao']}: {brl(v['valor'])}")
    linhas.append(f"Total de proventos: {brl(r['total_proventos'])}")
    if r["descontos"]:
        linhas.append("")
        linhas.append("Descontos:")
        for x in r["descontos"]:
            if x["valor"]:
                linhas.append(f"• {x['descricao']}: {brl(x['valor'])}")
        linhas.append(f"Total de descontos: {brl(r['total_descontos'])}")
    linhas.append("")
    linhas.append(f"Líquido a receber: {brl(r['total_liquido'])}")
    f = r["fgts"]
    linhas.append("")
    linhas.append("FGTS (valores à parte, depositados pelo empregador):")
    linhas.append(f"• Depósito sobre as verbas rescisórias: {brl(f['deposito_rescisorio'])}")
    if f.get("multa_aliquota"):
        if f.get("multa") is None:
            linhas.append(f"• Multa de {int(f['multa_aliquota'] * 100)}%: informe o saldo do FGTS para calcular")
        else:
            linhas.append(f"• Multa de {int(f['multa_aliquota'] * 100)}%: {brl(f['multa'])}")
    linhas.append(f"• Saque do FGTS: {r['direitos']['saque_fgts_percentual']}%")
    if r["direitos"]["seguro_desemprego"]:
        linhas.append("• Seguro-desemprego: possível, sujeito aos requisitos legais")
    return linhas


def formatar_resultado(tipo: str, r: Dict[str, Any]) -> str:
    """Texto pronto para o usuário. Nunca esconde pendências nem premissas."""
    if tipo == "rescisao":
        linhas = _linhas_rescisao(r)
    elif tipo == "ferias":
        linhas = [
            f"Férias — {r['dias_gozados']} dia(s) gozado(s)" + (f" e {r['dias_vendidos']} vendido(s)" if r["dias_vendidos"] else ""),
            f"• Valor dos dias: {brl(r['valor_dias'])}",
            f"• 1/3 constitucional: {brl(r['terco_constitucional'])}",
        ]
        if r["dias_vendidos"]:
            linhas += [f"• Abono pecuniário: {brl(r['abono_pecuniario'])}", f"• 1/3 do abono: {brl(r['terco_abono'])}"]
        linhas += [f"• INSS: {brl(r['inss'])}", f"• IRRF: {brl(r['irrf'])}", f"Total bruto: {brl(r['total_bruto'])}",
                   f"Líquido a receber: {brl(r['total_liquido'])}"]
    elif tipo == "decimo_terceiro":
        linhas = [
            f"13º salário — {r['meses']}/12",
            f"• Valor total: {brl(r['total_bruto'])}",
            f"• 1ª parcela (até 30/11, sem descontos): {brl(r['primeira_parcela'])}",
            f"• INSS: {brl(r['inss'])}  ·  IRRF: {brl(r['irrf'])}",
            f"• 2ª parcela (até 20/12): {brl(r['segunda_parcela'])}",
            f"Total líquido: {brl(r['total_liquido'])}",
        ]
    elif tipo == "inss":
        linhas = [f"INSS do empregado sobre {brl(r['base'])} (competência {r['competencia']})"]
        for p in r["faixas"]:
            linhas.append(f"• {p['aliquota'] * 100:.1f}% sobre {brl(p['base_na_faixa'])}: {brl(p['valor'])}")
        if r["base"] > r["base_limitada_ao_teto"]:
            linhas.append(f"(base limitada ao teto de {brl(r['base_limitada_ao_teto'])})")
        linhas.append(f"Total: {brl(r['inss'])}")
    elif tipo == "irrf":
        linhas = [
            f"IRRF sobre rendimentos de {brl(r['rendimentos_tributaveis'])} (competência {r['competencia']})",
            f"• Dedução usada: {'desconto simplificado' if r['opcao_deducao'] == 'simplificado' else 'deduções legais (INSS, dependentes, pensão)'}",
            f"• Base de cálculo: {brl(r['base_calculo'])}",
            f"• Imposto pela tabela: {brl(r['imposto_tabela'])}",
            f"• Redução da Lei 15.270/2025: {brl(r['reducao'])}",
            f"IRRF devido: {brl(r['irrf'])}",
        ]
    else:
        linhas = [str(r)]

    for aviso in r.get("pendencias", []):
        linhas += ["", f"Pendência: {aviso}"]
    avisos = r.get("avisos")
    if avisos:
        linhas += ["", "Premissas:"] + [f"• {a}" for a in avisos]
    tabela = r.get("tabelas") or r.get("tabela")
    if tabela:
        linhas += ["", "Tabelas: " + (tabela if isinstance(tabela, str) else "; ".join(f"{k}: {v}" for k, v in tabela.items()))]
    return "\n".join(linhas)
