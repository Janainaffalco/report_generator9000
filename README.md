# report_generator9000

Aplicação web que gera o `RELATÓRIO TÉCNICO FINAL` do SEBRAETEC. O fluxo de
produção é executado sem interação durante a geração: enviar a planilha de
controle, escolher um atendimento, revisar a prévia renderizada e baixar o
arquivo `.docx`.

O Gemini é usado somente para os dois campos de prosa permitidos. Capturas,
substituições, proveniência e gates continuam determinísticos.

## Executar a aplicação em contêiner

Construa a imagem:

```powershell
docker build --tag report-generator9000 .
```

Inicie o serviço injetando a configuração pelo ambiente do processo:

```powershell
docker run --rm --publish 8000:8000 --env-file .env report-generator9000
```

A aplicação fica disponível em `http://localhost:8000`. A imagem contém o
pipeline completo e o Chromium usado pelo Playwright. Nenhuma credencial é
copiada durante o build; `.env.example` documenta o contrato de configuração.

## Desenvolvimento

Backend:

```powershell
uv sync
uv run uvicorn report_generator9000.web:app --reload
```

Frontend:

```powershell
Set-Location web
npm ci
npm run dev
```

Para produzir os arquivos estáticos servidos pelo backend:

```powershell
Set-Location web
npm run build
```

## Testes

```powershell
Set-Location web
npm test
npm run lint
npm run typecheck
npm run build

Set-Location ..
uv run pytest
```

## Configuração da VPS

Use `.env.example` como contrato, mas injete valores reais pelo runtime de
contêineres ou pelo gerenciador de processos. Não grave chaves na imagem, no
repositório ou em uma unidade `systemd`.

Em produção, mantenha um identificador estável em `GEMINI_MODEL`, sem aliases
`*-latest`, preview ou experimental. Respostas sem estrutura ou sem citação
literal falham de forma fechada ou viram Pendência.
