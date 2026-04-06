print("🚀 Sistema iniciado...\n")

import os
import re
import json
import pdfplumber
from pdf2image import convert_from_path
import pytesseract
import ollama

PASTA_DADOS = "data"
TOLERANCIA = 0.05  # margem de R$ 0,05 para comparações de valor


# =============================
# LEITURA PDF
# =============================

def ler_pdf(caminho):
    texto = ""
    try:
        with pdfplumber.open(caminho) as pdf:
            for pagina in pdf.pages:
                conteudo = pagina.extract_text()
                if conteudo:
                    texto += conteudo + "\n"
    except:
        pass
    return texto


def ler_pdf_imagem(caminho):
    texto = ""
    try:
        imagens = convert_from_path(
            caminho,
            poppler_path=r"C:\Users\luizf\OneDrive\Documentos\poppler-25.11.0\Library\bin"
        )
        for img in imagens:
            texto += pytesseract.image_to_string(img) + "\n"
    except:
        pass
    return texto


# =============================
# UTIL
# =============================

def limpar_valor(valor):
    if not valor:
        return 0.0
    valor = str(valor).replace(".", "").replace(",", ".")
    try:
        return float(valor)
    except:
        return 0.0


def limpar_nf(nf):
    if not nf:
        return ""
    # Remove pontos, traços e espaços (ex: "000.261.734" → "000261734")
    nf = re.sub(r"[^\d]", "", str(nf))
    # Remove zeros à esquerda
    return nf.lstrip("0")


def limpar_cnpj(cnpj):
    if not cnpj:
        return ""
    return re.sub(r"[^\d]", "", str(cnpj))


def extrair_cnpj(texto):
    match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}", texto)
    return match.group() if match else ""


def valores_iguais(a, b, tolerancia=TOLERANCIA):
    try:
        return abs(float(a) - float(b)) <= tolerancia
    except:
        return False


def formatar_valor(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(v)


# =============================
# IDENTIFICAR TIPO
# =============================

def identificar_tipo(texto):
    t = texto.lower()

    if "nota de serviço - cpr" in t:
        return "CPR"
    elif "nota de serviço - dedução" in t or "nota de serviço - deducao" in t:
        return "DEDUCAO"
    elif "autorização de pagamento" in t:
        return "AP"
    elif "relatório fatura" in t or "relatorio fatura" in t:
        return "RELATORIO"
    elif "termo de recebimento" in t:
        return "TERMO"
    elif "ordem bancária" in t or "ordem bancaria" in t or "ob n" in t:
        return "OB"

    if (
        "chave de acesso" in t
        or "danfe" in t
        or "danfse" in t
        or "nfs-e" in t
        or "nfse" in t
        or "nfe.fazenda.gov.br" in t
        or "documento auxiliar da nfs" in t
        or re.search(r"\d{4}\s\d{4}\s\d{4}\s\d{4}", texto)
    ):
        return "NF"

    return "DESCONHECIDO"


# =============================
# EXTRAÇÕES FIXAS
# =============================

def extrair_relatorio(texto):
    dados = {}

    nf = re.search(r"N[ºo]?\s*da\s*Fatura.*?(\d+)", texto, re.IGNORECASE | re.DOTALL)
    if nf:
        dados["numero_fatura"] = nf.group(1)

    pos = re.search(r"Valor\s*Fatura", texto, re.IGNORECASE)
    if pos:
        trecho = texto[pos.end():pos.end() + 200]
        valores = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", trecho)
        valores = [limpar_valor(v) for v in valores if limpar_valor(v) > 0]
        if valores:
            dados["valor_total"] = max(valores)

    return dados


def extrair_ap(texto):
    dados = {}

    nf = re.search(r"Nota Fiscal\s*(\d+)", texto)
    if nf:
        dados["numero_nota"] = nf.group(1)

    valor = re.search(r"Valor Total.*?([\d\.,]+)", texto)
    if valor:
        dados["valor_total"] = limpar_valor(valor.group(1))

    cnpj = re.search(r"Fornecedor\s*\(CNPJ\)\s*([\d\./-]+)", texto)
    if cnpj:
        dados["cnpj"] = cnpj.group(1)

    return dados


def extrair_termo(texto):
    dados = {}

    nf = re.search(r"Nota Fiscal\s*(\d+)", texto)
    if nf:
        dados["numero_nota"] = nf.group(1)

    valor = re.search(r"Valor Total.*?([\d\.,]+)", texto)
    if valor:
        dados["valor_total"] = limpar_valor(valor.group(1))

    cnpj = re.search(r"Fornecedor\s*\(CNPJ\)\s*([\d\./-]+)", texto)
    if cnpj:
        dados["cnpj"] = cnpj.group(1)

    if not re.search(r"Ao\(s\).*dia\(s\).*m[eê]s.*ano.*Boletim Interno", texto, re.IGNORECASE):
        dados["aviso"] = "Termo sem comissão identificada"

    return dados


def extrair_cpr(texto):
    dados = {}

    cnpj = re.search(r"FAVORECIDO\s*:\s*([\d\./-]+)", texto)
    if cnpj:
        dados["cnpj"] = cnpj.group(1)

    nf = re.search(r"NF\s*(\d+)", texto)
    if nf:
        dados["numero_nota"] = nf.group(1)

    valores = re.findall(r"\n\s*([\d\.,]+)\s*\n", texto)
    valores = [limpar_valor(v) for v in valores if limpar_valor(v) > 0]
    if valores:
        dados["valor_total"] = max(valores)

    return dados


def extrair_deducao(texto):
    dados = {}

    cnpj = re.search(r"FAVORECIDO\s*:\s*([\d\./-]+)", texto)
    if cnpj:
        dados["cnpj"] = cnpj.group(1)
    else:
        cnpj_gen = extrair_cnpj(texto)
        if cnpj_gen:
            dados["cnpj"] = cnpj_gen

    nf = re.search(r"NF\s*(\d+)", texto, re.IGNORECASE)
    if nf:
        dados["numero_nota"] = nf.group(1)

    # Código de imposto (4+ dígitos isolado, não CNPJ)
    codigos = re.findall(r"(?<!\d)(\d{4,6})(?!\d)", texto)
    codigos = [c for c in codigos if not c.startswith("0") and not re.match(r"^(19|20)\d{2}$", c)]
    if codigos:
        dados["codigo_imposto"] = codigos[0]

    # Valor da dedução — menor valor monetário relevante (imposto/retenção)
    valores = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", texto)
    valores = [limpar_valor(v) for v in valores if limpar_valor(v) > 0]
    if valores:
        dados["valor_total"] = min(valores)

    return dados


def extrair_ob(texto):
    dados = {}

    ob = re.search(r"OB\s*[Nn]?[º°]?\s*(\d+)", texto, re.IGNORECASE)
    if ob:
        dados["numero_ob"] = ob.group(1)

    nf = re.search(r"NF\s*(\d+)", texto, re.IGNORECASE)
    if not nf:
        nf = re.search(r"Nota Fiscal\s*(\d+)", texto, re.IGNORECASE)
    if nf:
        dados["numero_nota"] = nf.group(1)

    cnpj = re.search(r"FAVORECIDO\s*:\s*([\d\./-]+)", texto, re.IGNORECASE)
    if cnpj:
        dados["cnpj"] = cnpj.group(1)
    else:
        cnpj_gen = extrair_cnpj(texto)
        if cnpj_gen:
            dados["cnpj"] = cnpj_gen

    valor = re.search(r"Valor\s*(?:Pago|L[íi]quido|Total).*?([\d\.,]+)", texto, re.IGNORECASE)
    if valor:
        dados["valor_total"] = limpar_valor(valor.group(1))
    else:
        valores = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", texto)
        valores = [limpar_valor(v) for v in valores if limpar_valor(v) > 0]
        if valores:
            dados["valor_total"] = max(valores)

    return dados


# =============================
# IA PARA NF
# =============================

def extrair_nf_ia(texto, nf_base=None):
    texto = texto[:4000]
    referencia = f"O número esperado da nota fiscal é: {nf_base}." if nf_base else ""

    prompt = f"""
{referencia}

Extraia:
numero_nota, data_emissao, valor_total, cnpj

Responda apenas JSON.
Documento:
{texto}
"""

    try:
        response = ollama.chat(
            model="llama3",
            messages=[{"role": "user", "content": prompt}]
        )
        conteudo = response["message"]["content"]
        match = re.search(r"\{.*?\}", conteudo, re.DOTALL)
        if not match:
            return {}
        return json.loads(match.group().replace("'", '"'))
    except:
        return {}


# =============================
# NF BASE
# =============================

def descobrir_nf_principal(documentos):
    contagem = {}
    for d in documentos:
        nf = limpar_nf(d.get("numero_nota"))
        if nf:
            contagem[nf] = contagem.get(nf, 0) + 1
    if not contagem:
        return None
    return max(contagem, key=contagem.get)


# =============================
# VALIDAÇÃO NL / CPR
# =============================

def validar_nl_cpr(documentos, nf_base):
    problemas = []
    avisos = []

    tipos = {d["tipo"]: d for d in documentos}
    ap        = tipos.get("AP", {})
    termo     = tipos.get("TERMO", {})
    cpr       = tipos.get("CPR", {})
    nf        = tipos.get("NF", {})
    relatorio = tipos.get("RELATORIO", {})
    deducao   = tipos.get("DEDUCAO", {})

    # ETAPA 1 — Documentos presentes
    print("\n  [1/5] Verificando documentos presentes...")
    for nome, doc in [("AP", ap), ("TERMO", termo), ("CPR", cpr), ("NF", nf)]:
        if not doc:
            problemas.append(f"Documento ausente: {nome}")
        else:
            print(f"        ✔ {nome} encontrado")
    if not deducao:
        avisos.append("NS Dedução não encontrada — dedução não será verificada")

    # ETAPA 2 — CNPJ
    print("\n  [2/5] Conferindo CNPJ...")
    cnpjs = {}
    for nome, doc in [("AP", ap), ("TERMO", termo), ("CPR", cpr), ("NF", nf)]:
        c = limpar_cnpj(doc.get("cnpj"))
        if c:
            cnpjs[nome] = c

    if cnpjs:
        cnpj_ref = list(cnpjs.values())[0]
        todos_iguais = True
        for nome, c in cnpjs.items():
            if c != cnpj_ref:
                problemas.append(f"CNPJ divergente no {nome}: {c} vs referência {cnpj_ref}")
                todos_iguais = False
        if todos_iguais:
            print(f"        ✔ CNPJ consistente: {cnpj_ref}")
    else:
        avisos.append("CNPJ não encontrado em nenhum documento")

    # ETAPA 3 — Número da NF
    print("\n  [3/5] Conferindo número da NF...")
    nfs = {}
    for nome, doc in [("AP", ap), ("TERMO", termo), ("CPR", cpr), ("NF", nf)]:
        nf_doc = limpar_nf(doc.get("numero_nota"))
        if nf_doc:
            nfs[nome] = nf_doc

    if nf_base:
        todos_iguais = True
        for nome, nf_doc in nfs.items():
            if nf_doc != nf_base:
                problemas.append(f"Número de NF divergente no {nome}: encontrado '{nf_doc}', esperado '{nf_base}'")
                todos_iguais = False
        if todos_iguais and nfs:
            print(f"        ✔ NF {nf_base} consistente em todos os documentos")
    else:
        avisos.append("Não foi possível definir a NF base para comparação")

    # ETAPA 4 — Valor total bruto
    print("\n  [4/5] Conferindo valor total bruto...")
    valores = {}
    for nome, doc in [("AP", ap), ("TERMO", termo), ("CPR", cpr), ("NF", nf)]:
        v = doc.get("valor_total")
        if v:
            valores[nome] = float(v)
    if relatorio.get("valor_total"):
        valores["RELATORIO"] = float(relatorio["valor_total"])

    if valores:
        referencia_valor = list(valores.values())[0]
        todos_iguais = True
        for nome, v in valores.items():
            if not valores_iguais(referencia_valor, v):
                problemas.append(f"Valor divergente no {nome}: {formatar_valor(v)} (referência: {formatar_valor(referencia_valor)})")
                todos_iguais = False
        if todos_iguais:
            print(f"        ✔ Valor bruto consistente: {formatar_valor(referencia_valor)}")
    else:
        avisos.append("Valor total não encontrado em nenhum documento")

    # ETAPA 5 — Dedução
    print("\n  [5/5] Verificando dedução...")
    valor_cpr     = float(cpr.get("valor_total") or 0)
    valor_deducao = float(deducao.get("valor_total") or 0)
    valor_ob_esperado = 0.0

    if valor_cpr and valor_deducao:
        valor_ob_esperado = round(valor_cpr - valor_deducao, 2)
        codigo = deducao.get("codigo_imposto", "não identificado")
        print(f"        Código de imposto : {codigo}")
        print(f"        Valor CPR (bruto) : {formatar_valor(valor_cpr)}")
        print(f"        Valor dedução     : {formatar_valor(valor_deducao)}")
        print(f"        Valor OB esperado : {formatar_valor(valor_ob_esperado)}")
        avisos.append(
            f"OB esperada: {formatar_valor(valor_cpr)} (CPR) - "
            f"{formatar_valor(valor_deducao)} (Dedução) = {formatar_valor(valor_ob_esperado)}"
        )
    elif valor_cpr and not valor_deducao:
        avisos.append("NS Dedução sem valor — não foi possível calcular o valor líquido (OB)")

    return problemas, avisos, valor_ob_esperado


# =============================
# VALIDAÇÃO OB
# =============================

def validar_ob(documentos, valor_ob_esperado=0.0):
    problemas = []
    avisos = []

    tipos = {d["tipo"]: d for d in documentos}
    cpr     = tipos.get("CPR", {})
    deducao = tipos.get("DEDUCAO", {})
    ob      = tipos.get("OB", {})

    for nome, doc in [("CPR", cpr), ("DEDUCAO", deducao)]:
        if not doc:
            avisos.append(f"Aviso: {nome} não encontrado para validação OB")
    if not ob:
        avisos.append("Documento OB não encontrado — confirmação do pagamento não verificada")

    # 1. Valor da OB
    valor_ob = float(ob.get("valor_total") or 0)

    if valor_ob_esperado and valor_ob:
        if valores_iguais(valor_ob, valor_ob_esperado):
            avisos.append(f"Valor OB conferido: {formatar_valor(valor_ob)} ✔ (esperado {formatar_valor(valor_ob_esperado)})")
        else:
            problemas.append(
                f"Valor OB incorreto: documento apresenta {formatar_valor(valor_ob)}, "
                f"esperado {formatar_valor(valor_ob_esperado)}"
            )
    elif valor_ob_esperado and not valor_ob:
        avisos.append(f"Valor esperado da OB é {formatar_valor(valor_ob_esperado)}, mas não foi possível extrair do documento OB")
    elif not valor_ob_esperado:
        avisos.append("Valor OB esperado não calculado — verifique CPR e Dedução no NL/CPR")

    # 2. Número da NF
    nfs_ob = {}
    for nome, doc in [("CPR", cpr), ("DEDUCAO", deducao), ("OB", ob)]:
        nf = limpar_nf(doc.get("numero_nota"))
        if nf:
            nfs_ob[nome] = nf

    if nfs_ob:
        nf_ref = list(nfs_ob.values())[0]
        for nome, nf in nfs_ob.items():
            if nf != nf_ref:
                problemas.append(f"Número de NF divergente no {nome}: '{nf}' vs '{nf_ref}'")

    # 3. CNPJ
    cnpjs_ob = {}
    for nome, doc in [("CPR", cpr), ("DEDUCAO", deducao), ("OB", ob)]:
        cnpj = limpar_cnpj(doc.get("cnpj"))
        if cnpj:
            cnpjs_ob[nome] = cnpj

    if cnpjs_ob:
        cnpj_ref = list(cnpjs_ob.values())[0]
        for nome, c in cnpjs_ob.items():
            if c != cnpj_ref:
                problemas.append(f"CNPJ divergente no {nome}: {c} vs {cnpj_ref}")

    return problemas, avisos


# =============================
# MAIN
# =============================

def main():
    documentos = []
    textos_nf = []

    pasta = os.path.join(os.path.dirname(__file__), PASTA_DADOS)

    for arquivo in os.listdir(pasta):
        if not arquivo.endswith(".pdf"):
            continue

        caminho = os.path.join(pasta, arquivo)
        print(f"📄 {arquivo}")

        texto = ler_pdf(caminho)
        if not texto.strip():
            print("   🔍 Usando OCR...")
            texto = ler_pdf_imagem(caminho)

        if not texto.strip():
            print("   ❌ Falha na leitura\n")
            continue

        tipo = identificar_tipo(texto)
        print(f"   Tipo identificado: {tipo}")

        if tipo in ("NF", "DESCONHECIDO"):
            textos_nf.append(texto)
            continue

        if tipo == "RELATORIO":
            dados = extrair_relatorio(texto)
        elif tipo == "AP":
            dados = extrair_ap(texto)
        elif tipo == "TERMO":
            dados = extrair_termo(texto)
        elif tipo == "CPR":
            dados = extrair_cpr(texto)
        elif tipo == "DEDUCAO":
            dados = extrair_deducao(texto)
        elif tipo == "OB":
            dados = extrair_ob(texto)
        else:
            dados = {}

        dados["tipo"] = tipo
        documentos.append(dados)
        print(f"   ➡️  {dados}\n")

    # NF BASE
    nf_base = descobrir_nf_principal(documentos)
    print(f"📌 NF base identificada: {nf_base}\n")

    # PROCESSAR NF COM IA
    for texto_nf in textos_nf:
        print("🤖 Processando NF com IA...")
        dados_nf = extrair_nf_ia(texto_nf, nf_base)
         # Número da NF: valida o que a IA retornou contra o nf_base
        # nf_base foi confirmado por maioria entre AP, TERMO e CPR — é mais confiável que a IA
        nf_ia = limpar_nf(dados_nf.get("numero_nota") or "")
        if nf_base and nf_ia != nf_base:
            dados_nf["numero_nota"] = nf_base
        elif not nf_ia and nf_base:
            dados_nf["numero_nota"] = nf_base
        # CNPJ: valida o que a IA retornou (precisa ter 14 dígitos)
        # A IA às vezes extrai algo errado (ex: "85555154-00" com só 8 dígitos)
        cnpj_ia = re.sub(r"[^\d]", "", str(dados_nf.get("cnpj") or ""))
        if len(cnpj_ia) != 14:
            dados_nf["cnpj"] = extrair_cnpj(texto_nf)
        # Valor total: SEMPRE usa regex — a IA confunde o formato brasileiro
        # (ex: lê "242.068,40" como 242.0684 em vez de 242068.40)
        valores_regex = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", texto_nf)
        valores_regex = [limpar_valor(v) for v in valores_regex if limpar_valor(v) > 0]
        if valores_regex:
            dados_nf["valor_total"] = max(valores_regex)
        dados_nf["tipo"] = "NF"
        documentos.append(dados_nf)
        print(f"   ➡️  NF FINAL: {dados_nf}\n")

    # PROCEDIMENTO NL / CPR
    print("\n" + "=" * 50)
    print("📋 PROCEDIMENTO NL / CPR")
    print("=" * 50)

    problemas_nl, avisos_nl, valor_ob_esperado = validar_nl_cpr(documentos, nf_base)

    print()
    for aviso in avisos_nl:
        print(f"   ℹ️  {aviso}")

    print()
    if not problemas_nl:
        print("   ✅ NL/CPR: Tudo consistente")
    else:
        print(f"   ⚠️  {len(problemas_nl)} problema(s) encontrado(s) no NL/CPR:")
        for p in problemas_nl:
            print(f"   ❌ {p}")

    # PROCEDIMENTO OB
    print("\n" + "=" * 50)
    print("🏦 PROCEDIMENTO OB (Ordem Bancária)")
    print("=" * 50)

    problemas_ob, avisos_ob = validar_ob(documentos, valor_ob_esperado)

    for aviso in avisos_ob:
        print(f"   ℹ️  {aviso}")

    print()
    if not problemas_ob:
        print("   ✅ OB: Tudo conferido")
    else:
        print(f"   ⚠️  {len(problemas_ob)} problema(s) encontrado(s) na OB:")
        for p in problemas_ob:
            print(f"   ❌ {p}")

    # RESULTADO GERAL
    print("\n" + "=" * 50)
    print("📊 RESULTADO GERAL")
    print("=" * 50)

    total_problemas = problemas_nl + problemas_ob

    if not total_problemas:
        print("✅ Processo aprovado — nenhuma inconsistência encontrada")
    else:
        print(f"⚠️  {len(total_problemas)} problema(s) encontrado(s) no total:")
        for p in total_problemas:
            print(f"   ❌ {p}")


if __name__ == "__main__":
    main()