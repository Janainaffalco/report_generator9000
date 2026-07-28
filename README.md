# report_generator9000

CLI determinístico para gerar o `RELATÓRIO TÉCNICO FINAL` do SEBRAETEC.
O Gemini é usado somente para os dois campos de prosa permitidos; Captures,
substituições, Provenance e gates continuam determinísticos.

## Preparação local

```powershell
uv sync
Copy-Item .env.example .env
```

Preencha `GEMINI_API_KEY` no `.env`. O arquivo `.env` é ignorado pelo Git.
O projeto usa o SDK atual `google-genai`; não usa o pacote legado
`google-generativeai`.

Instale o Chromium do Playwright quando necessário:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
uv run playwright install chromium
```

## Gerar um relatório

Com Gemini:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
uv run python .\gerar_relatorio.py --linha 115-2026
```

Sem chamada ao modelo:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
uv run python .\gerar_relatorio.py --linha 115-2026 --no-llm
```

Valores da linha de comando `--prose-model` e
`--prose-output-budget` substituem os defaults do ambiente. O parâmetro
`--prose-provider` continua disponível para testes ou outro provedor.
Quando o modelo primário responde especificamente com `503 UNAVAILABLE`, o
provider tenta uma vez o `GEMINI_FALLBACK_MODEL`. Outros erros não acionam
fallback.

## Implantação em VPS

Use `.env.example` como contrato de configuração, mas injete os valores reais
pelo gerenciador de processos ou runtime de containers. Não copie uma chave
para a imagem, repositório ou unidade `systemd`.

Para produção, mantenha um identificador estável em `GEMINI_MODEL`, e não um
alias `*-latest`, preview ou experimental. O provider configura timeout,
tentativas limitadas para falhas transitórias, saída JSON estruturada e baixo
nível de thinking para esta tarefa curta. Qualquer resposta sem estrutura ou
sem citação literal falha fechada ou vira Pendência.
