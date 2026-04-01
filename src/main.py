print("🚀 Sistema iniciado...\n")

import os
import re
import json
import pdfplumber
from pdf2image import convert_from_path
import pytesseract
import ollama

PASTA_DADOS = "data"


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
    return str(nf).strip().lstrip("0")


def extrair_cnpj(texto):
    match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}", texto)
    return match.group() if match else ""


# =============================
# IDENTIFICAR TIPO
# =============================

def identificar_tipo(texto):
    t = texto.lower()

    if "nota de serviço - cpr" in t:
        return "CPR"
    elif "nota de serviço - dedução" in t:
        return "DEDUCAO"
    elif "autorização de pagamento" in t:
        return "AP"
    elif "relatório fatura" in t:
        return "RELATORIO"
    elif "termo de recebimento" in t:
        return "TERMO"

    # 🔥 NOVA DETECÇÃO DE NF (robusta)
    if (
        "chave de acesso" in t
        or "danfe" in t
        or "nfe.fazenda.gov.br" in t
        or re.search(r"\d{4}\s\d{4}\s\d{4}\s\d{4}", texto)  # chave NF
    ):
        return "NF"

    return "DESCONHECIDO"


# =============================
# EXTRAÇÕES FIXAS
# =============================

def extrair_relatorio(texto):
    dados = {}

    # Número da fatura
    nf = re.search(r"N[ºo]?\s*da\s*Fatura.*?(\d+)", texto, re.IGNORECASE | re.DOTALL)
    if nf:
        dados["numero_fatura"] = nf.group(1)

    # 🔥 abordagem robusta
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
        dados["erro"] = "❌ Termo sem comissão válida"

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
# MAIN
# =============================

def main():
    documentos = []
    textos_nf = []
    problemas = []

    for arquivo in os.listdir(PASTA_DADOS):
        if not arquivo.endswith(".pdf"):
            continue

        caminho = os.path.join(PASTA_DADOS, arquivo)
        print(f"📄 {arquivo}")

        texto = ler_pdf(caminho)

        if not texto.strip():
            print("🔍 OCR...")
            texto = ler_pdf_imagem(caminho)

        if not texto.strip():
            print("❌ Falha leitura\n")
            continue

        tipo = identificar_tipo(texto)

        if tipo == "NF" or tipo == "DESCONHECIDO":
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
        else:
            dados = {}

        dados["tipo"] = tipo
        documentos.append(dados)

        print("➡️", dados, "\n")

    # NF BASE
    nf_base = descobrir_nf_principal(documentos)
    print("NF base:", nf_base, "\n")

    # PROCESSAR NF COM IA
    for texto_nf in textos_nf:
        print("🤖 Processando NF com IA...")

        dados_nf = extrair_nf_ia(texto_nf, nf_base)

        # fallback pesado
        if not dados_nf.get("numero_nota") and nf_base:
            dados_nf["numero_nota"] = nf_base

        if not dados_nf.get("valor_total"):
            valores = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", texto_nf)
            valores = [limpar_valor(v) for v in valores if limpar_valor(v) > 0]
            if valores:
                dados_nf["valor_total"] = max(valores)

        if not dados_nf.get("cnpj"):
            dados_nf["cnpj"] = extrair_cnpj(texto_nf)

        dados_nf["tipo"] = "NF"
        documentos.append(dados_nf)

        print("➡️ NF FINAL:", dados_nf, "\n")

    # VALIDAÇÃO
    for d in documentos:
        nf = limpar_nf(d.get("numero_nota"))
        if nf and nf_base and nf != nf_base:
            problemas.append(f"❌ NF divergente: {nf} vs {nf_base}")

    print("\n=== RESULTADO FINAL ===\n")

    if not problemas:
        print("✅ Tudo consistente")
    else:
        for p in problemas:
            print(p)


if __name__ == "__main__":
    main()