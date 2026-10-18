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


def _data_br(iso: str) -> str:
    ano, mes, dia = str(iso)[:10].split("-")
    return f"{dia}/{mes}/{ano}"


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
    elif tipo == "fgts":
        linhas = [
            f"FGTS mensal ({r['categoria']}) sobre {brl(r['base'])}",
            f"• Alíquota: {r['aliquota'] * 100:.1f}%".replace(".", ","),
            f"Depósito do empregador: {brl(r['fgts'])}",
        ]
    elif tipo == "folha":
        linhas = [f"Folha de {r['competencia']}", "", "Proventos:"]
        nomes = {
            "salario_base": "Salário base", "adicionais": "Adicionais", "horas_extras": "Horas extras",
            "dsr_horas_extras": "DSR sobre horas extras", "outros_proventos": "Outros proventos",
        }
        linhas += [f"• {nomes.get(k, k)}: {brl(v)}" for k, v in r["proventos"].items()]
        linhas.append(f"Total de proventos: {brl(r['total_proventos'])}")
        linhas += ["", "Descontos:"]
        nomes_d = {
            "inss": "INSS", "irrf": "IRRF", "vale_transporte": "Vale-transporte",
            "pensao_alimenticia": "Pensão alimentícia", "outros_descontos": "Outros descontos",
        }
        linhas += [f"• {nomes_d.get(k, k)}: {brl(v)}" for k, v in r["descontos"].items()]
        linhas.append(f"Total de descontos: {brl(r['total_descontos'])}")
        linhas += ["", f"Líquido a receber: {brl(r['total_liquido'])}",
                   f"FGTS do empregador (não desconta do empregado): {brl(r['fgts_empregador'])}"]
    elif tipo == "prolabore":
        linhas = [
            f"Pró-labore de {brl(r['prolabore'])} — {r['regime']} (competência {r['competencia']})",
            f"• INSS do sócio (11% sobre {brl(r['base_inss_socio'])}): {brl(r['inss_socio'])}",
            f"• IRRF: {brl(r['irrf'])}",
            f"Líquido do sócio: {brl(r['liquido'])}",
            "",
            f"Contribuição patronal da empresa: {brl(r['inss_patronal'])}",
            f"Custo total para a empresa: {brl(r['custo_total_empresa'])}",
        ]
    elif tipo == "gps":
        linhas = [
            f"GPS — {r['tipo']} (competência {r['competencia']})",
            f"• Base: {brl(r['base'])}",
            f"• Alíquota: {r['aliquota'] * 100:.0f}%",
            f"Valor a pagar: {brl(r['valor'])}",
            f"Vencimento: {_data_br(r['vencimento'])}",
        ]
    elif tipo == "das_mei":
        linhas = [
            f"DAS do MEI — {r['atividade']} (competência {r['competencia']})",
            f"• INSS: {brl(r['inss'])}",
            f"• ICMS: {brl(r['icms'])}  ·  ISS: {brl(r['iss'])}",
            f"Valor a pagar: {brl(r['valor'])}",
            f"Vencimento: {_data_br(r['vencimento'])}",
        ]
    elif tipo == "darf":
        linhas = [
            f"DARF pago em {_data_br(r['pagamento'])} (vencimento {_data_br(r['vencimento'])}, {r['dias_de_atraso']} dia(s) de atraso)",
            f"• Valor principal: {brl(r['valor_principal'])}",
            f"• Multa de mora ({r['taxa_multa'] * 100:.2f}%): {brl(r['multa'])}".replace(".", ","),
            f"• Juros ({r['taxa_juros'] * 100:.2f}%): {brl(r['juros'])}".replace(".", ","),
            f"Total a pagar: {brl(r['total'])}",
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
